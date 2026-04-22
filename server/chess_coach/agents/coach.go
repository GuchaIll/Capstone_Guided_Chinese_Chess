package agents

import (
	"fmt"
	"strings"

	"go_agent_framework/contrib/llm"
	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// CoachAgent synthesizes all analysis results into human-friendly coaching advice
// using an LLM. It only runs when a coach trigger condition is satisfied (move_count,
// material_shift, or tactical_pattern). On the fast path it is a no-op.
type CoachAgent struct {
	LLM    llm.LLMClient
	Skills *core.SkillRegistry
}

func (a *CoachAgent) Name() string { return "coach" }
func (a *CoachAgent) Description() string {
	return "Synthesizes analysis results into coaching advice using LLM (slow path only)."
}
func (a *CoachAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{
		Skills: []string{"beginner_coaching", "explain_tactic", "general_advice"},
		Model:  string(llm.RoleAnalysis),
	}
}

func (a *CoachAgent) Run(ctx *core.Context) error {
	if abort, _ := ctx.State["blunder_abort"].(bool); abort {
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Blunder abort active, skipping coach.")
		return nil
	}
	coachTrigger, _ := ctx.State["coach_trigger"].(string)
	if coachTrigger == "" || coachTrigger == "none" {
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "No coach trigger — fast path, skipping LLM call.")
		return nil
	}

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("Coach triggered by: %s — building prompt.", coachTrigger))

	prompt := buildCoachPrompt(ctx.State, coachTrigger)
	prompt += a.skillInstructions(ctx)
	prompt += "\n\nProvide clear, concise coaching advice based on the above analysis."

	observability.PublishSkillUse(ctx.GraphName, a.Name(), ctx.SessionID, "llm:generate", "Generating coaching advice.")

	advice, err := a.LLM.Generate(ctx.ToContext(), prompt)
	if err != nil {
		return fmt.Errorf("coach: llm error: %w", err)
	}

	ctx.State["coaching_advice"] = advice
	ctx.State["strategy_advice"] = advice

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("LLM returned coaching advice (%d chars).", len(advice)))
	ctx.Logger.Info("coach complete", "advice_len", len(advice), "trigger", coachTrigger)
	return nil
}

func (a *CoachAgent) skillInstructions(ctx *core.Context) string {
	if a.Skills == nil {
		return ""
	}
	skill, ok := a.Skills.Get("beginner_coaching")
	if !ok {
		return ""
	}
	observability.PublishSkillUse(ctx.GraphName, a.Name(), ctx.SessionID, skill.Name, skill.Description)
	return fmt.Sprintf("\n\nFormatting instructions: %s", skill.Description)
}

// buildCoachPrompt assembles the LLM prompt from available state without deep nesting.
func buildCoachPrompt(state map[string]interface{}, trigger string) string {
	var sb strings.Builder
	fen, _ := state["fen"].(string)
	sb.WriteString("You are an expert xiangqi coach. Provide clear, actionable coaching advice.\n\n")
	sb.WriteString(fmt.Sprintf("Position (FEN): %s\n", fen))
	sb.WriteString(fmt.Sprintf("Coach trigger: %s\n", trigger))

	if q, _ := state["question"].(string); q != "" {
		sb.WriteString(fmt.Sprintf("Student question: %s\n\n", q))
	}

	appendEngineSection(&sb, state)
	appendBlunderSection(&sb, state)
	appendPuzzleSection(&sb, state)
	return sb.String()
}

func appendEngineSection(sb *strings.Builder, state map[string]interface{}) {
	metrics, ok := state["engine_metrics"].(map[string]interface{})
	if !ok {
		return
	}
	if score, ok := metrics["search_score"]; ok {
		sb.WriteString(fmt.Sprintf("Engine score: %v\n", score))
	} else if eval, ok := metrics["eval"]; ok {
		sb.WriteString(fmt.Sprintf("Engine evaluation: %v\n", eval))
	}
	appendBestMove(sb, metrics)
	if phase, _ := state["game_phase"].(string); phase != "" {
		sb.WriteString(fmt.Sprintf("Game phase: %s\n", phase))
	}
	if material, ok := state["material_info"].(map[string]interface{}); ok {
		sb.WriteString(fmt.Sprintf("Material balance: %v\n", material))
	}
}

func appendBestMove(sb *strings.Builder, metrics map[string]interface{}) {
	if mf, ok := metrics["move_features"].(map[string]interface{}); ok {
		if mm, ok := mf["move_metadata"].(map[string]interface{}); ok {
			sb.WriteString(fmt.Sprintf("Best move: %v\n", mm["move_str"]))
		}
		if sm, ok := mf["search_metrics"].(map[string]interface{}); ok {
			if pv, ok := sm["principal_variation"]; ok {
				sb.WriteString(fmt.Sprintf("Principal variation: %v\n", pv))
			}
		}
		return
	}
	if bm, ok := metrics["best_move"]; ok {
		sb.WriteString(fmt.Sprintf("Best move: %v\n", bm))
	}
	if pv, _ := metrics["pv"].(string); pv != "" {
		sb.WriteString(fmt.Sprintf("Principal variation: %s\n", pv))
	}
}

func appendBlunderSection(sb *strings.Builder, state map[string]interface{}) {
	blunderData, ok := state["blunder_analysis"].(map[string]interface{})
	if !ok {
		return
	}
	blunders, ok := blunderData["blunders"].([]interface{})
	if !ok || len(blunders) == 0 {
		return
	}
	sb.WriteString(fmt.Sprintf("\nBlunders detected: %d\n", len(blunders)))
	for _, b := range blunders {
		bm, ok := b.(map[string]interface{})
		if !ok {
			continue
		}
		if category, ok := bm["category"]; ok {
			sb.WriteString(fmt.Sprintf("  - Move %v: %v (category: %v, cp loss: %v)\n",
				bm["move_index"], bm["move"], category, bm["centipawn_loss"]))
			if alts, ok := bm["alternatives"].([]interface{}); ok && len(alts) > 0 {
				sb.WriteString(fmt.Sprintf("    Better alternatives: %v\n", alts))
			}
		} else {
			sb.WriteString(fmt.Sprintf("  - Move %v: %v (eval drop: %v)\n",
				bm["move_index"], bm["move"], bm["eval_drop"]))
		}
	}
}

func appendPuzzleSection(sb *strings.Builder, state map[string]interface{}) {
	puzzle, ok := state["puzzle"].(map[string]interface{})
	if !ok {
		return
	}
	sb.WriteString("\nPuzzle generated from this position:\n")
	sb.WriteString(fmt.Sprintf("  Solution: %v\n", puzzle["solution"]))
	if themes, ok := state["puzzle_themes"].(map[string]interface{}); ok {
		sb.WriteString(fmt.Sprintf("  Themes: %v\n", themes["themes"]))
	}
	if diff, ok := state["puzzle_difficulty"].(map[string]interface{}); ok {
		sb.WriteString(fmt.Sprintf("  Difficulty: %v (rating: %v)\n", diff["difficulty"], diff["rating"]))
	}
}
