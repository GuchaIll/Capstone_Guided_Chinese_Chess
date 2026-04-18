package agents

import (
	"fmt"

	"go_agent_framework/contrib/llm"
	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// OrchestratorAgent determines the intent of the user request and sets routing
// flags in the context for downstream agents. It decides which analysis path
// to take: position analysis, blunder detection, puzzle generation, or general coaching.
type OrchestratorAgent struct {
	LLM   llm.LLMClient
	Tools *core.ToolRegistry
}

func (a *OrchestratorAgent) Name() string { return "orchestrator" }
func (a *OrchestratorAgent) Description() string {
	return "Classifies user intent and sets routing flags for downstream agents."
}
func (a *OrchestratorAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{
		Tools:  []string{"get_position_features", "suggest_best_move"},
		Model:  string(llm.RoleOrchestration),
		Agents: []string{"position_analyst", "blunder_detection", "puzzle_curator", "coach", "visualization"},
	}
}

func (a *OrchestratorAgent) Run(ctx *core.Context) error {
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Classifying user intent to determine analysis path.")

	fen, _ := ctx.State["fen"].(string)
	question, _ := ctx.State["question"].(string)
	hasMove, _ := ctx.State["has_move"].(bool)
	moves, _ := ctx.State["moves"].(string)

	// Determine routing flags based on input features.

	// Default: always run position analysis.
	ctx.State["route_position_analysis"] = true

	// Blunder detection: triggered when a move sequence is provided.
	ctx.State["route_blunder_detection"] = hasMove || moves != ""

	// Puzzle generation: triggered when blunders are found (set later by BlunderDetectionAgent)
	// or when the user explicitly asks for a puzzle.
	wantsPuzzle := containsAny(question, "puzzle", "practice", "exercise", "train", "drill")
	ctx.State["route_puzzle"] = wantsPuzzle

	// Coaching: always provide coaching output.
	ctx.State["route_coaching"] = true

	// Visualization: include board rendering.
	ctx.State["route_visualization"] = fen != ""

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("Routing: position=%v blunder=%v puzzle=%v coaching=%v viz=%v",
			ctx.State["route_position_analysis"],
			ctx.State["route_blunder_detection"],
			ctx.State["route_puzzle"],
			ctx.State["route_coaching"],
			ctx.State["route_visualization"],
		))

	// If LLM is available, refine intent classification.
	if a.LLM != nil {
		prompt := fmt.Sprintf(
			"Classify this chess coaching request. Position (FEN): %s\nUser message: %s\nMove provided: %v\n\n"+
				"Respond with one primary intent: ANALYZE, BLUNDER_CHECK, PUZZLE, EXPLAIN, GENERAL_ADVICE",
			fen, question, hasMove,
		)

		intent, err := a.LLM.Generate(ctx.ToContext(), prompt)
		if err == nil {
			ctx.State["classified_intent"] = intent
			observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
				fmt.Sprintf("LLM classified intent: %s", intent))
		}
	}

	ctx.Logger.Info("orchestrator complete",
		"route_position_analysis", ctx.State["route_position_analysis"],
		"route_blunder_detection", ctx.State["route_blunder_detection"],
		"route_puzzle", ctx.State["route_puzzle"],
	)
	return nil
}

// containsAny checks if s contains any of the given substrings (case-insensitive).
func containsAny(s string, subs ...string) bool {
	lower := toLower(s)
	for _, sub := range subs {
		if contains(lower, toLower(sub)) {
			return true
		}
	}
	return false
}

func toLower(s string) string {
	b := make([]byte, len(s))
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 'A' && c <= 'Z' {
			c += 'a' - 'A'
		}
		b[i] = c
	}
	return string(b)
}

func contains(s, sub string) bool {
	return len(sub) <= len(s) && (s == sub || len(sub) == 0 || indexString(s, sub) >= 0)
}

func indexString(s, sub string) int {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
