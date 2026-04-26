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
	Tools  *core.ToolRegistry
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

	ctx.AgentName = a.Name()
	question, _ := ctx.State["question"].(string)
	move, _ := ctx.State["move"].(string)
	questionOnly, _ := ctx.State["question_only"].(bool)

	if questionOnly || question != "" {
		retrieveRAGSection(ctx, a.Tools, "general", "get_general_advice", map[string]interface{}{
			"user_question": question,
			"top_k":         3,
		})
	}
	if move != "" {
		retrieveRAGSection(ctx, a.Tools, "tactic", "explain_tactic", map[string]interface{}{
			"user_question": firstNonEmptyString(question, "Explain this move."),
			"move":          move,
			"top_k":         3,
		})
	}

	prompt := buildCoachPrompt(ctx.State, coachTrigger)
	prompt += a.skillInstructions(ctx)
	prompt += "\n\nProvide clear, concise coaching advice based on the above analysis."
	prompt += " Keep the response under 320 words. Do not quote large knowledge blocks."

	var advice string
	if isMockLLM(a.LLM) {
		observability.PublishSkillUse(ctx.GraphName, a.Name(), ctx.SessionID, "mock:coach_fallback", "Using deterministic coaching fallback because the mock LLM is active.")
		advice = buildFallbackCoachAdvice(ctx.State, coachTrigger)
	} else {
		observability.PublishSkillUse(ctx.GraphName, a.Name(), ctx.SessionID, "llm:generate", "Generating coaching advice.")

		var err error
		advice, err = a.LLM.Generate(ctx.ToContext(), prompt)
		if err != nil {
			return fmt.Errorf("coach: llm error: %w", err)
		}
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
	appendRAGPromptSection(&sb, state)
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

func appendRAGPromptSection(sb *strings.Builder, state map[string]interface{}) {
	ragContext, ok := state["rag_context"].(map[string]interface{})
	if !ok || len(ragContext) == 0 {
		return
	}

	orderedKeys := []string{"general", "opening", "middlegame", "endgame", "tactic", "puzzle"}
	var added bool
	for _, key := range orderedKeys {
		raw, ok := ragContext[key].(map[string]interface{})
		if !ok {
			continue
		}
		text, _ := raw["text"].(string)
		if strings.TrimSpace(text) == "" {
			continue
		}
		if !added {
			sb.WriteString("\nRelevant knowledge from the library:\n")
			added = true
		}
		sb.WriteString(fmt.Sprintf("## %s guidance:\n%s\n", key, text))
	}
}

func firstNonEmptyString(values ...string) string {
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			return trimmed
		}
	}
	return ""
}

func isMockLLM(client llm.LLMClient) bool {
	describer, ok := client.(llm.Describer)
	if !ok {
		return false
	}
	return describer.Provider() == "mock"
}

func buildFallbackCoachAdvice(state map[string]interface{}, trigger string) string {
	var parts []string
	if score := coachScoreText(state); score != "" {
		parts = append(parts, score)
	}
	if bestMove := coachBestMoveText(state); bestMove != "" {
		parts = append(parts, bestMove)
	}
	if tactical := coachTacticalText(state); tactical != "" {
		parts = append(parts, tactical)
	}
	if knowledge := coachKnowledgeText(state); knowledge != "" {
		parts = append(parts, knowledge)
	}
	if trigger != "" && trigger != "none" {
		parts = append(parts, fmt.Sprintf("This longer explanation was triggered by %s.", trigger))
	}
	return strings.Join(parts, " ")
}

func coachScoreText(state map[string]interface{}) string {
	metrics, ok := state["engine_metrics"].(map[string]interface{})
	if !ok {
		return ""
	}
	if score, ok := metrics["search_score"]; ok {
		return fmt.Sprintf("Engine evaluation is %v centipawns, so this position still has concrete tactical consequences.", score)
	}
	if eval, ok := metrics["eval"]; ok {
		return fmt.Sprintf("Engine evaluation is %v.", eval)
	}
	return ""
}

func coachBestMoveText(state map[string]interface{}) string {
	metrics, ok := state["engine_metrics"].(map[string]interface{})
	if !ok {
		return ""
	}
	bestMove := ""
	if mf, ok := metrics["move_features"].(map[string]interface{}); ok {
		if mm, ok := mf["move_metadata"].(map[string]interface{}); ok {
			bestMove = fmt.Sprint(mm["move_str"])
		}
	} else if bm, ok := metrics["best_move"]; ok {
		bestMove = fmt.Sprint(bm)
	}
	bestMove = strings.TrimSpace(bestMove)
	if bestMove == "" || bestMove == "<nil>" {
		return ""
	}
	return fmt.Sprintf("The engine prefers %s as the cleanest move.", bestMove)
}

func coachTacticalText(state map[string]interface{}) string {
	if hp, ok := state["hanging_pieces"].([]interface{}); ok && len(hp) > 0 {
		return fmt.Sprintf("There are %d hanging piece threats in the position, so piece safety should come before general opening goals.", len(hp))
	}
	if forks, ok := state["forks"].([]interface{}); ok && len(forks) > 0 {
		return "A fork is available or must be prevented, so calculate forcing moves before making a quiet improving move."
	}
	if pins, ok := state["pins"].([]interface{}); ok && len(pins) > 0 {
		return "A pin is shaping the position, so be careful not to rely on a piece that cannot safely move."
	}
	return ""
}

func coachKnowledgeText(state map[string]interface{}) string {
	ragContext, ok := state["rag_context"].(map[string]interface{})
	if !ok {
		return ""
	}
	for _, key := range []string{"tactic", "opening", "middlegame", "endgame", "general", "puzzle"} {
		raw, ok := ragContext[key].(map[string]interface{})
		if !ok {
			continue
		}
		text, _ := raw["text"].(string)
		summary := summarizeRAGText(text)
		if summary == "" {
			continue
		}
		return fmt.Sprintf("%s guidance: %s", key, summary)
	}
	return ""
}
