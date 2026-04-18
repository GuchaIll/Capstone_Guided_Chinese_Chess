package agents

import (
	"fmt"

	"go_agent_framework/contrib/llm"
	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// CoachAgent synthesizes all analysis results into human-friendly coaching advice
// using an LLM. It combines engine analysis, blunder detection, puzzle information,
// and RAG context to produce a comprehensive coaching response.
type CoachAgent struct {
	LLM    llm.LLMClient
	Skills *core.SkillRegistry
}

func (a *CoachAgent) Name() string { return "coach" }
func (a *CoachAgent) Description() string {
	return "Synthesizes analysis results into coaching advice using LLM."
}
func (a *CoachAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{
		Skills: []string{"beginner_coaching", "explain_tactic", "general_advice"},
		Model:  string(llm.RoleAnalysis),
	}
}

func (a *CoachAgent) Run(ctx *core.Context) error {
	if skip, _ := ctx.State["route_coaching"].(bool); !skip {
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Coaching not requested, skipping.")
		return nil
	}

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Building coaching prompt from analysis results.")

	fen, _ := ctx.State["fen"].(string)
	question, _ := ctx.State["question"].(string)

	// Build a comprehensive prompt from all available state.
	prompt := fmt.Sprintf(
		"You are an expert chess coach. Provide clear, actionable coaching advice.\n\n"+
			"Position (FEN): %s\n", fen)

	if question != "" {
		prompt += fmt.Sprintf("Student's question: %s\n\n", question)
	}

	// Include engine analysis.
	if metrics, ok := ctx.State["engine_metrics"].(map[string]interface{}); ok {
		// Try new structured format first.
		if score, ok := metrics["search_score"]; ok {
			prompt += fmt.Sprintf("Engine score: %v\n", score)
		} else if eval, ok := metrics["eval"]; ok {
			prompt += fmt.Sprintf("Engine evaluation: %v\n", eval)
		}
		if mf, ok := metrics["move_features"].(map[string]interface{}); ok {
			if mm, ok := mf["move_metadata"].(map[string]interface{}); ok {
				prompt += fmt.Sprintf("Best move: %v\n", mm["move_str"])
			}
			if sm, ok := mf["search_metrics"].(map[string]interface{}); ok {
				if pv, ok := sm["principal_variation"]; ok {
					prompt += fmt.Sprintf("Principal variation: %v\n", pv)
				}
			}
		} else {
			if bm, ok := metrics["best_move"]; ok {
				prompt += fmt.Sprintf("Best move: %v\n", bm)
			}
			if pv, ok := metrics["pv"].(string); ok {
				prompt += fmt.Sprintf("Principal variation: %s\n", pv)
			}
		}
		if phase, ok := ctx.State["game_phase"].(string); ok {
			prompt += fmt.Sprintf("Game phase: %s\n", phase)
		}
		if material, ok := ctx.State["material_info"].(map[string]interface{}); ok {
			prompt += fmt.Sprintf("Material balance: %v\n", material)
		}
	}

	// Include blunder analysis.
	if blunderData, ok := ctx.State["blunder_analysis"].(map[string]interface{}); ok {
		if blunders, ok := blunderData["blunders"].([]interface{}); ok && len(blunders) > 0 {
			prompt += fmt.Sprintf("\nBlunders detected: %d\n", len(blunders))
			for _, b := range blunders {
				if bm, ok := b.(map[string]interface{}); ok {
					// Try new structured format (category, centipawn_loss, score_delta).
					if category, ok := bm["category"]; ok {
						prompt += fmt.Sprintf("  - Move %v: %v (category: %v, centipawn loss: %v, score delta: %v)\n",
							bm["move_index"], bm["move"], category, bm["centipawn_loss"], bm["score_delta"])
						if alts, ok := bm["alternatives"].([]interface{}); ok && len(alts) > 0 {
							prompt += fmt.Sprintf("    Better alternatives: %v\n", alts)
						}
					} else {
						// Legacy format fallback.
						prompt += fmt.Sprintf("  - Move %v: %v (eval drop: %v)\n",
							bm["move_index"], bm["move"], bm["eval_drop"])
					}
				}
			}
		}
	}

	// Include puzzle information.
	if puzzle, ok := ctx.State["puzzle"].(map[string]interface{}); ok {
		prompt += fmt.Sprintf("\nPuzzle generated from this position:\n")
		prompt += fmt.Sprintf("  Solution: %v\n", puzzle["solution"])
		if themes, ok := ctx.State["puzzle_themes"].(map[string]interface{}); ok {
			prompt += fmt.Sprintf("  Themes: %v\n", themes["themes"])
		}
		if diff, ok := ctx.State["puzzle_difficulty"].(map[string]interface{}); ok {
			prompt += fmt.Sprintf("  Difficulty: %v (rating: %v)\n", diff["difficulty"], diff["rating"])
		}
	}

	// Apply coaching skill formatting if available.
	if a.Skills != nil {
		if skill, ok := a.Skills.Get("beginner_coaching"); ok {
			prompt += fmt.Sprintf("\n\nFormatting instructions: %s", skill.Description)
			observability.PublishSkillUse(ctx.GraphName, a.Name(), ctx.SessionID, skill.Name, skill.Description)
		}
	}

	prompt += "\n\nProvide comprehensive coaching advice based on the above analysis."

	observability.PublishSkillUse(ctx.GraphName, a.Name(), ctx.SessionID, "llm:generate", "Generating coaching advice.")

	advice, err := a.LLM.Generate(ctx.ToContext(), prompt)
	if err != nil {
		return fmt.Errorf("coach: llm error: %w", err)
	}

	ctx.State["coaching_advice"] = advice
	// Also keep backward compatibility with strategy_advice key.
	ctx.State["strategy_advice"] = advice

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("LLM returned coaching advice (%d chars).", len(advice)))
	ctx.Logger.Info("coach complete", "advice_len", len(advice))
	return nil
}
