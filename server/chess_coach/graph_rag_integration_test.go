package chess

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"unicode"

	"chess_coach/engine"
	chesstools "chess_coach/tools"
	"go_agent_framework/contrib/llm"
	"go_agent_framework/core"
)

type knowledgeChunk struct {
	ChunkID string   `json:"chunk_id"`
	Text    string   `json:"text"`
	Title   string   `json:"title"`
	Topic   string   `json:"topic"`
	Tags    []string `json:"tags"`
}

type knowledgeCollection struct {
	Chunks []knowledgeChunk `json:"chunks"`
}

type knowledgeBase struct {
	Collections map[string]knowledgeCollection `json:"collections"`
}

type fileKnowledgeRetriever struct {
	chunks []knowledgeChunk
}

func (r *fileKnowledgeRetriever) Retrieve(_ context.Context, query string, topK int) ([]core.Chunk, error) {
	if topK <= 0 {
		topK = 5
	}

	queryTokens := tokenizeForRetrieval(query)
	type scored struct {
		chunk core.Chunk
		score int
	}
	scoredChunks := make([]scored, 0, len(r.chunks))
	for _, entry := range r.chunks {
		haystack := strings.ToLower(strings.Join(append([]string{entry.Title, entry.Topic, entry.Text}, entry.Tags...), " "))
		score := 0
		for _, token := range queryTokens {
			if strings.Contains(haystack, token) {
				score++
			}
		}
		if score == 0 {
			continue
		}
		scoredChunks = append(scoredChunks, scored{
			chunk: core.Chunk{
				ID:      entry.ChunkID,
				Content: entry.Text,
				Score:   float32(score),
			},
			score: score,
		})
	}

	sort.Slice(scoredChunks, func(i, j int) bool {
		if scoredChunks[i].score == scoredChunks[j].score {
			return scoredChunks[i].chunk.ID < scoredChunks[j].chunk.ID
		}
		return scoredChunks[i].score > scoredChunks[j].score
	})

	if len(scoredChunks) > topK {
		scoredChunks = scoredChunks[:topK]
	}

	out := make([]core.Chunk, len(scoredChunks))
	for i, item := range scoredChunks {
		out[i] = item.chunk
	}
	return out, nil
}

type capturingLLM struct {
	response string
	prompts  []string
}

func (c *capturingLLM) Generate(_ context.Context, prompt string) (string, error) {
	c.prompts = append(c.prompts, prompt)
	return c.response, nil
}

func (c *capturingLLM) Provider() string { return "capturing" }
func (c *capturingLLM) Model() string    { return "capturing-llm" }

func loadKnowledgeBaseRetriever(t *testing.T, collection string) core.Retriever {
	t.Helper()

	path := filepath.Join("..", "web_scraper", "knowledge", "json", "knowledge_base.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read knowledge base: %v", err)
	}

	var kb knowledgeBase
	if err := json.Unmarshal(data, &kb); err != nil {
		t.Fatalf("parse knowledge base: %v", err)
	}

	collectionData, ok := kb.Collections[collection]
	if !ok {
		t.Fatalf("missing collection %q in knowledge base", collection)
	}

	return &fileKnowledgeRetriever{chunks: collectionData.Chunks}
}

func registerRealRAGTools(t *testing.T, reg *core.ToolRegistry) {
	t.Helper()
	retrievers := map[string]core.Retriever{
		"openings":            loadKnowledgeBaseRetriever(t, "openings"),
		"tactics":             loadKnowledgeBaseRetriever(t, "tactics"),
		"endgames":            loadKnowledgeBaseRetriever(t, "endgames"),
		"beginner_principles": loadKnowledgeBaseRetriever(t, "beginner_principles"),
	}
	if err := chesstools.RegisterRAGTools(reg, retrievers); err != nil {
		t.Fatalf("register rag tools: %v", err)
	}
}

func tokenizeForRetrieval(text string) []string {
	lower := strings.ToLower(text)
	fields := strings.FieldsFunc(lower, func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsNumber(r)
	})
	out := make([]string, 0, len(fields))
	seen := make(map[string]struct{}, len(fields))
	for _, field := range fields {
		if len(field) < 3 {
			continue
		}
		if _, ok := seen[field]; ok {
			continue
		}
		seen[field] = struct{}{}
		out = append(out, field)
	}
	return out
}

func TestBuildGraphFastPathIncludesOpeningRAGFromKnowledgeBase(t *testing.T) {
	toolReg := core.NewToolRegistry()
	mockEngine := &engine.MockEngine{}
	if err := chesstools.RegisterChessTools(toolReg, mockEngine); err != nil {
		t.Fatalf("register chess tools: %v", err)
	}
	if err := chesstools.RegisterPuzzleDetectorTools(toolReg, mockEngine); err != nil {
		t.Fatalf("register puzzle tools: %v", err)
	}
	registerRealRAGTools(t, toolReg)

	graph := BuildGraph(toolReg, core.NewSkillRegistry(), llm.Models{
		Analysis:      &countingLLM{response: "unused on fast path"},
		Orchestration: &countingLLM{response: "EXPLAIN"},
	})

	ctx := newGraphContext(map[string]interface{}{
		"fen":                    testGraphFEN,
		"question":               "How should I develop my pieces in the opening?",
		"moves_since_last_coach": 0,
	})

	if err := graph.Run(ctx); err != nil {
		t.Fatalf("graph run: %v", err)
	}

	ragContext, ok := ctx.State["rag_context"].(map[string]interface{})
	if !ok {
		t.Fatalf("rag_context missing: %#v", ctx.State["rag_context"])
	}
	opening, ok := ragContext["opening"].(map[string]interface{})
	if !ok {
		t.Fatalf("opening rag section missing: %#v", ragContext)
	}
	openingText, _ := opening["text"].(string)
	if strings.TrimSpace(openingText) == "" {
		t.Fatalf("opening rag text missing: %#v", opening)
	}

	feedback, _ := ctx.State["feedback"].(string)
	if !strings.Contains(feedback, "Guidance [opening]:") {
		t.Fatalf("feedback missing compact opening guidance: %q", feedback)
	}
	if strings.Contains(feedback, openingText) {
		t.Fatalf("feedback should no longer dump the full raw RAG block.\nFeedback: %q\nRAG: %q", feedback, openingText)
	}
}

func TestBuildGraphSlowPathInjectsOpeningRAGIntoCoachPrompt(t *testing.T) {
	toolReg := core.NewToolRegistry()
	mockEngine := &engine.MockEngine{}
	if err := chesstools.RegisterChessTools(toolReg, mockEngine); err != nil {
		t.Fatalf("register chess tools: %v", err)
	}
	if err := chesstools.RegisterPuzzleDetectorTools(toolReg, mockEngine); err != nil {
		t.Fatalf("register puzzle tools: %v", err)
	}
	registerRealRAGTools(t, toolReg)

	coachLLM := &capturingLLM{response: "Use your pieces efficiently and contest the center."}
	graph := BuildGraph(toolReg, core.NewSkillRegistry(), llm.Models{
		Analysis:      coachLLM,
		Orchestration: &countingLLM{response: "EXPLAIN"},
	})

	ctx := newGraphContext(map[string]interface{}{
		"fen":                    testGraphFEN,
		"question":               "What should I focus on in the opening?",
		"moves_since_last_coach": 3,
	})

	if err := graph.Run(ctx); err != nil {
		t.Fatalf("graph run: %v", err)
	}

	if len(coachLLM.prompts) != 1 {
		t.Fatalf("expected one coach prompt, got %d", len(coachLLM.prompts))
	}
	prompt := coachLLM.prompts[0]
	if !strings.Contains(prompt, "Relevant knowledge from the library:") {
		t.Fatalf("coach prompt missing rag header: %q", prompt)
	}

	ragContext, ok := ctx.State["rag_context"].(map[string]interface{})
	if !ok {
		t.Fatalf("rag_context missing: %#v", ctx.State["rag_context"])
	}
	opening, ok := ragContext["opening"].(map[string]interface{})
	if !ok {
		t.Fatalf("opening rag context missing: %#v", ragContext)
	}
	openingText, _ := opening["text"].(string)
	if strings.TrimSpace(openingText) == "" {
		t.Fatalf("opening rag text empty: %#v", opening)
	}
	if !strings.Contains(prompt, openingText) {
		t.Fatalf("coach prompt should contain retrieved opening guidance.\nPrompt: %q\nRAG: %q", prompt, openingText)
	}
}
