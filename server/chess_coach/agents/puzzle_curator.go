package agents

import (
	"encoding/json"
	"fmt"

	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// PuzzleCuratorAgent generates tactical puzzles from positions where blunders
// were detected or when the user explicitly requests puzzle practice.
type PuzzleCuratorAgent struct {
	Tools  *core.ToolRegistry
	Skills *core.SkillRegistry
}

func (a *PuzzleCuratorAgent) Name() string { return "puzzle_curator" }
func (a *PuzzleCuratorAgent) Description() string {
	return "Generates tactical puzzles from blunder positions or on-demand requests."
}
func (a *PuzzleCuratorAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{
		Tools:  []string{"find_tactical_motif", "generate_puzzle", "rate_difficulty", "tag_puzzle_themes", "generate_hint", "get_tactical_patterns"},
		Skills: []string{"generate_puzzle", "find_tactical_motif"},
	}
}

func (a *PuzzleCuratorAgent) Run(ctx *core.Context) error {
	if skip, _ := ctx.State["route_puzzle"].(bool); !skip {
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Puzzle generation not requested, skipping.")
		return nil
	}

	fen, _ := ctx.State["fen"].(string)
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("Generating puzzle from position."))

	// Step 0: Get tactical patterns for context.
	patArgs, _ := json.Marshal(map[string]interface{}{"fen": fen})
	patCall := core.ToolCall{ID: "pc_patterns_1", Name: "get_tactical_patterns", Args: patArgs}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, patCall.Name, map[string]interface{}{"fen": fen})

	patResult := a.Tools.ExecuteTool(ctx.StdContext, patCall)
	if patResult.Error == "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, patCall.Name, patResult.Output, "")
		var patData map[string]interface{}
		_ = json.Unmarshal([]byte(patResult.Output), &patData)
		ctx.State["tactical_patterns"] = patData
	}

	// Step 1: Find tactical motifs.
	motifArgs, _ := json.Marshal(map[string]interface{}{"fen": fen, "depth": 15})
	motifCall := core.ToolCall{ID: "pc_motif_1", Name: "find_tactical_motif", Args: motifArgs}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, motifCall.Name, map[string]interface{}{"fen": fen})

	motifResult := a.Tools.ExecuteTool(ctx.StdContext, motifCall)
	if motifResult.Error != "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, motifCall.Name, "", motifResult.Error)
		return fmt.Errorf("puzzle_curator: motif detection error: %s", motifResult.Error)
	}
	observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, motifCall.Name, motifResult.Output, "")

	var motifData map[string]interface{}
	_ = json.Unmarshal([]byte(motifResult.Output), &motifData)
	ctx.State["tactical_motifs"] = motifData

	// Step 2: Generate the puzzle.
	puzzleArgs, _ := json.Marshal(map[string]interface{}{"fen": fen, "solution_depth": 3})
	puzzleCall := core.ToolCall{ID: "pc_puzzle_1", Name: "generate_puzzle", Args: puzzleArgs}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, puzzleCall.Name, map[string]interface{}{"fen": fen})

	puzzleResult := a.Tools.ExecuteTool(ctx.StdContext, puzzleCall)
	if puzzleResult.Error != "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, puzzleCall.Name, "", puzzleResult.Error)
		return fmt.Errorf("puzzle_curator: puzzle generation error: %s", puzzleResult.Error)
	}
	observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, puzzleCall.Name, puzzleResult.Output, "")

	var puzzleData map[string]interface{}
	_ = json.Unmarshal([]byte(puzzleResult.Output), &puzzleData)
	ctx.State["puzzle"] = puzzleData

	// Step 3: Rate difficulty.
	solutionDepth := 3
	if sd, ok := puzzleData["solution_depth"].(float64); ok {
		solutionDepth = int(sd)
	}
	rateArgs, _ := json.Marshal(map[string]interface{}{"fen": fen, "solution_depth": solutionDepth})
	rateCall := core.ToolCall{ID: "pc_rate_1", Name: "rate_difficulty", Args: rateArgs}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, rateCall.Name, map[string]interface{}{"fen": fen})

	rateResult := a.Tools.ExecuteTool(ctx.StdContext, rateCall)
	if rateResult.Error == "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, rateCall.Name, rateResult.Output, "")
		var rateData map[string]interface{}
		_ = json.Unmarshal([]byte(rateResult.Output), &rateData)
		ctx.State["puzzle_difficulty"] = rateData
	}

	// Step 4: Tag themes.
	// Extract solution moves — handle both old ([]string) and new ([]solutionStep) formats.
	solution := ""
	if sol, ok := puzzleData["solution"].([]interface{}); ok {
		parts := make([]string, 0, len(sol))
		for _, s := range sol {
			switch v := s.(type) {
			case string:
				parts = append(parts, v)
			case map[string]interface{}:
				if mv, ok := v["move"].(string); ok {
					parts = append(parts, mv)
				}
			}
		}
		solution = joinStrings(parts, " ")
	}
	tagArgs, _ := json.Marshal(map[string]interface{}{"fen": fen, "solution": solution})
	tagCall := core.ToolCall{ID: "pc_tag_1", Name: "tag_puzzle_themes", Args: tagArgs}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, tagCall.Name, map[string]interface{}{"fen": fen})

	tagResult := a.Tools.ExecuteTool(ctx.StdContext, tagCall)
	if tagResult.Error == "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, tagCall.Name, tagResult.Output, "")
		var tagData map[string]interface{}
		_ = json.Unmarshal([]byte(tagResult.Output), &tagData)
		ctx.State["puzzle_themes"] = tagData
	}

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Puzzle generated and tagged.")
	ctx.Logger.Info("puzzle_curator complete", "puzzle", puzzleData)
	return nil
}

func joinStrings(parts []string, sep string) string {
	if len(parts) == 0 {
		return ""
	}
	result := parts[0]
	for _, p := range parts[1:] {
		result += sep + p
	}
	return result
}
