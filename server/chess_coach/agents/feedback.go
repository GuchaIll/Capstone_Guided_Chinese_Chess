package agents

import (
	"fmt"
	"go_agent_framework/core"
	"go_agent_framework/observability"
	"strings"
)

// FeedbackAgent composes the final coaching response from pipeline outputs.
// It handles three distinct paths:
//   - Blunder abort: emits blunder summary only, all other sections suppressed.
//   - Fast path:     emits engine metrics + puzzle (no coaching advice).
//   - Slow path:     emits engine metrics + puzzle + coaching advice (if approved by Guard).
type FeedbackAgent struct{}

func (a *FeedbackAgent) Name() string { return "feedback" }
func (a *FeedbackAgent) Description() string {
	return "Composes the final coaching response based on the active pipeline path."
}
func (a *FeedbackAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{Agents: []string{"blunder_detection", "position_analyst", "puzzle_curator", "coach", "guard"}}
}

func (a *FeedbackAgent) Run(ctx *core.Context) error {
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Composing final response.")

	var sb strings.Builder

	if abort, _ := ctx.State["blunder_abort"].(bool); abort {
		writeBlunderPath(&sb, ctx.State)
	} else {
		writeAnalysisPath(&sb, ctx.State)
	}

	ctx.State["feedback"] = sb.String()
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("Response composed (%d chars).", sb.Len()))
	ctx.Logger.Info("feedback composed", "length", sb.Len())
	return nil
}

// writeBlunderPath emits the blunder-abort output: blunder summary only.
func writeBlunderPath(sb *strings.Builder, state map[string]interface{}) {
	sb.WriteString("⚠ BLUNDER DETECTED\n")
	blunderData, ok := state["blunder_analysis"].(map[string]interface{})
	if !ok {
		return
	}
	blunders, ok := blunderData["blunders"].([]interface{})
	if !ok {
		return
	}
	for _, b := range blunders {
		bm, ok := b.(map[string]interface{})
		if !ok {
			continue
		}
		sb.WriteString(fmt.Sprintf("Move: %v | Centipawn loss: %v | Category: %v\n",
			bm["move"], bm["centipawn_loss"], bm["category"]))
		if alts, ok := bm["alternatives"].([]interface{}); ok && len(alts) > 0 {
			sb.WriteString(fmt.Sprintf("Better move: %v\n", alts[0]))
		}
	}
	sb.WriteString("A puzzle has been queued for your next turn.\n")
}

// writeAnalysisPath emits the fast or slow path output.
func writeAnalysisPath(sb *strings.Builder, state map[string]interface{}) {
	writeEngineSection(sb, state)
	writePuzzleSection(sb, state)
	writeCoachSection(sb, state)
}

func writeEngineSection(sb *strings.Builder, state map[string]interface{}) {
	metrics, ok := state["engine_metrics"].(map[string]interface{})
	if !ok {
		return
	}
	eval := metrics["eval"]
	if score, ok := metrics["search_score"]; ok {
		eval = score
	}
	bestMove := metrics["best_move"]
	if mf, ok := metrics["move_features"].(map[string]interface{}); ok {
		if mm, ok := mf["move_metadata"].(map[string]interface{}); ok {
			bestMove = mm["move_str"]
		}
	}
	sb.WriteString(fmt.Sprintf("Evaluation: %v  |  Best move: %v\n", eval, bestMove))

	if pv, ok := state["principal_variation"].(map[string]interface{}); ok {
		sb.WriteString(fmt.Sprintf("Best line: %v\n", pv["pv"]))
	}
}

func writePuzzleSection(sb *strings.Builder, state map[string]interface{}) {
	puzzle, ok := state["puzzle"].(map[string]interface{})
	if !ok {
		return
	}
	sb.WriteString("\nPuzzle:\n")
	sb.WriteString(fmt.Sprintf("  Starting position: %v\n", puzzle["starting_fen"]))
	sb.WriteString(fmt.Sprintf("  Solution: %v\n", puzzle["solution"]))
	if themes, ok := state["puzzle_themes"].(map[string]interface{}); ok {
		sb.WriteString(fmt.Sprintf("  Themes: %v\n", themes["themes"]))
	}
	if diff, ok := state["puzzle_difficulty"].(map[string]interface{}); ok {
		sb.WriteString(fmt.Sprintf("  Difficulty: %v (rating %v)\n", diff["difficulty"], diff["rating"]))
	}
}

func writeCoachSection(sb *strings.Builder, state map[string]interface{}) {
	advice, _ := state["coaching_advice"].(string)
	if advice == "" {
		return
	}
	approved, _ := state["coach_advice_approved"].(bool)
	if !approved {
		return
	}
	trigger, _ := state["coach_trigger"].(string)
	sb.WriteString(fmt.Sprintf("\nCoaching advice [%s]:\n%s\n", trigger, advice))
}
