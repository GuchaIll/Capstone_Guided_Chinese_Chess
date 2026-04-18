package agents

import (
	"encoding/json"
	"fmt"
	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// InspectionAgent validates the FEN via the chess engine tool.
type InspectionAgent struct {
	Tools *core.ToolRegistry
}

func (a *InspectionAgent) Name() string        { return "inspection" }
func (a *InspectionAgent) Description() string { return "Validates the FEN position via the chess engine." }
func (a *InspectionAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{Tools: []string{"validate_fen"}}
}

func (a *InspectionAgent) Run(ctx *core.Context) error {
	fen, _ := ctx.State["fen"].(string)

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Validating FEN string with chess engine.")

	args, _ := json.Marshal(map[string]string{"fen": fen})
	call := core.ToolCall{ID: "validate_fen_1", Name: "validate_fen", Args: args}

	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, map[string]string{"fen": fen})

	result := a.Tools.ExecuteTool(ctx.StdContext, call)
	if result.Error != "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, "", result.Error)
		return fmt.Errorf("inspection: tool error: %s", result.Error)
	}

	observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, result.Output, "")

	var out struct {
		Valid bool `json:"valid"`
	}
	if err := json.Unmarshal([]byte(result.Output), &out); err != nil {
		return fmt.Errorf("inspection: parse result: %w", err)
	}

	if !out.Valid {
		return fmt.Errorf("inspection: invalid FEN %q", fen)
	}

	ctx.State["fen_valid"] = true
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "FEN is valid. Proceeding to analysis.")
	ctx.Logger.Info("inspection passed", "fen", fen)
	return nil
}
