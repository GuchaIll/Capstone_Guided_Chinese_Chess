package chesstools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"chess_coach/engine"
	"go_agent_framework/core"
)

// ── GetPositionFeaturesTool ──

// GetPositionFeaturesTool extracts specific feature subsets from a position analysis.
// Accepts a list of feature sections to return, avoiding full-payload overhead.
type GetPositionFeaturesTool struct {
	Engine engine.EngineClient
}

func (t *GetPositionFeaturesTool) Name() string { return "get_position_features" }
func (t *GetPositionFeaturesTool) Description() string {
	return "Extract specific positional feature subsets (e.g. hanging_pieces, forks, king_safety) from a FEN position."
}
func (t *GetPositionFeaturesTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
		{Name: "features", Type: "string", Description: "Comma-separated feature sections: material,mobility,king_safety,hanging_pieces,forks,pins,cannon_screens,rook_files,pawn_chains,cross_river_pieces,piece_locations", Required: true},
		{Name: "depth", Type: "number", Description: "Search depth (default 5)", Required: false},
	}
}

func (t *GetPositionFeaturesTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN      string `json:"fen"`
		Features string `json:"features"`
		Depth    int    `json:"depth"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("get_position_features: %w", err)
	}
	if p.Depth <= 0 {
		p.Depth = 5
	}

	resp, err := t.Engine.AnalyzePositionFull(ctx, p.FEN, p.Depth)
	if err != nil {
		return "", fmt.Errorf("get_position_features: %w", err)
	}

	requested := parseFeatureList(p.Features)
	result := filterPositionFeatures(&resp.PositionAnalysis, requested)

	// Always include basic state.
	result["fen"] = resp.FEN
	result["side_to_move"] = resp.SideToMove
	result["phase_name"] = resp.PhaseName
	result["move_number"] = resp.MoveNumber

	out, _ := json.Marshal(result)
	return string(out), nil
}

// ── ClassifyMoveTool ──

// ClassifyMoveTool evaluates a specific move and returns its classification + alternatives.
type ClassifyMoveTool struct {
	Engine engine.EngineClient
}

func (t *ClassifyMoveTool) Name() string { return "classify_move" }
func (t *ClassifyMoveTool) Description() string {
	return "Classify a move as brilliant/good/inaccuracy/mistake/blunder and return top alternatives."
}
func (t *ClassifyMoveTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position before the move", Required: true},
		{Name: "move", Type: "string", Description: "Move in UCI notation (e.g. h2e2)", Required: true},
		{Name: "depth", Type: "number", Description: "Search depth (default 5)", Required: false},
	}
}

func (t *ClassifyMoveTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN   string `json:"fen"`
		Move  string `json:"move"`
		Depth int    `json:"depth"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("classify_move: %w", err)
	}
	if p.Depth <= 0 {
		p.Depth = 5
	}

	// Use batch_analyze with a single entry to get the full feature vector for this move.
	entries := []engine.BatchEntry{{FEN: p.FEN, MoveStr: p.Move}}
	results, err := t.Engine.BatchAnalyze(ctx, entries)
	if err != nil {
		return "", fmt.Errorf("classify_move: %w", err)
	}
	if len(results) == 0 {
		return "", fmt.Errorf("classify_move: engine returned no results")
	}

	fv := results[0]
	out, _ := json.Marshal(map[string]interface{}{
		"move":           p.Move,
		"classification": fv.Classification,
		"centipawn_loss": fv.SearchMetrics.CentipawnLoss,
		"score":          fv.SearchMetrics.Score,
		"score_delta":    fv.SearchMetrics.ScoreDelta,
		"alternatives":   fv.Alternatives,
		"gives_check":    fv.MoveMetadata.GivesCheck,
		"is_capture":     fv.MoveMetadata.IsCapture,
		"piece_type":     fv.MoveMetadata.PieceType,
	})
	return string(out), nil
}

// ── GetTacticalPatternsTool ──

// GetTacticalPatternsTool extracts tactical patterns (forks, pins, cannon screens, hanging pieces).
type GetTacticalPatternsTool struct {
	Engine engine.EngineClient
}

func (t *GetTacticalPatternsTool) Name() string { return "get_tactical_patterns" }
func (t *GetTacticalPatternsTool) Description() string {
	return "Detect tactical patterns in a position: forks, pins, cannon screens, and hanging pieces."
}
func (t *GetTacticalPatternsTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
	}
}

func (t *GetTacticalPatternsTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN string `json:"fen"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("get_tactical_patterns: %w", err)
	}

	resp, err := t.Engine.AnalyzePositionFull(ctx, p.FEN, 10)
	if err != nil {
		return "", fmt.Errorf("get_tactical_patterns: %w", err)
	}

	pa := resp.PositionAnalysis

	// Filter cannon screens that have actual targets (threatening captures).
	var activeScreens []engine.CannonScreen
	for _, cs := range pa.CannonScreens {
		if cs.TargetPiece != nil {
			activeScreens = append(activeScreens, cs)
		}
	}

	summary := map[string]interface{}{
		"fen":            pa.FEN,
		"side_to_move":   pa.SideToMove,
		"phase_name":     pa.PhaseName,
		"forks":          pa.Forks,
		"pins":           pa.Pins,
		"cannon_screens": activeScreens,
		"hanging_pieces": pa.HangingPieces,
		"has_tactics":    len(pa.Forks) > 0 || len(pa.Pins) > 0 || len(activeScreens) > 0 || len(pa.HangingPieces) > 0,
		"red_in_check":   pa.RedInCheck,
		"black_in_check": pa.BlackInCheck,
	}

	out, _ := json.Marshal(summary)
	return string(out), nil
}

// ── SuggestBestMoveTool ──

// SuggestBestMoveTool asks the engine for a move suggestion without applying it.
type SuggestBestMoveTool struct {
	Engine engine.EngineClient
}

func (t *SuggestBestMoveTool) Name() string { return "suggest_best_move" }
func (t *SuggestBestMoveTool) Description() string {
	return "Get the engine's best move suggestion for a position without applying it."
}
func (t *SuggestBestMoveTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
		{Name: "depth", Type: "number", Description: "Search depth (default 15)", Required: false},
	}
}

func (t *SuggestBestMoveTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN   string `json:"fen"`
		Depth int    `json:"depth"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("suggest_best_move: %w", err)
	}
	if p.Depth <= 0 {
		p.Depth = 15
	}

	move, score, err := t.Engine.Suggest(ctx, p.FEN, p.Depth)
	if err != nil {
		return "", fmt.Errorf("suggest_best_move: %w", err)
	}

	out, _ := json.Marshal(map[string]interface{}{
		"best_move": move,
		"score":     score,
	})
	return string(out), nil
}

// ── helpers ──

func parseFeatureList(features string) map[string]bool {
	result := make(map[string]bool)
	for _, f := range strings.Split(features, ",") {
		f = strings.TrimSpace(f)
		if f != "" {
			result[f] = true
		}
	}
	return result
}

func filterPositionFeatures(pa *engine.PositionAnalysis, requested map[string]bool) map[string]interface{} {
	result := make(map[string]interface{})

	if requested["material"] {
		result["material"] = pa.Material
	}
	if requested["mobility"] {
		result["mobility"] = pa.Mobility
	}
	if requested["king_safety"] {
		result["red_king_safety"] = pa.RedKingSafety
		result["black_king_safety"] = pa.BlackKingSafety
	}
	if requested["hanging_pieces"] {
		result["hanging_pieces"] = pa.HangingPieces
	}
	if requested["forks"] {
		result["forks"] = pa.Forks
	}
	if requested["pins"] {
		result["pins"] = pa.Pins
	}
	if requested["cannon_screens"] {
		result["cannon_screens"] = pa.CannonScreens
	}
	if requested["rook_files"] {
		result["rook_files"] = pa.RookFiles
	}
	if requested["pawn_chains"] {
		result["pawn_chains"] = pa.PawnChains
	}
	if requested["cross_river_pieces"] {
		result["cross_river_pieces"] = pa.CrossRiverPieces
	}
	if requested["piece_locations"] {
		result["piece_locations"] = pa.PieceLocations
	}
	if requested["pst"] {
		result["red_pst_score"] = pa.RedPSTScore
		result["black_pst_score"] = pa.BlackPSTScore
	}

	return result
}
