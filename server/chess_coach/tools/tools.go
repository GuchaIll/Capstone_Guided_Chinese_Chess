package chesstools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"go_agent_framework/core"
	"chess_coach/engine"
)

// ValidateFENTool validates a FEN string using the chess engine.
type ValidateFENTool struct {
	Engine engine.EngineClient
}

func (t *ValidateFENTool) Name() string        { return "validate_fen" }
func (t *ValidateFENTool) Description() string { return "Validate a FEN position string using the chess engine." }
func (t *ValidateFENTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string to validate", Required: true},
	}
}

func (t *ValidateFENTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN string `json:"fen"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("validate_fen: %w", err)
	}
	valid, err := t.Engine.ValidateFEN(ctx, p.FEN)
	if err != nil {
		return "", fmt.Errorf("validate_fen: %w", err)
	}
	out, _ := json.Marshal(map[string]bool{"valid": valid})
	return string(out), nil
}

// AnalyzePositionTool runs engine analysis on a FEN position.
type AnalyzePositionTool struct {
	Engine engine.EngineClient
}

func (t *AnalyzePositionTool) Name() string { return "analyze_position" }
func (t *AnalyzePositionTool) Description() string {
	return "Run engine analysis on a FEN position at a given depth."
}
func (t *AnalyzePositionTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string to analyze", Required: true},
		{Name: "depth", Type: "number", Description: "Search depth for engine analysis", Required: true},
	}
}

func (t *AnalyzePositionTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN   string `json:"fen"`
		Depth int    `json:"depth"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("analyze_position: %w", err)
	}
	if p.Depth <= 0 {
		p.Depth = 20
	}
	resp, err := t.Engine.AnalyzePositionFull(ctx, p.FEN, p.Depth)
	if err != nil {
		// Fallback to legacy Analyze for engines that don't support full analysis.
		metrics, fallbackErr := t.Engine.Analyze(ctx, p.FEN, p.Depth)
		if fallbackErr != nil {
			return "", fmt.Errorf("analyze_position: %w", err)
		}
		out, _ := json.Marshal(metrics)
		return string(out), nil
	}
	out, _ := json.Marshal(resp)
	return string(out), nil
}

// CheckMoveTool checks if a move is legal in a given position.
type CheckMoveTool struct {
	Engine engine.EngineClient
}

func (t *CheckMoveTool) Name() string        { return "is_move_legal" }
func (t *CheckMoveTool) Description() string { return "Check whether a proposed move is legal in the given FEN position." }
func (t *CheckMoveTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
		{Name: "move", Type: "string", Description: "Move in UCI notation (e.g. e2e4)", Required: true},
	}
}

func (t *CheckMoveTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN  string `json:"fen"`
		Move string `json:"move"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("is_move_legal: %w", err)
	}
	legal, err := t.Engine.IsMoveLegal(ctx, p.FEN, p.Move)
	if err != nil {
		return "", fmt.Errorf("is_move_legal: %w", err)
	}
	out, _ := json.Marshal(map[string]bool{"legal": legal})
	return string(out), nil
}

// ValidateEngineTool is a mock tool that validates the engine is operational
// by running a quick analysis on the starting position.
type ValidateEngineTool struct {
	Engine engine.EngineClient
}

func (t *ValidateEngineTool) Name() string { return "validate_engine" }
func (t *ValidateEngineTool) Description() string {
	return "Validate that the chess engine is operational by running a quick analysis."
}
func (t *ValidateEngineTool) Parameters() []core.ToolParameter { return nil }

func (t *ValidateEngineTool) Execute(ctx context.Context, _ json.RawMessage) (string, error) {
	const startFEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
	metrics, err := t.Engine.Analyze(ctx, startFEN, 1)
	if err != nil {
		return "", fmt.Errorf("validate_engine: %w", err)
	}
	out, _ := json.Marshal(map[string]interface{}{
		"status":  "ok",
		"metrics": metrics,
	})
	return string(out), nil
}

// RegisterChessTools registers all chess engine tools with the given registry.
func RegisterChessTools(reg *core.ToolRegistry, eng engine.EngineClient) error {
	for _, t := range []core.Tool{
		// Legacy tools
		&ValidateFENTool{Engine: eng},
		&AnalyzePositionTool{Engine: eng},
		&CheckMoveTool{Engine: eng},
		&GetLegalMovesTool{Engine: eng},
		&ValidateEngineTool{Engine: eng},
		&GetPrincipalVariationTool{Engine: eng},
		&GetMoveRankingsTool{Engine: eng},
		&DetectBlundersTool{Engine: eng},
		&GetGameStateTool{Engine: eng},
		&ValidateMoveLegalityTool{Engine: eng},
		// Feature-aware tools (Phase B)
		&GetPositionFeaturesTool{Engine: eng},
		&ClassifyMoveTool{Engine: eng},
		&GetTacticalPatternsTool{Engine: eng},
		&SuggestBestMoveTool{Engine: eng},
	} {
		if err := reg.Register(t); err != nil {
			return err
		}
	}
	return nil
}

// ── New engine-backed tools ──

// GetLegalMovesTool returns all legal moves for a position.
type GetLegalMovesTool struct {
	Engine engine.EngineClient
}

func (t *GetLegalMovesTool) Name() string        { return "get_legal_moves" }
func (t *GetLegalMovesTool) Description() string { return "Return all legal moves for the given FEN position." }
func (t *GetLegalMovesTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
	}
}

func (t *GetLegalMovesTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN string `json:"fen"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("get_legal_moves: %w", err)
	}
	moves, err := t.Engine.LegalMoves(ctx, p.FEN)
	if err != nil {
		return "", fmt.Errorf("get_legal_moves: %w", err)
	}
	out, _ := json.Marshal(map[string]interface{}{"moves": moves, "count": len(moves)})
	return string(out), nil
}

// GetPrincipalVariationTool returns the principal variation for a position.
type GetPrincipalVariationTool struct {
	Engine engine.EngineClient
}

func (t *GetPrincipalVariationTool) Name() string { return "get_principal_variation" }
func (t *GetPrincipalVariationTool) Description() string {
	return "Get the principal variation (best line of play) from a position."
}
func (t *GetPrincipalVariationTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
		{Name: "depth", Type: "number", Description: "Search depth", Required: true},
	}
}

func (t *GetPrincipalVariationTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN   string `json:"fen"`
		Depth int    `json:"depth"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("get_principal_variation: %w", err)
	}
	if p.Depth <= 0 {
		p.Depth = 20
	}
	resp, err := t.Engine.AnalyzePositionFull(ctx, p.FEN, p.Depth)
	if err != nil {
		// Fallback to legacy Analyze.
		metrics, fallbackErr := t.Engine.Analyze(ctx, p.FEN, p.Depth)
		if fallbackErr != nil {
			return "", fmt.Errorf("get_principal_variation: %w", err)
		}
		pv, _ := metrics["pv"].(string)
		out, _ := json.Marshal(map[string]interface{}{"pv": pv, "eval": metrics["eval"], "depth": p.Depth})
		return string(out), nil
	}
	// Use search metrics from full analysis if available, else from MoveFeatures.
	var pv []string
	var score int
	if resp.MoveFeatures != nil {
		pv = resp.MoveFeatures.SearchMetrics.PrincipalVariation
		score = resp.MoveFeatures.SearchMetrics.Score
	} else {
		score = resp.SearchScore
	}
	out, _ := json.Marshal(map[string]interface{}{"pv": pv, "score": score, "depth": resp.SearchDepth})
	return string(out), nil
}

// GetMoveRankingsTool analyzes candidate moves via batch analysis and ranks by evaluation.
type GetMoveRankingsTool struct {
	Engine engine.EngineClient
}

func (t *GetMoveRankingsTool) Name() string { return "get_move_rankings" }
func (t *GetMoveRankingsTool) Description() string {
	return "Analyze all legal moves via batch analysis and rank them by engine evaluation."
}
func (t *GetMoveRankingsTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
		{Name: "depth", Type: "number", Description: "Search depth", Required: false},
	}
}

func (t *GetMoveRankingsTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN   string `json:"fen"`
		Depth int    `json:"depth"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("get_move_rankings: %w", err)
	}
	if p.Depth <= 0 {
		p.Depth = 15
	}

	// Get legal moves.
	moves, err := t.Engine.LegalMoves(ctx, p.FEN)
	if err != nil {
		return "", fmt.Errorf("get_move_rankings: %w", err)
	}

	// Build batch entries for all legal moves.
	entries := make([]engine.BatchEntry, len(moves))
	for i, mv := range moves {
		entries[i] = engine.BatchEntry{FEN: p.FEN, MoveStr: mv}
	}

	// Single batch call to the engine.
	results, err := t.Engine.BatchAnalyze(ctx, entries)
	if err != nil {
		return "", fmt.Errorf("get_move_rankings: %w", err)
	}

	type ranked struct {
		Move           string `json:"move"`
		Score          int    `json:"score"`
		Category       string `json:"category"`
		PieceType      string `json:"piece_type"`
		IsCapture      bool   `json:"is_capture"`
		CentipawnLoss  int    `json:"centipawn_loss"`
	}
	rankings := make([]ranked, 0, len(results))
	for _, fv := range results {
		rankings = append(rankings, ranked{
			Move:          fv.MoveMetadata.MoveStr,
			Score:         fv.SearchMetrics.Score,
			Category:      fv.Classification.Category,
			PieceType:     fv.MoveMetadata.PieceType,
			IsCapture:     fv.MoveMetadata.IsCapture,
			CentipawnLoss: fv.SearchMetrics.CentipawnLoss,
		})
	}
	out, _ := json.Marshal(map[string]interface{}{"rankings": rankings, "total_moves": len(moves)})
	return string(out), nil
}

// DetectBlundersTool detects blunders in a sequence of moves by evaluation delta.
type DetectBlundersTool struct {
	Engine engine.EngineClient
}

func (t *DetectBlundersTool) Name() string { return "detect_blunders" }
func (t *DetectBlundersTool) Description() string {
	return "Detect blunders in a move sequence by analyzing evaluation drops."
}
func (t *DetectBlundersTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "Starting FEN position", Required: true},
		{Name: "moves", Type: "string", Description: "Space-separated move sequence in UCI notation", Required: true},
		{Name: "threshold", Type: "number", Description: "Eval drop threshold to flag as blunder (centipawns, default 150)", Required: false},
	}
}

func (t *DetectBlundersTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN       string  `json:"fen"`
		Moves     string  `json:"moves"`
		Threshold float64 `json:"threshold"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("detect_blunders: %w", err)
	}
	if p.Threshold <= 0 {
		p.Threshold = 150
	}

	moveList := strings.Fields(p.Moves)

	// Build batch entries: replay the move sequence to produce FEN for each move.
	// For batch_analyze, we need FEN+move pairs. The engine replays internally,
	// but we provide the starting FEN for all entries (engine handles sequencing).
	entries := make([]engine.BatchEntry, len(moveList))
	currentFEN := p.FEN
	for i, mv := range moveList {
		entries[i] = engine.BatchEntry{FEN: currentFEN, MoveStr: mv}
		// Advance position via MakeMove for the next entry's FEN.
		result, err := t.Engine.MakeMove(ctx, currentFEN, mv)
		if err != nil {
			break
		}
		if newFEN, ok := result["fen"].(string); ok && newFEN != "" {
			currentFEN = newFEN
		}
	}

	// Single batch call to get full feature vectors.
	results, err := t.Engine.BatchAnalyze(ctx, entries)
	if err != nil {
		return "", fmt.Errorf("detect_blunders: batch analysis: %w", err)
	}

	type blunder struct {
		MoveIndex     int                      `json:"move_index"`
		Move          string                   `json:"move"`
		Category      string                   `json:"category"`
		CentipawnLoss int                      `json:"centipawn_loss"`
		ScoreDelta    int                      `json:"score_delta"`
		Score         int                      `json:"score"`
		Alternatives  []engine.AlternativeMove `json:"alternatives"`
	}

	var blunders []blunder
	for i, fv := range results {
		// Use the engine's built-in classification.
		if fv.Classification.IsBlunder || fv.Classification.IsInaccuracy ||
			float64(fv.SearchMetrics.CentipawnLoss) > p.Threshold {
			blunders = append(blunders, blunder{
				MoveIndex:     i,
				Move:          fv.MoveMetadata.MoveStr,
				Category:      fv.Classification.Category,
				CentipawnLoss: fv.SearchMetrics.CentipawnLoss,
				ScoreDelta:    fv.SearchMetrics.ScoreDelta,
				Score:         fv.SearchMetrics.Score,
				Alternatives:  fv.Alternatives,
			})
		}
	}

	out, _ := json.Marshal(map[string]interface{}{
		"blunders":    blunders,
		"total_moves": len(moveList),
	})
	return string(out), nil
}

// GetGameStateTool retrieves the current game state from the engine.
type GetGameStateTool struct {
	Engine engine.EngineClient
}

func (t *GetGameStateTool) Name() string        { return "get_game_state" }
func (t *GetGameStateTool) Description() string { return "Get the current game state from the engine." }
func (t *GetGameStateTool) Parameters() []core.ToolParameter { return nil }

func (t *GetGameStateTool) Execute(ctx context.Context, _ json.RawMessage) (string, error) {
	state, err := t.Engine.GetState(ctx)
	if err != nil {
		return "", fmt.Errorf("get_game_state: %w", err)
	}
	out, _ := json.Marshal(state)
	return string(out), nil
}

// ValidateMoveLegalityTool is a user-facing alias for is_move_legal.
type ValidateMoveLegalityTool struct {
	Engine engine.EngineClient
}

func (t *ValidateMoveLegalityTool) Name() string { return "validate_move_legality" }
func (t *ValidateMoveLegalityTool) Description() string {
	return "Validate whether a move is legal in the given position."
}
func (t *ValidateMoveLegalityTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
		{Name: "move", Type: "string", Description: "Move in UCI notation", Required: true},
	}
}

func (t *ValidateMoveLegalityTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN  string `json:"fen"`
		Move string `json:"move"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("validate_move_legality: %w", err)
	}
	legal, err := t.Engine.IsMoveLegal(ctx, p.FEN, p.Move)
	if err != nil {
		return "", fmt.Errorf("validate_move_legality: %w", err)
	}
	out, _ := json.Marshal(map[string]bool{"legal": legal})
	return string(out), nil
}

// parseEval converts an evaluation string like "+0.35" or "-1.20" to a float64.
func parseEval(v interface{}) float64 {
	switch e := v.(type) {
	case float64:
		return e
	case string:
		var f float64
		fmt.Sscanf(e, "%f", &f)
		return f * 100 // convert pawns to centipawns
	}
	return 0
}
