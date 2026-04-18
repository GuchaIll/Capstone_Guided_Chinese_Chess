package agents

import (
	"fmt"
	"go_agent_framework/core"
	"go_agent_framework/observability"
	"strings"
)

// FeedbackAgent composes the final coaching response from outputs of all
// pipeline agents (position analyst, blunder detection, puzzle curator, coach, visualization).
type FeedbackAgent struct{}

func (a *FeedbackAgent) Name() string { return "feedback" }
func (a *FeedbackAgent) Description() string {
	return "Composes final coaching response from all pipeline agent outputs."
}
func (a *FeedbackAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{Agents: []string{"position_analyst", "blunder_detection", "puzzle_curator", "coach", "visualization"}}
}

func (a *FeedbackAgent) Run(ctx *core.Context) error {
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Aggregating results from all pipeline agents.")
	observability.PublishDelegation(ctx.GraphName, a.Name(), ctx.SessionID, "all_agents", "Composing final response from pipeline agent outputs.")

	var sb strings.Builder

	// Board visualization.
	if board, ok := ctx.State["board_visualization"].(string); ok {
		sb.WriteString(board)
		sb.WriteString("\n")
	}

	// Engine analysis summary.
	if metrics, ok := ctx.State["engine_metrics"].(map[string]interface{}); ok {
		sb.WriteString(fmt.Sprintf("Engine evaluation: %v  |  Best move: %v\n",
			metrics["eval"], metrics["best_move"]))
		if pv, ok := ctx.State["principal_variation"].(map[string]interface{}); ok {
			sb.WriteString(fmt.Sprintf("Principal variation: %v\n", pv["pv"]))
		}
	}

	// Blunder analysis.
	if blunderData, ok := ctx.State["blunder_analysis"].(map[string]interface{}); ok {
		if blunders, ok := blunderData["blunders"].([]interface{}); ok && len(blunders) > 0 {
			sb.WriteString(fmt.Sprintf("\nBlunders detected: %d\n", len(blunders)))
			for _, b := range blunders {
				if bm, ok := b.(map[string]interface{}); ok {
					sb.WriteString(fmt.Sprintf("  Move %v: %v (eval drop: %v cp)\n",
						bm["move_index"], bm["move"], bm["eval_drop"]))
				}
			}
		}
	}

	// Puzzle.
	if puzzle, ok := ctx.State["puzzle"].(map[string]interface{}); ok {
		sb.WriteString("\nPuzzle:\n")
		sb.WriteString(fmt.Sprintf("  Starting position: %v\n", puzzle["starting_fen"]))
		sb.WriteString(fmt.Sprintf("  Solution: %v\n", puzzle["solution"]))
		if themes, ok := ctx.State["puzzle_themes"].(map[string]interface{}); ok {
			sb.WriteString(fmt.Sprintf("  Themes: %v\n", themes["themes"]))
		}
		if diff, ok := ctx.State["puzzle_difficulty"].(map[string]interface{}); ok {
			sb.WriteString(fmt.Sprintf("  Difficulty: %v (rating %v)\n", diff["difficulty"], diff["rating"]))
		}
	}

	// Coaching advice (from CoachAgent or legacy StrategyAgent).
	if advice, ok := ctx.State["coaching_advice"].(string); ok {
		sb.WriteString(fmt.Sprintf("\nCoaching advice:\n%s\n", advice))
	} else if advice, ok := ctx.State["strategy_advice"].(string); ok {
		sb.WriteString(fmt.Sprintf("\nCoaching advice:\n%s\n", advice))
	}

	// Move legality feedback.
	if legal, ok := ctx.State["move_legal"].(bool); ok {
		move, _ := ctx.State["move"].(string)
		if legal {
			sb.WriteString(fmt.Sprintf("\nYour move %s is legal.", move))
		} else {
			sb.WriteString(fmt.Sprintf("\nYour move %s is NOT legal in this position.", move))
		}
	}

	ctx.State["feedback"] = sb.String()
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, fmt.Sprintf("Final coaching response composed (%d chars).", sb.Len()))
	ctx.Logger.Info("feedback composed", "length", sb.Len())
	return nil
}
