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
		Agents: []string{"blunder_detection", "position_analyst", "puzzle_curator", "coach", "guard"},
	}
}

func (a *OrchestratorAgent) Run(ctx *core.Context) error {
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Classifying user intent and evaluating coach trigger conditions.")

	fen, _ := ctx.State["fen"].(string)
	question, _ := ctx.State["question"].(string)
	hasMove, _ := ctx.State["has_move"].(bool)
	moves, _ := ctx.State["moves"].(string)
	questionOnly, _ := ctx.State["question_only"].(bool)

	// Routing flags.
	ctx.State["route_blunder_detection"] = !questionOnly && (hasMove || moves != "")
	ctx.State["route_position_analysis"] = !questionOnly && fen != ""

	wantsPuzzle := containsAny(question, "puzzle", "practice", "exercise", "train", "drill")
	ctx.State["route_puzzle"] = wantsPuzzle

	// Evaluate coach trigger — Coach runs only when one of these conditions is met.
	// Condition 3 (tactical_pattern) is evaluated later by PositionAnalystAgent.
	coachTrigger := evalCoachTrigger(ctx.State)
	ctx.State["coach_trigger"] = coachTrigger

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("Routing: position=%v blunder=%v puzzle=%v coach_trigger=%v",
			ctx.State["route_position_analysis"],
			ctx.State["route_blunder_detection"],
			ctx.State["route_puzzle"],
			coachTrigger,
		))

	// Optional LLM intent classification.
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
		"route_blunder_detection", ctx.State["route_blunder_detection"],
		"route_position_analysis", ctx.State["route_position_analysis"],
		"route_puzzle", ctx.State["route_puzzle"],
		"coach_trigger", coachTrigger,
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

// evalCoachTrigger checks the two pre-analysis trigger conditions.
// Condition 3 (tactical_pattern) is evaluated later by PositionAnalystAgent.
func evalCoachTrigger(state map[string]interface{}) string {
	question, _ := state["question"].(string)
	questionOnly, _ := state["question_only"].(bool)
	hasMove, _ := state["has_move"].(bool)

	if shouldForceCoaching(question, questionOnly, hasMove) {
		return "explicit"
	}
	if movesSince, _ := state["moves_since_last_coach"].(int); movesSince >= 3 {
		return "move_count"
	}
	prevScore, hasPrev := state["prev_score"].(int)
	currScore, hasCurr := state["current_score"].(int)
	if hasPrev && hasCurr {
		delta := currScore - prevScore
		if delta < 0 {
			delta = -delta
		}
		if delta >= 200 {
			return "material_shift"
		}
	}
	return "none"
}

func shouldForceCoaching(question string, questionOnly, hasMove bool) bool {
	if questionOnly && stringsTrimSpace(question) != "" {
		return true
	}
	if !hasMove {
		return false
	}
	lower := toLower(question)
	return containsAny(lower,
		"why",
		"explain",
		"comment",
		"coach",
		"advice",
		"plan",
		"what should",
		"how should",
		"what is the idea",
	)
}

func stringsTrimSpace(s string) string {
	start := 0
	for start < len(s) && (s[start] == ' ' || s[start] == '\n' || s[start] == '\t' || s[start] == '\r') {
		start++
	}
	end := len(s)
	for end > start && (s[end-1] == ' ' || s[end-1] == '\n' || s[end-1] == '\t' || s[end-1] == '\r') {
		end--
	}
	return s[start:end]
}
