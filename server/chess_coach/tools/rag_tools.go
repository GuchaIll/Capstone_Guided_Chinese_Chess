package chesstools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"go_agent_framework/core"
)

type ragToolSpec struct {
	toolName    string
	description string
	collection  string
	queryParam  core.ToolParameter
	buildQuery  func(fields map[string]string) string
}

func ragToolSpecs() []ragToolSpec {
	return []ragToolSpec{
		{
			toolName:    "get_opening_plan",
			description: "Retrieve opening plans and theory from the openings database.",
			collection:  "openings",
			queryParam: core.ToolParameter{
				Name:        "position_description",
				Type:        "string",
				Description: "Opening position description to retrieve plans for.",
				Required:    true,
			},
			buildQuery: func(fields map[string]string) string {
				return firstNonEmpty(fields, "position_description", "query")
			},
		},
		{
			toolName:    "get_middlegame_theme",
			description: "Retrieve middlegame themes and tactical patterns.",
			collection:  "tactics",
			queryParam: core.ToolParameter{
				Name:        "position_features",
				Type:        "string",
				Description: "Middlegame position features or motifs to retrieve themes for.",
				Required:    true,
			},
			buildQuery: func(fields map[string]string) string {
				return firstNonEmpty(fields, "position_features", "query")
			},
		},
		{
			toolName:    "get_endgame_principle",
			description: "Retrieve endgame principles and techniques.",
			collection:  "endgames",
			queryParam: core.ToolParameter{
				Name:        "position_features",
				Type:        "string",
				Description: "Endgame position features to retrieve principles for.",
				Required:    true,
			},
			buildQuery: func(fields map[string]string) string {
				return firstNonEmpty(fields, "position_features", "query")
			},
		},
		{
			toolName:    "get_general_advice",
			description: "Retrieve general chess advice for beginners.",
			collection:  "beginner_principles",
			queryParam: core.ToolParameter{
				Name:        "user_question",
				Type:        "string",
				Description: "User question to answer with beginner-friendly advice.",
				Required:    true,
			},
			buildQuery: func(fields map[string]string) string {
				return firstNonEmpty(fields, "user_question", "query")
			},
		},
	}
}

// RAGTool is a collection-specific retriever with a query field tailored to the use case.
type RAGTool struct {
	ToolName   string
	ToolDesc   string
	Retriever  core.Retriever
	TopK       int
	QueryParam core.ToolParameter
	BuildQuery func(fields map[string]string) string
}

func (t *RAGTool) Name() string        { return t.ToolName }
func (t *RAGTool) Description() string { return t.ToolDesc }
func (t *RAGTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		t.QueryParam,
		{Name: "top_k", Type: "number", Description: "Number of results to return (default 5)", Required: false},
	}
}

func (t *RAGTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	fields, topK, err := decodeStringArgs(args)
	if err != nil {
		return "", fmt.Errorf("%s: %w", t.ToolName, err)
	}
	query := ""
	if t.BuildQuery != nil {
		query = strings.TrimSpace(t.BuildQuery(fields))
	}
	if query == "" {
		query = strings.TrimSpace(firstNonEmpty(fields, t.QueryParam.Name, "query"))
	}
	if query == "" {
		return "", fmt.Errorf("%s: missing %s", t.ToolName, t.QueryParam.Name)
	}
	topK = normalizedTopK(topK, t.TopK)

	chunks, err := t.Retriever.Retrieve(ctx, query, topK)
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
	out, _ := json.Marshal(map[string]interface{}{
		"results": results,
		"count":   len(results),
		"query":   query,
	})
	return string(out), nil
}

// ExplainTacticTool retrieves tactical explanations from RAG.
type ExplainTacticTool struct {
	Retriever core.Retriever
}

func (t *ExplainTacticTool) Name() string { return "explain_tactic" }
func (t *ExplainTacticTool) Description() string {
	return "Retrieve a beginner-friendly explanation for a tactic using the user's question and move."
}
func (t *ExplainTacticTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "user_question", Type: "string", Description: "User question about the tactic.", Required: true},
		{Name: "move", Type: "string", Description: "Move being explained (e.g. h7e7).", Required: false},
		{Name: "top_k", Type: "number", Description: "Number of results to return (default 3)", Required: false},
	}
}

func (t *ExplainTacticTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	fields, topK, err := decodeStringArgs(args)
	if err != nil {
		return "", fmt.Errorf("explain_tactic: %w", err)
	}
	query := strings.TrimSpace(strings.Join(nonEmptyStrings(
		firstNonEmpty(fields, "user_question", "tactic_name"),
		firstNonEmpty(fields, "move"),
	), " "))
	if query == "" {
		return "", fmt.Errorf("explain_tactic: missing user_question")
	}
	chunks, err := t.Retriever.Retrieve(ctx, query, normalizedTopK(topK, 3))
	if err != nil {
		return "", fmt.Errorf("explain_tactic: %w", err)
	}
	injector := &core.ContextInjector{}
	out, _ := json.Marshal(map[string]interface{}{
		"question":    firstNonEmpty(fields, "user_question", "tactic_name"),
		"move":        firstNonEmpty(fields, "move"),
		"query":       query,
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
		{Name: "puzzle_context", Type: "string", Description: "Puzzle context or objective to explain.", Required: true},
		{Name: "top_k", Type: "number", Description: "Number of results to return (default 3)", Required: false},
	}
}

func (t *ExplainPuzzleObjectiveTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	fields, topK, err := decodeStringArgs(args)
	if err != nil {
		return "", fmt.Errorf("explain_puzzle_objective: %w", err)
	}
	contextText := firstNonEmpty(fields, "puzzle_context", "themes")
	if contextText == "" {
		return "", fmt.Errorf("explain_puzzle_objective: missing puzzle_context")
	}
	query := contextText
	chunks, err := t.Retriever.Retrieve(ctx, query, normalizedTopK(topK, 3))
	if err != nil {
		return "", fmt.Errorf("explain_puzzle_objective: %w", err)
	}
	injector := &core.ContextInjector{}
	out, _ := json.Marshal(map[string]interface{}{
		"puzzle_context": contextText,
		"query":          query,
		"guidance":       injector.Inject(chunks),
	})
	return string(out), nil
}

// RegisterRAGTools registers all RAG-backed tools.
// retrievers maps collection name → Retriever (e.g. "openings", "tactics", "endgames", "beginner_principles").
func RegisterRAGTools(reg *core.ToolRegistry, retrievers map[string]core.Retriever) error {
	for _, spec := range ragToolSpecs() {
		ret, ok := retrievers[spec.collection]
		if !ok {
			continue
		}
		if err := reg.Register(&RAGTool{
			ToolName:   spec.toolName,
			ToolDesc:   spec.description,
			Retriever:  ret,
			TopK:       5,
			QueryParam: spec.queryParam,
			BuildQuery: spec.buildQuery,
		}); err != nil {
			return err
		}
	}

	if principlesRet, ok := retrievers["beginner_principles"]; ok {
		if err := reg.Register(&ExplainTacticTool{Retriever: principlesRet}); err != nil {
			return err
		}
		if err := reg.Register(&ExplainPuzzleObjectiveTool{Retriever: principlesRet}); err != nil {
			return err
		}
	}

	return nil
}

func decodeStringArgs(args json.RawMessage) (map[string]string, int, error) {
	var raw map[string]interface{}
	if err := json.Unmarshal(args, &raw); err != nil {
		return nil, 0, err
	}
	fields := make(map[string]string, len(raw))
	topK := 0
	for key, value := range raw {
		switch typed := value.(type) {
		case string:
			fields[key] = strings.TrimSpace(typed)
		case float64:
			if key == "top_k" {
				topK = int(typed)
			}
		}
	}
	return fields, topK, nil
}

func normalizedTopK(topK, fallback int) int {
	if topK > 0 {
		return topK
	}
	if fallback > 0 {
		return fallback
	}
	return 5
}

func firstNonEmpty(fields map[string]string, keys ...string) string {
	for _, key := range keys {
		if value := strings.TrimSpace(fields[key]); value != "" {
			return value
		}
	}
	return ""
}

func nonEmptyStrings(values ...string) []string {
	result := make([]string, 0, len(values))
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			result = append(result, trimmed)
		}
	}
	return result
}
