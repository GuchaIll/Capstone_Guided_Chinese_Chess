package chesstools

import (
	"context"
	"encoding/json"
	"fmt"

	"go_agent_framework/core"
)

// RAGTool is a generic tool backed by a core.Retriever for a specific collection.
type RAGTool struct {
	ToolName    string
	ToolDesc    string
	Retriever   core.Retriever
	TopK        int
}

func (t *RAGTool) Name() string        { return t.ToolName }
func (t *RAGTool) Description() string { return t.ToolDesc }
func (t *RAGTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "query", Type: "string", Description: "Search query for retrieval", Required: true},
		{Name: "top_k", Type: "number", Description: "Number of results to return (default 5)", Required: false},
	}
}

func (t *RAGTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		Query string `json:"query"`
		TopK  int    `json:"top_k"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("%s: %w", t.ToolName, err)
	}
	topK := p.TopK
	if topK <= 0 {
		topK = t.TopK
	}
	if topK <= 0 {
		topK = 5
	}

	chunks, err := t.Retriever.Retrieve(ctx, p.Query, topK)
	if err != nil {
		return "", fmt.Errorf("%s: %w", t.ToolName, err)
	}

	type result struct {
		Content string  `json:"content"`
		Score   float32 `json:"score"`
	}
	results := make([]result, len(chunks))
	for i, c := range chunks {
		results[i] = result{Content: c.Content, Score: c.Score}
	}
	out, _ := json.Marshal(map[string]interface{}{"results": results, "count": len(results)})
	return string(out), nil
}

// ExplainTacticTool retrieves tactical explanations from RAG.
type ExplainTacticTool struct {
	Retriever core.Retriever
}

func (t *ExplainTacticTool) Name() string        { return "explain_tactic" }
func (t *ExplainTacticTool) Description() string { return "Retrieve explanations for a specific tactic using RAG context." }
func (t *ExplainTacticTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "tactic_name", Type: "string", Description: "Name of the tactic to explain (e.g. fork, pin, skewer)", Required: true},
		{Name: "fen", Type: "string", Description: "Optional FEN for positional context", Required: false},
	}
}

func (t *ExplainTacticTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		TacticName string `json:"tactic_name"`
		FEN        string `json:"fen"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("explain_tactic: %w", err)
	}
	query := fmt.Sprintf("explain %s tactic", p.TacticName)
	if p.FEN != "" {
		query += " in position " + p.FEN
	}
	chunks, err := t.Retriever.Retrieve(ctx, query, 3)
	if err != nil {
		return "", fmt.Errorf("explain_tactic: %w", err)
	}
	injector := &core.ContextInjector{}
	out, _ := json.Marshal(map[string]interface{}{
		"tactic":      p.TacticName,
		"explanation": injector.Inject(chunks),
	})
	return string(out), nil
}

// ExplainPuzzleObjectiveTool retrieves puzzle-solving guidance from RAG.
type ExplainPuzzleObjectiveTool struct {
	Retriever core.Retriever
}

func (t *ExplainPuzzleObjectiveTool) Name() string { return "explain_puzzle_objective" }
func (t *ExplainPuzzleObjectiveTool) Description() string {
	return "Explain the objective and strategy needed for a puzzle position."
}
func (t *ExplainPuzzleObjectiveTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "themes", Type: "string", Description: "Comma-separated puzzle themes", Required: true},
	}
}

func (t *ExplainPuzzleObjectiveTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		Themes string `json:"themes"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("explain_puzzle_objective: %w", err)
	}
	query := fmt.Sprintf("how to solve %s puzzle", p.Themes)
	chunks, err := t.Retriever.Retrieve(ctx, query, 3)
	if err != nil {
		return "", fmt.Errorf("explain_puzzle_objective: %w", err)
	}
	injector := &core.ContextInjector{}
	out, _ := json.Marshal(map[string]interface{}{
		"themes":    p.Themes,
		"guidance":  injector.Inject(chunks),
	})
	return string(out), nil
}

// RegisterRAGTools registers all RAG-backed tools.
// retrievers maps collection name → Retriever (e.g. "openings", "tactics", "endgames", "beginner_principles").
func RegisterRAGTools(reg *core.ToolRegistry, retrievers map[string]core.Retriever) error {
	collections := []struct {
		name, desc, collection string
	}{
		{"get_opening_plan", "Retrieve opening plans and theory from the openings database.", "openings"},
		{"get_middlegame_theme", "Retrieve middlegame themes and tactical patterns.", "tactics"},
		{"get_endgame_principle", "Retrieve endgame principles and techniques.", "endgames"},
		{"get_general_advice", "Retrieve general chess advice for beginners.", "beginner_principles"},
	}

	for _, c := range collections {
		ret, ok := retrievers[c.collection]
		if !ok {
			continue
		}
		if err := reg.Register(&RAGTool{
			ToolName:  c.name,
			ToolDesc:  c.desc,
			Retriever: ret,
			TopK:      5,
		}); err != nil {
			return err
		}
	}

	// Tactic and puzzle explanation tools use the tactics retriever.
	if tacticsRet, ok := retrievers["tactics"]; ok {
		if err := reg.Register(&ExplainTacticTool{Retriever: tacticsRet}); err != nil {
			return err
		}
	}
	if principlesRet, ok := retrievers["beginner_principles"]; ok {
		if err := reg.Register(&ExplainPuzzleObjectiveTool{Retriever: principlesRet}); err != nil {
			return err
		}
	}

	return nil
}
