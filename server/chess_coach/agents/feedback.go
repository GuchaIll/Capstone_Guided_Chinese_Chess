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
	writeRAGSection(sb, state)
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
	bestMove := ""
	if mf, ok := metrics["move_features"].(map[string]interface{}); ok {
		if mm, ok := mf["move_metadata"].(map[string]interface{}); ok {
			bestMove = fmt.Sprint(mm["move_str"])
		}
	} else if bm, ok := metrics["best_move"]; ok {
		bestMove = fmt.Sprint(bm)
	}
	if bestMove == "<nil>" {
		bestMove = ""
	}
	if bestMove != "" {
		sb.WriteString(fmt.Sprintf("Evaluation: %v  |  Best move: %s\n", eval, bestMove))
	} else {
		sb.WriteString(fmt.Sprintf("Evaluation: %v\n", eval))
	}

	if pv, ok := state["principal_variation"].(map[string]interface{}); ok {
		if bestLine := formatPrincipalVariation(pv["pv"]); bestLine != "" {
			sb.WriteString(fmt.Sprintf("Best line: %s\n", bestLine))
		}
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
	sb.WriteString(fmt.Sprintf("\nCoaching advice:\n%s\n", truncateWords(cleanHumanText(advice), 320)))
}

func writeRAGSection(sb *strings.Builder, state map[string]interface{}) {
	advice, _ := state["coaching_advice"].(string)
	approved, _ := state["coach_advice_approved"].(bool)
	if advice != "" && approved {
		return
	}

	ragContext, ok := state["rag_context"].(map[string]interface{})
	if !ok || len(ragContext) == 0 {
		return
	}

	orderedKeys := []string{"general", "opening", "middlegame", "endgame", "tactic", "puzzle"}
	for _, key := range orderedKeys {
		raw, ok := ragContext[key].(map[string]interface{})
		if !ok {
			continue
		}
		text, _ := raw["text"].(string)
		if strings.TrimSpace(text) == "" {
			continue
		}
		snippet := summarizeRAGText(text)
		if snippet == "" {
			continue
		}
		sb.WriteString(fmt.Sprintf("\nGuidance [%s]: %s\n", key, snippet))
		break
	}
}

func summarizeRAGText(text string) string {
	text = cleanHumanText(text)
	if text == "" {
		return ""
	}
	if idx := strings.IndexAny(text, ".!?"); idx > 0 {
		text = text[:idx+1]
	}
	if len(text) > 180 {
		text = strings.TrimSpace(text[:180]) + "..."
	}
	return truncateWords(text, 28)
}

func truncateWords(text string, maxWords int) string {
	if maxWords <= 0 {
		return ""
	}
	words := strings.Fields(strings.TrimSpace(text))
	if len(words) <= maxWords {
		return strings.Join(words, " ")
	}
	return strings.Join(words[:maxWords], " ") + "..."
}

func cleanHumanText(text string) string {
	text = strings.TrimSpace(text)
	replacements := []string{
		"Context:", "",
		"context:", "",
		"Explicit:", "",
		"explicit:", "",
	}
	for i := 0; i < len(replacements); i += 2 {
		text = strings.ReplaceAll(text, replacements[i], replacements[i+1])
	}
	text = strings.Join(strings.Fields(text), " ")
	return strings.TrimSpace(text)
}

func formatPrincipalVariation(raw interface{}) string {
	switch pv := raw.(type) {
	case []interface{}:
		parts := make([]string, 0, len(pv))
		for _, item := range pv {
			text := strings.TrimSpace(fmt.Sprint(item))
			if text != "" && text != "<nil>" {
				parts = append(parts, text)
			}
		}
		return strings.Join(parts, " -> ")
	case []string:
		parts := make([]string, 0, len(pv))
		for _, item := range pv {
			text := strings.TrimSpace(item)
			if text != "" {
				parts = append(parts, text)
			}
		}
		return strings.Join(parts, " -> ")
	default:
		text := strings.TrimSpace(fmt.Sprint(raw))
		if text == "" || text == "<nil>" {
			return ""
		}
		return text
	}
}
