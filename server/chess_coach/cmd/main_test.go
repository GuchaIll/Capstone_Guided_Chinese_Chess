package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	chess "chess_coach"
	"chess_coach/engine"
	chesstools "chess_coach/tools"
	"go_agent_framework/contrib/llm"
	"go_agent_framework/core"
)

const testHandlerFEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"

func newChatHandlerTestGraph(t *testing.T, eng engine.EngineClient, models llm.Models) *core.Graph {
	t.Helper()
	toolReg := core.NewToolRegistry()
	if err := chesstools.RegisterChessTools(toolReg, eng); err != nil {
		t.Fatalf("register chess tools: %v", err)
	}
	if err := chesstools.RegisterPuzzleDetectorTools(toolReg, eng); err != nil {
		t.Fatalf("register puzzle tools: %v", err)
	}
	return chess.BuildGraph(toolReg, core.NewSkillRegistry(), models)
}

func decodeChatResponse(t *testing.T, body []byte) struct {
	SessionID string                 `json:"session_id"`
	Response  string                 `json:"response"`
	State     map[string]interface{} `json:"state"`
} {
	t.Helper()
	var resp struct {
		SessionID string                 `json:"session_id"`
		Response  string                 `json:"response"`
		State     map[string]interface{} `json:"state"`
	}
	if err := json.Unmarshal(body, &resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return resp
}

func TestMakeChatHandlerReturnsAgentGeneratedExplanation(t *testing.T) {
	graph := newChatHandlerTestGraph(t, &engine.MockEngine{}, llm.Models{
		Analysis:      &llm.MockLLM{Response: "Play b0c2 to control the center before attacking."},
		Orchestration: &llm.MockLLM{Response: "EXPLAIN"},
	})
	store := core.NewMemStore()
	sessionID := "chat-handler-session"
	if err := store.Put(&core.Session{
		ID:    sessionID,
		State: map[string]interface{}{},
	}); err != nil {
		t.Fatalf("seed session: %v", err)
	}

	handler := makeChatHandler(graph, store)

	body, _ := json.Marshal(map[string]interface{}{
		"message":    "Explain this Xiangqi position.",
		"session_id": sessionID,
		"fen":        testHandlerFEN,
		"move":       "b0c2",
	})
	req := httptest.NewRequest(http.MethodPost, "/dashboard/chat", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", rr.Code, rr.Body.String())
	}

	resp := decodeChatResponse(t, rr.Body.Bytes())
	if resp.SessionID != sessionID {
		t.Fatalf("session mismatch: got %q", resp.SessionID)
	}
	if !strings.Contains(resp.Response, "Evaluation:") {
		t.Fatalf("response missing fast-path analysis: %q", resp.Response)
	}
	if strings.Contains(resp.Response, "Coaching advice [") {
		t.Fatalf("ordinary chat request should stay on fast path unless explicitly triggered: %q", resp.Response)
	}
	if _, ok := resp.State["engine_metrics"]; !ok {
		t.Fatalf("response state missing engine_metrics: %#v", resp.State)
	}
	if _, ok := resp.State["feedback"]; !ok {
		t.Fatalf("response state missing feedback: %#v", resp.State)
	}
}

func TestMakeChatHandlerPreservesSessionContextAcrossFollowups(t *testing.T) {
	graph := newChatHandlerTestGraph(t, &engine.MockEngine{}, llm.Models{
		Analysis:      &llm.MockLLM{Response: "Play b0c2 to control the center before attacking."},
		Orchestration: &llm.MockLLM{Response: "EXPLAIN"},
	})
	store := core.NewMemStore()
	handler := makeChatHandler(graph, store)
	sessionID := "chat-continuity-session"

	firstBody, _ := json.Marshal(map[string]interface{}{
		"message":    "Explain this Xiangqi position.",
		"session_id": sessionID,
		"fen":        testHandlerFEN,
		"move":       "b0c2",
	})
	firstReq := httptest.NewRequest(http.MethodPost, "/dashboard/chat", bytes.NewReader(firstBody))
	firstReq.Header.Set("Content-Type", "application/json")
	firstRR := httptest.NewRecorder()
	handler(firstRR, firstReq)

	if firstRR.Code != http.StatusOK {
		t.Fatalf("first request unexpected status %d: %s", firstRR.Code, firstRR.Body.String())
	}

	secondBody, _ := json.Marshal(map[string]interface{}{
		"message":    "Why was that move good?",
		"session_id": sessionID,
	})
	secondReq := httptest.NewRequest(http.MethodPost, "/dashboard/chat", bytes.NewReader(secondBody))
	secondReq.Header.Set("Content-Type", "application/json")
	secondRR := httptest.NewRecorder()
	handler(secondRR, secondReq)

	if secondRR.Code != http.StatusOK {
		t.Fatalf("second request unexpected status %d: %s", secondRR.Code, secondRR.Body.String())
	}

	resp := decodeChatResponse(t, secondRR.Body.Bytes())
	if got, _ := resp.State["fen"].(string); got != testHandlerFEN {
		t.Fatalf("follow-up request should retain previous fen, got %q", got)
	}
	if got, _ := resp.State["move"].(string); got != "b0c2" {
		t.Fatalf("follow-up request should retain previous move, got %q", got)
	}
	if !strings.Contains(resp.Response, "Evaluation:") {
		t.Fatalf("follow-up response should still have analysis context: %q", resp.Response)
	}
}

func TestMakeAnalyzeHandlerReturnsMetricsAndExplanation(t *testing.T) {
	graph := newChatHandlerTestGraph(t, &engine.MockEngine{}, llm.Models{
		Analysis:      &llm.MockLLM{Response: "Play b0c2 to control the center before attacking."},
		Orchestration: &llm.MockLLM{Response: "ANALYZE"},
	})
	store := core.NewMemStore()
	handler := makeAnalyzeHandler(graph, store)

	body, _ := json.Marshal(map[string]interface{}{
		"fen":   testHandlerFEN,
		"depth": 6,
	})
	req := httptest.NewRequest(http.MethodPost, "/coach/analyze", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", rr.Code, rr.Body.String())
	}

	var resp struct {
		SessionID string                 `json:"session_id"`
		Response  string                 `json:"response"`
		Metrics   map[string]interface{} `json:"metrics"`
		GamePhase string                 `json:"game_phase"`
		Material  map[string]interface{} `json:"material"`
	}
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}

	if resp.Response == "" || !strings.Contains(resp.Response, "Evaluation:") {
		t.Fatalf("analyze response missing explanation: %q", resp.Response)
	}
	if resp.GamePhase != "opening" {
		t.Fatalf("game_phase = %q", resp.GamePhase)
	}
	if _, ok := resp.Metrics["search_score"]; !ok {
		t.Fatalf("metrics missing search_score: %#v", resp.Metrics)
	}
	if len(resp.Material) == 0 {
		t.Fatalf("material should not be empty")
	}
}

func TestMakeFeaturesHandlerReturnsRequestedFeatureSubset(t *testing.T) {
	toolReg := core.NewToolRegistry()
	if err := chesstools.RegisterChessTools(toolReg, &engine.MockEngine{}); err != nil {
		t.Fatalf("register chess tools: %v", err)
	}
	handler := makeFeaturesHandler(toolReg)

	body, _ := json.Marshal(map[string]interface{}{
		"fen":      testHandlerFEN,
		"features": "material,forks,pins",
	})
	req := httptest.NewRequest(http.MethodPost, "/coach/features", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", rr.Code, rr.Body.String())
	}

	var resp map[string]interface{}
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if _, ok := resp["material"]; !ok {
		t.Fatalf("features response missing material: %#v", resp)
	}
	if _, ok := resp["forks"]; !ok {
		t.Fatalf("features response missing forks: %#v", resp)
	}
	if _, ok := resp["pins"]; !ok {
		t.Fatalf("features response missing pins: %#v", resp)
	}
}

func TestMakeClassifyMoveHandlerReturnsClassificationPayload(t *testing.T) {
	toolReg := core.NewToolRegistry()
	if err := chesstools.RegisterChessTools(toolReg, &engine.MockEngine{}); err != nil {
		t.Fatalf("register chess tools: %v", err)
	}
	handler := makeClassifyMoveHandler(toolReg)

	body, _ := json.Marshal(map[string]interface{}{
		"fen":  testHandlerFEN,
		"move": "b0c2",
	})
	req := httptest.NewRequest(http.MethodPost, "/coach/classify-move", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", rr.Code, rr.Body.String())
	}

	var resp map[string]interface{}
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if got, _ := resp["move"].(string); got != "b0c2" {
		t.Fatalf("move = %q", got)
	}
	if _, ok := resp["classification"]; !ok {
		t.Fatalf("classify response missing classification: %#v", resp)
	}
}
