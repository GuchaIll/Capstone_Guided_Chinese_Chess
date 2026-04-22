package chesstools

import (
	"context"
	"encoding/json"
	"testing"

	"go_agent_framework/core"
)

type mockRetriever struct {
	lastQuery string
	lastTopK  int
}

func (m *mockRetriever) Retrieve(_ context.Context, query string, topK int) ([]core.Chunk, error) {
	m.lastQuery = query
	m.lastTopK = topK
	return []core.Chunk{{ID: "doc-1", Content: "sample", Score: 0.9}}, nil
}

func TestNewChromaDBRetrieversIncludesRequiredCollections(t *testing.T) {
	retrievers := NewChromaDBRetrievers("http://chromadb:8000", "http://embedding:8100")

	for _, name := range []string{"openings", "tactics", "endgames", "beginner_principles"} {
		if _, ok := retrievers[name]; !ok {
			t.Fatalf("expected retriever for collection %q", name)
		}
	}
}

func TestRegisterRAGToolsMatchesSpec(t *testing.T) {
	reg := core.NewToolRegistry()
	retrievers := map[string]core.Retriever{
		"openings":            &mockRetriever{},
		"tactics":             &mockRetriever{},
		"endgames":            &mockRetriever{},
		"beginner_principles": &mockRetriever{},
	}

	if err := RegisterRAGTools(reg, retrievers); err != nil {
		t.Fatalf("register rag tools: %v", err)
	}

	expectedParams := map[string]string{
		"get_opening_plan":         "position_description",
		"get_middlegame_theme":     "position_features",
		"get_endgame_principle":    "position_features",
		"get_general_advice":       "user_question",
		"explain_tactic":           "user_question",
		"explain_puzzle_objective": "puzzle_context",
	}

	for toolName, firstParam := range expectedParams {
		tool, ok := reg.Get(toolName)
		if !ok {
			t.Fatalf("expected tool %q to be registered", toolName)
		}
		params := tool.Parameters()
		if len(params) == 0 || params[0].Name != firstParam {
			t.Fatalf("%s first parameter mismatch: got %+v, want %q", toolName, params, firstParam)
		}
	}
}

func TestRAGToolsUseExpectedQuerySources(t *testing.T) {
	openings := &mockRetriever{}
	tactics := &mockRetriever{}
	endgames := &mockRetriever{}
	principles := &mockRetriever{}
	reg := core.NewToolRegistry()
	if err := RegisterRAGTools(reg, map[string]core.Retriever{
		"openings":            openings,
		"tactics":             tactics,
		"endgames":            endgames,
		"beginner_principles": principles,
	}); err != nil {
		t.Fatalf("register rag tools: %v", err)
	}

	cases := []struct {
		name          string
		args          map[string]interface{}
		retriever     *mockRetriever
		expectedQuery string
	}{
		{
			name:          "get_opening_plan",
			args:          map[string]interface{}{"position_description": "central cannon opening"},
			retriever:     openings,
			expectedQuery: "central cannon opening",
		},
		{
			name:          "get_middlegame_theme",
			args:          map[string]interface{}{"position_features": "forks pins cannon pressure"},
			retriever:     tactics,
			expectedQuery: "forks pins cannon pressure",
		},
		{
			name:          "get_endgame_principle",
			args:          map[string]interface{}{"position_features": "rook endgame active king"},
			retriever:     endgames,
			expectedQuery: "rook endgame active king",
		},
		{
			name:          "get_general_advice",
			args:          map[string]interface{}{"user_question": "How should I improve my opening play?"},
			retriever:     principles,
			expectedQuery: "How should I improve my opening play?",
		},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			body, _ := json.Marshal(tc.args)
			result := reg.ExecuteTool(context.Background(), core.ToolCall{
				ID:   "call-1",
				Name: tc.name,
				Args: body,
			})
			if result.Error != "" {
				t.Fatalf("tool execution failed: %s", result.Error)
			}
			if tc.retriever.lastQuery != tc.expectedQuery {
				t.Fatalf("query mismatch: got %q want %q", tc.retriever.lastQuery, tc.expectedQuery)
			}
		})
	}
}

func TestExplainTacticUsesBeginnerPrinciplesAndMoveContext(t *testing.T) {
	tactics := &mockRetriever{}
	principles := &mockRetriever{}
	reg := core.NewToolRegistry()
	if err := RegisterRAGTools(reg, map[string]core.Retriever{
		"tactics":             tactics,
		"beginner_principles": principles,
	}); err != nil {
		t.Fatalf("register rag tools: %v", err)
	}

	body, _ := json.Marshal(map[string]interface{}{
		"user_question": "Why is this move a fork?",
		"move":          "h7e7",
	})
	result := reg.ExecuteTool(context.Background(), core.ToolCall{
		ID:   "call-2",
		Name: "explain_tactic",
		Args: body,
	})
	if result.Error != "" {
		t.Fatalf("tool execution failed: %s", result.Error)
	}
	if principles.lastQuery != "Why is this move a fork? h7e7" {
		t.Fatalf("unexpected explain_tactic query: %q", principles.lastQuery)
	}
	if tactics.lastQuery != "" {
		t.Fatalf("explain_tactic should not use tactics retriever, got query %q", tactics.lastQuery)
	}
}

func TestExplainPuzzleObjectiveUsesPuzzleContext(t *testing.T) {
	principles := &mockRetriever{}
	reg := core.NewToolRegistry()
	if err := RegisterRAGTools(reg, map[string]core.Retriever{
		"beginner_principles": principles,
	}); err != nil {
		t.Fatalf("register rag tools: %v", err)
	}

	body, _ := json.Marshal(map[string]interface{}{
		"puzzle_context": "Mate in two with a cannon battery on the open file",
	})
	result := reg.ExecuteTool(context.Background(), core.ToolCall{
		ID:   "call-3",
		Name: "explain_puzzle_objective",
		Args: body,
	})
	if result.Error != "" {
		t.Fatalf("tool execution failed: %s", result.Error)
	}
	if principles.lastQuery != "Mate in two with a cannon battery on the open file" {
		t.Fatalf("unexpected puzzle query: %q", principles.lastQuery)
	}
}
