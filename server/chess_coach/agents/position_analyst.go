package agents

import (
	"encoding/json"
	"fmt"

	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// PositionAnalystAgent performs deep position evaluation including opening/middlegame/endgame
// context retrieval and principal variation analysis.
type PositionAnalystAgent struct {
	Tools  *core.ToolRegistry
	Skills *core.SkillRegistry
	Depth  int
}

func (a *PositionAnalystAgent) Name() string { return "position_analyst" }
func (a *PositionAnalystAgent) Description() string {
	return "Deep position analysis: engine evaluation, PV extraction, and phase-specific RAG context."
}
func (a *PositionAnalystAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{
		Tools:  []string{"analyze_position", "get_principal_variation", "get_move_rankings", "get_position_features"},
		Skills: []string{"evaluate_position", "opening_plan", "middlegame_theme", "endgame_principle"},
		RAG:    []string{"openings", "tactics", "endgames"},
	}
}

func (a *PositionAnalystAgent) Run(ctx *core.Context) error {
	if abort, _ := ctx.State["blunder_abort"].(bool); abort {
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Blunder abort active, skipping position analysis.")
		return nil
	}
	if skip, _ := ctx.State["route_position_analysis"].(bool); !skip {
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Position analysis not requested, skipping.")
		return nil
	}

	fen, _ := ctx.State["fen"].(string)
	depth := a.Depth
	if depth == 0 {
		depth = 20
	}

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("Analyzing position at depth %d.", depth))

	// Run engine analysis.
	args, _ := json.Marshal(map[string]interface{}{"fen": fen, "depth": depth})
	call := core.ToolCall{ID: "pa_analyze_1", Name: "analyze_position", Args: args}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, map[string]interface{}{"fen": fen, "depth": depth})

	result := a.Tools.ExecuteTool(ctx.StdContext, call)
	if result.Error != "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, "", result.Error)
		return fmt.Errorf("position_analyst: tool error: %s", result.Error)
	}
	observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, result.Output, "")

	var metrics map[string]interface{}
	if err := json.Unmarshal([]byte(result.Output), &metrics); err != nil {
		return fmt.Errorf("position_analyst: parse result: %w", err)
	}
	ctx.State["engine_metrics"] = metrics

	// Extract structured feature data for downstream agents.
	// The analyze_position tool now returns full PositionAnalysis when the engine supports it.
	if phaseName, ok := metrics["phase_name"].(string); ok {
		ctx.State["game_phase"] = phaseName
	}
	if material, ok := metrics["material"].(map[string]interface{}); ok {
		ctx.State["material_info"] = material
	}
	if hangingPieces, ok := metrics["hanging_pieces"].([]interface{}); ok && len(hangingPieces) > 0 {
		ctx.State["hanging_pieces"] = hangingPieces
	}
	if forks, ok := metrics["forks"].([]interface{}); ok && len(forks) > 0 {
		ctx.State["forks"] = forks
	}
	if pins, ok := metrics["pins"].([]interface{}); ok && len(pins) > 0 {
		ctx.State["pins"] = pins
	}

	// Extract principal variation.
	pvArgs, _ := json.Marshal(map[string]interface{}{"fen": fen, "depth": depth})
	pvCall := core.ToolCall{ID: "pa_pv_1", Name: "get_principal_variation", Args: pvArgs}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, pvCall.Name, map[string]interface{}{"fen": fen, "depth": depth})

	pvResult := a.Tools.ExecuteTool(ctx.StdContext, pvCall)
	if pvResult.Error == "" {
		observability.PublishToolResult(ctx.GraphName, a.Name(), ctx.SessionID, pvCall.Name, pvResult.Output, "")
		var pvData map[string]interface{}
		if err := json.Unmarshal([]byte(pvResult.Output), &pvData); err == nil {
			ctx.State["principal_variation"] = pvData
		}
	}

	// Determine display values from new or legacy format.
	var evalDisplay interface{}
	var bestMoveDisplay interface{}
	var phaseDisplay string
	if score, ok := metrics["search_score"]; ok {
		evalDisplay = score
	} else {
		evalDisplay = metrics["eval"]
	}
	if mf, ok := metrics["move_features"].(map[string]interface{}); ok {
		if mm, ok := mf["move_metadata"].(map[string]interface{}); ok {
			bestMoveDisplay = mm["move_str"]
		}
	} else {
		bestMoveDisplay = metrics["best_move"]
	}
	if p, ok := ctx.State["game_phase"].(string); ok {
		phaseDisplay = p
	}

	// Detect tactical patterns and optionally upgrade the coach trigger.
	tacticalFound := hasPatterns(ctx.State)
	ctx.State["tactical_pattern_detected"] = tacticalFound
	if tacticalFound {
		if trigger, _ := ctx.State["coach_trigger"].(string); trigger == "none" {
			ctx.State["coach_trigger"] = "tactical_pattern"
		}
	}

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("Engine eval: %v, best move: %v, phase: %s, tactical: %v", evalDisplay, bestMoveDisplay, phaseDisplay, tacticalFound))
	ctx.Logger.Info("position_analyst complete", "eval", evalDisplay, "best_move", bestMoveDisplay, "phase", phaseDisplay, "tactical_pattern", tacticalFound)
	return nil
}

func hasPatterns(state map[string]interface{}) bool {
	if hp, ok := state["hanging_pieces"].([]interface{}); ok && len(hp) > 0 {
		return true
	}
	if f, ok := state["forks"].([]interface{}); ok && len(f) > 0 {
		return true
	}
	if p, ok := state["pins"].([]interface{}); ok && len(p) > 0 {
		return true
	}
	return false
}
