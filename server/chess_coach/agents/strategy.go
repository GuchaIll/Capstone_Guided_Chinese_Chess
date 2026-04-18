package agents

import (
	"fmt"

	"go_agent_framework/contrib/llm"
	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// StrategyAgent asks the LLM for strategic coaching advice based on the position.
type StrategyAgent struct {
	LLM       llm.LLMClient
	Skills    *core.SkillRegistry
	ModelRole string // e.g. "analysis" or "orchestration"
}

func (a *StrategyAgent) Name() string        { return "strategy" }
func (a *StrategyAgent) Description() string { return "Asks the LLM for strategic coaching advice." }
func (a *StrategyAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{Skills: []string{"llm:generate", "beginner_coaching"}, Model: a.ModelRole}
}

func (a *StrategyAgent) Run(ctx *core.Context) error {
	fen, _ := ctx.State["fen"].(string)
	question, _ := ctx.State["question"].(string)

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Building strategic coaching prompt for the LLM.")

	prompt := fmt.Sprintf(
		"You are a chess coach. The current position (FEN): %s\n"+
			"Provide strategic advice for the player to move.",
		fen,
	)
	if question != "" {
		prompt += fmt.Sprintf("\nThe student asks: %s", question)
	}

	// Apply coaching skill formatting if available.
	if a.Skills != nil {
		if skill, ok := a.Skills.Get("beginner_coaching"); ok {
			prompt += fmt.Sprintf("\n\nFormatting instructions: %s", skill.Description)
			observability.PublishSkillUse(ctx.GraphName, a.Name(), ctx.SessionID, skill.Name, skill.Description)
		}
	}

	observability.PublishSkillUse(ctx.GraphName, a.Name(), ctx.SessionID, "llm:generate", "Sending prompt to LLM for strategic advice.")

	advice, err := a.LLM.Generate(ctx.ToContext(), prompt)
	if err != nil {
		return fmt.Errorf("strategy: llm error: %w", err)
	}

	ctx.State["strategy_advice"] = advice
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, fmt.Sprintf("LLM returned advice (%d chars).", len(advice)))
	ctx.Logger.Info("strategy complete", "advice_len", len(advice))
	return nil
}
