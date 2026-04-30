package agents

import (
	"encoding/json"
	"fmt"
	"strings"

	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// BlunderDetectionAgent analyzes a move sequence to identify blunders
// (moves that cause a significant evaluation drop).
type BlunderDetectionAgent struct {
	Tools *core.ToolRegistry
}

func (a *BlunderDetectionAgent) Name() string { return "blunder_detection" }
func (a *BlunderDetectionAgent) Description() string {
	return "Detects blunders in a move sequence by comparing evaluations before and after each move."
}
func (a *BlunderDetectionAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{
		Tools:  []string{"detect_blunders", "get_move_rankings", "classify_move"},
		Skills: []string{"detect_blunders"},
	}
}

func (a *BlunderDetectionAgent) Run(ctx *core.Context) error {
	if skip, _ := ctx.State["route_blunder_detection"].(bool); !skip {
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Blunder detection not requested, skipping.")
		return nil
	}

	fen, _ := ctx.State["fen"].(string)
	move, _ := ctx.State["move"].(string)
	moves, _ := ctx.State["moves"].(string)

	// Build the move list from either "moves" or single "move".
	moveSeq := moves
	if moveSeq == "" && move != "" {
		moveSeq = move
	}
	if moveSeq == "" {
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "No moves to analyze for blunders.")
		return nil
	}

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("Detecting blunders in %d moves.", len(strings.Fields(moveSeq))))

	args, _ := json.Marshal(map[string]interface{}{
		"fen":       fen,
		"moves":     moveSeq,
		"threshold": 150,
	})
	call := core.ToolCall{ID: "bd_detect_1", Name: "detect_blunders", Args: args}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, call.Name,
		map[string]interface{}{"fen": fen, "moves": moveSeq})

	result := a.Tools.ExecuteTool(ctx.StdContext, call)
	if result.Error != "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, "", result.Error)
		return fmt.Errorf("blunder_detection: tool error: %s", result.Error)
	}
	observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, result.Output, "")

	var blunderData map[string]interface{}
	if err := json.Unmarshal([]byte(result.Output), &blunderData); err != nil {
		return fmt.Errorf("blunder_detection: parse result: %w", err)
	}

	ctx.State["blunder_analysis"] = blunderData

	if blunders, ok := blunderData["blunders"].([]interface{}); ok && len(blunders) > 0 {
		// Abort all downstream agents — feedback will emit the blunder summary only.
		ctx.State["blunder_abort"] = true
		ctx.State["blunder_positions"] = blunders
		// Queue puzzle for the next turn (not this one, since we are aborting).
		ctx.State["route_puzzle"] = true
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
			fmt.Sprintf("Found %d blunder(s) — aborting downstream agents, queuing puzzle for next turn.", len(blunders)))
	} else {
		ctx.State["blunder_abort"] = false
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
			"No engine blunders detected; tactical patterns may still inform coaching, but they do not trigger a blunder abort.")
	}

	ctx.Logger.Info("blunder_detection complete", "blunder_abort", ctx.State["blunder_abort"])
	return nil
}
