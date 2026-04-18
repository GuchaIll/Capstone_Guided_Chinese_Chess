package agents

import (
	"encoding/json"

	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// VisualizationAgent renders the board position and annotates it with
// analysis results (best move arrows, blunder highlights, etc.).
type VisualizationAgent struct {
	Tools *core.ToolRegistry
}

func (a *VisualizationAgent) Name() string { return "visualization" }
func (a *VisualizationAgent) Description() string {
	return "Renders the board position as ASCII art and annotates with analysis results."
}
func (a *VisualizationAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{
		Tools: []string{"visualize_board"},
	}
}

func (a *VisualizationAgent) Run(ctx *core.Context) error {
	if skip, _ := ctx.State["route_visualization"].(bool); !skip {
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Visualization not requested, skipping.")
		return nil
	}

	fen, _ := ctx.State["fen"].(string)
	if fen == "" {
		return nil
	}

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Rendering board visualization.")

	args, _ := json.Marshal(map[string]interface{}{"fen": fen})
	call := core.ToolCall{ID: "viz_board_1", Name: "visualize_board", Args: args}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, map[string]interface{}{"fen": fen})

	result := a.Tools.ExecuteTool(ctx.StdContext, call)
	if result.Error != "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, "", result.Error)
		// Non-fatal: visualization failure should not block the coaching response.
		ctx.Logger.Warn("visualization: tool error", "error", result.Error)
		return nil
	}
	observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, result.Output, "")

	var vizData map[string]interface{}
	if err := json.Unmarshal([]byte(result.Output), &vizData); err == nil {
		ctx.State["board_visualization"] = vizData["board"]
	}

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Board visualization rendered.")
	ctx.Logger.Info("visualization complete")
	return nil
}
