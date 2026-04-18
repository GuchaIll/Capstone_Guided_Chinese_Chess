package agents

import (
	"encoding/json"
	"fmt"
	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// GuardAgent validates whether the user's proposed move is legal and safe.
// If no move was supplied it is a no-op.
type GuardAgent struct {
	Tools *core.ToolRegistry
}

func (a *GuardAgent) Name() string        { return "guard" }
func (a *GuardAgent) Description() string { return "Checks whether the proposed move is legal." }
func (a *GuardAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{Tools: []string{"is_move_legal"}}
}

func (a *GuardAgent) Run(ctx *core.Context) error {
	move, _ := ctx.State["move"].(string)
	if move == "" {
		ctx.State["move_legal"] = nil // no move to check
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "No move supplied, skipping legality check.")
		ctx.Logger.Info("guard: no move supplied, skipping")
		return nil
	}

	fen, _ := ctx.State["fen"].(string)

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, fmt.Sprintf("Checking legality of move %q.", move))

	args, _ := json.Marshal(map[string]string{"fen": fen, "move": move})
	call := core.ToolCall{ID: "check_move_1", Name: "is_move_legal", Args: args}

	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, map[string]string{"fen": fen, "move": move})

	result := a.Tools.ExecuteTool(ctx.StdContext, call)
	if result.Error != "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, "", result.Error)
		return fmt.Errorf("guard: tool error: %s", result.Error)
	}

	observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, result.Output, "")

	var out struct {
		Legal bool `json:"legal"`
	}
	if err := json.Unmarshal([]byte(result.Output), &out); err != nil {
		return fmt.Errorf("guard: parse result: %w", err)
	}

	ctx.State["move_legal"] = out.Legal
	ctx.Logger.Info("guard complete", "move", move, "legal", out.Legal)
	return nil
}
