package agents

import (
	"encoding/json"
	"fmt"
	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// AnalysisAgent calls the chess engine tool to evaluate the position.
type AnalysisAgent struct {
	Tools *core.ToolRegistry
	Depth int
}

func (a *AnalysisAgent) Name() string        { return "analysis" }
func (a *AnalysisAgent) Description() string { return "Evaluates the position using the chess engine at depth 20." }
func (a *AnalysisAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{Tools: []string{"analyze_position"}}
}

func (a *AnalysisAgent) Run(ctx *core.Context) error {
	fen, _ := ctx.State["fen"].(string)

	depth := a.Depth
	if depth == 0 {
		depth = 20
	}

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, fmt.Sprintf("Analyzing position at depth %d.", depth))

	args, _ := json.Marshal(map[string]interface{}{"fen": fen, "depth": depth})
	call := core.ToolCall{ID: "analyze_1", Name: "analyze_position", Args: args}

	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, map[string]interface{}{"fen": fen, "depth": depth})

	result := a.Tools.ExecuteTool(ctx.StdContext, call)
	if result.Error != "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, "", result.Error)
		return fmt.Errorf("analysis: tool error: %s", result.Error)
	}

	observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, result.Output, "")

	var metrics map[string]interface{}
	if err := json.Unmarshal([]byte(result.Output), &metrics); err != nil {
		return fmt.Errorf("analysis: parse result: %w", err)
	}

	ctx.State["engine_metrics"] = metrics
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, fmt.Sprintf("Engine evaluation: %v, best move: %v.", metrics["eval"], metrics["best_move"]))
	ctx.Logger.Info("analysis complete", "eval", metrics["eval"], "best_move", metrics["best_move"])
	return nil
}
