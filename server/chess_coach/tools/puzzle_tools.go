package chesstools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"chess_coach/engine"
	"go_agent_framework/core"
)

// FindTacticalMotifTool detects tactical patterns in a position using engine analysis.
type FindTacticalMotifTool struct {
	Engine engine.EngineClient
}

func (t *FindTacticalMotifTool) Name() string { return "find_tactical_motif" }
func (t *FindTacticalMotifTool) Description() string {
	return "Detect tactical motifs (fork, pin, skewer, etc.) in a position via engine analysis."
}
func (t *FindTacticalMotifTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
		{Name: "depth", Type: "number", Description: "Search depth (default 5)", Required: false},
	}
}

func (t *FindTacticalMotifTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN   string `json:"fen"`
		Depth int    `json:"depth"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("find_tactical_motif: %w", err)
	}
	if p.Depth <= 0 {
		p.Depth = 5
	}

	// Try full analysis first for real tactical data.
	resp, err := t.Engine.AnalyzePositionFull(ctx, p.FEN, p.Depth)
	if err == nil && resp.FEN != "" {
		pa := &resp.PositionAnalysis
		var motifs []string
		if len(pa.Forks) > 0 {
			for _, f := range pa.Forks {
				motifs = append(motifs, fmt.Sprintf("fork:%s_attacks_%v", f.AttackerType, f.Targets))
			}
		}
		if len(pa.Pins) > 0 {
			for _, pin := range pa.Pins {
				motifs = append(motifs, fmt.Sprintf("pin:%s_pins_%s", pin.PinnerType, pin.PinnedPiece))
			}
		}
		if len(pa.CannonScreens) > 0 {
			motifs = append(motifs, "cannon_screen")
		}
		if len(pa.HangingPieces) > 0 {
			for _, h := range pa.HangingPieces {
				motifs = append(motifs, fmt.Sprintf("hanging:%s_at_%s", h.PieceType, h.Square))
			}
		}
		if pa.RedInCheck || pa.BlackInCheck {
			motifs = append(motifs, "check")
		}
		if pa.IsCheckmate {
			motifs = append(motifs, "checkmate")
		}
		if len(motifs) == 0 {
			motifs = append(motifs, "positional")
		}

		result := map[string]interface{}{
			"fen":    p.FEN,
			"motifs": motifs,
			"score":  resp.SearchScore,
		}
		if resp.MoveFeatures != nil {
			result["best_move"] = resp.MoveFeatures.MoveMetadata.MoveStr
			result["pv"] = resp.MoveFeatures.SearchMetrics.PrincipalVariation
		}
		out, _ := json.Marshal(result)
		return string(out), nil
	}

	// Fallback to legacy analysis.
	metrics, err2 := t.Engine.Analyze(ctx, p.FEN, p.Depth)
	if err2 != nil {
		if err != nil {
			return "", fmt.Errorf("find_tactical_motif: %w", err)
		}
		return "", fmt.Errorf("find_tactical_motif: %w", err2)
	}

	pv, _ := metrics["pv"].(string)
	eval := metrics["eval"]
	bestMove, _ := metrics["best_move"].(string)
	motifs := classifyMotifs(p.FEN, pv, bestMove)

	out, _ := json.Marshal(map[string]interface{}{
		"fen":       p.FEN,
		"best_move": bestMove,
		"eval":      eval,
		"pv":        pv,
		"motifs":    motifs,
	})
	return string(out), nil
}

// classifyMotifs applies heuristic pattern detection on the PV and position.
func classifyMotifs(fen, pv, bestMove string) []string {
	var motifs []string
	pvMoves := strings.Fields(pv)

	// Heuristic: if PV has a capture sequence (many moves in a row), likely tactical.
	if len(pvMoves) >= 4 {
		motifs = append(motifs, "combination")
	}

	// Heuristic: if the eval swings dramatically, likely a tactic.
	// Placeholder — real implementation would cross-reference piece positions.
	if bestMove != "" {
		motifs = append(motifs, "forced_move")
	}

	if len(motifs) == 0 {
		motifs = append(motifs, "positional")
	}
	return motifs
}

// GeneratePuzzleTool creates a puzzle from a given position by finding the best move sequence.
type GeneratePuzzleTool struct {
	Engine engine.EngineClient
}

func (t *GeneratePuzzleTool) Name() string { return "generate_puzzle" }
func (t *GeneratePuzzleTool) Description() string {
	return "Generate a tactical puzzle from a position by finding the best move sequence."
}
func (t *GeneratePuzzleTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN starting position for the puzzle", Required: true},
		{Name: "solution_depth", Type: "number", Description: "Number of moves in the solution (default 3)", Required: false},
	}
}

func (t *GeneratePuzzleTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN           string `json:"fen"`
		SolutionDepth int    `json:"solution_depth"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("generate_puzzle: %w", err)
	}
	if p.SolutionDepth <= 0 {
		p.SolutionDepth = 3
	}

	// Build the solution using Suggest (engine's best move without applying).
	currentFEN := p.FEN
	type solutionStep struct {
		Move  string `json:"move"`
		Score int    `json:"score"`
	}
	var solution []solutionStep

	for i := 0; i < p.SolutionDepth; i++ {
		bestMove, score, err := t.Engine.Suggest(ctx, currentFEN, 5)
		if err != nil || bestMove == "" {
			// Fallback to legacy analysis.
			metrics, err2 := t.Engine.Analyze(ctx, currentFEN, 5)
			if err2 != nil {
				break
			}
			bestMove, _ = metrics["best_move"].(string)
			if bestMove == "" {
				break
			}
		}
		solution = append(solution, solutionStep{Move: bestMove, Score: score})

		result, err := t.Engine.MakeMove(ctx, currentFEN, bestMove)
		if err != nil {
			break
		}
		newFEN, _ := result["fen"].(string)
		if newFEN == "" {
			break
		}
		currentFEN = newFEN
	}

	out, _ := json.Marshal(map[string]interface{}{
		"starting_fen":   p.FEN,
		"solution":       solution,
		"solution_depth": len(solution),
	})
	return string(out), nil
}

// ValidatePuzzleSolutionTool validates a user's solution attempt against the engine line.
type ValidatePuzzleSolutionTool struct {
	Engine engine.EngineClient
}

func (t *ValidatePuzzleSolutionTool) Name() string { return "validate_puzzle_solution" }
func (t *ValidatePuzzleSolutionTool) Description() string {
	return "Validate a user's puzzle solution against the engine's optimal line."
}
func (t *ValidatePuzzleSolutionTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "Puzzle starting FEN", Required: true},
		{Name: "user_moves", Type: "string", Description: "Space-separated user move sequence", Required: true},
	}
}

func (t *ValidatePuzzleSolutionTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN       string `json:"fen"`
		UserMoves string `json:"user_moves"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("validate_puzzle_solution: %w", err)
	}

	userMoves := strings.Fields(p.UserMoves)

	// Build batch entries for the user's move sequence to classify each in one call.
	currentFEN := p.FEN
	entries := make([]engine.BatchEntry, 0, len(userMoves))
	fenSeq := make([]string, 0, len(userMoves))
	for _, mv := range userMoves {
		entries = append(entries, engine.BatchEntry{FEN: currentFEN, MoveStr: mv})
		fenSeq = append(fenSeq, currentFEN)
		result, err := t.Engine.MakeMove(ctx, currentFEN, mv)
		if err != nil {
			break
		}
		newFEN, _ := result["fen"].(string)
		if newFEN == "" {
			break
		}
		currentFEN = newFEN
	}

	results, err := t.Engine.BatchAnalyze(ctx, entries)
	if err != nil {
		// Fallback to sequential analysis.
		return t.validateSequential(ctx, p.FEN, userMoves)
	}

	var correct = true
	var wrongAt = -1
	type moveResult struct {
		Move          string `json:"move"`
		Category      string `json:"category"`
		CentipawnLoss int    `json:"centipawn_loss"`
		IsOptimal     bool   `json:"is_optimal"`
	}
	var moveResults []moveResult

	for i, fv := range results {
		isOptimal := fv.Classification.IsBrilliant || fv.Classification.IsGoodMove
		if fv.Classification.IsBlunder || fv.Classification.IsInaccuracy {
			if correct {
				correct = false
				wrongAt = i
			}
		}
		moveResults = append(moveResults, moveResult{
			Move:          fv.MoveMetadata.MoveStr,
			Category:      fv.Classification.Category,
			CentipawnLoss: fv.SearchMetrics.CentipawnLoss,
			IsOptimal:     isOptimal,
		})
	}

	out, _ := json.Marshal(map[string]interface{}{
		"correct":       correct,
		"wrong_at_move": wrongAt,
		"moves_checked": len(userMoves),
		"move_details":  moveResults,
	})
	return string(out), nil
}

// validateSequential is the legacy fallback for puzzle validation.
func (t *ValidatePuzzleSolutionTool) validateSequential(ctx context.Context, fen string, userMoves []string) (string, error) {
	currentFEN := fen
	var correct = true
	var wrongAt = -1

	for i, mv := range userMoves {
		metrics, err := t.Engine.Analyze(ctx, currentFEN, 5)
		if err != nil {
			return "", fmt.Errorf("validate_puzzle_solution: %w", err)
		}
		bestMove, _ := metrics["best_move"].(string)
		if mv != bestMove {
			correct = false
			wrongAt = i
			break
		}
		result, err := t.Engine.MakeMove(ctx, currentFEN, mv)
		if err != nil {
			correct = false
			wrongAt = i
			break
		}
		newFEN, _ := result["fen"].(string)
		if newFEN == "" {
			break
		}
		currentFEN = newFEN
	}

	out, _ := json.Marshal(map[string]interface{}{
		"correct":       correct,
		"wrong_at_move": wrongAt,
		"moves_checked": len(userMoves),
	})
	return string(out), nil
}

// RateDifficultyTool estimates puzzle difficulty based on position features.
type RateDifficultyTool struct{}

func (t *RateDifficultyTool) Name() string { return "rate_difficulty" }
func (t *RateDifficultyTool) Description() string {
	return "Estimate puzzle difficulty based on solution depth, piece count, and position complexity."
}
func (t *RateDifficultyTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "solution_depth", Type: "number", Description: "Number of moves in the solution", Required: true},
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
	}
}

func (t *RateDifficultyTool) Execute(_ context.Context, args json.RawMessage) (string, error) {
	var p struct {
		SolutionDepth int    `json:"solution_depth"`
		FEN           string `json:"fen"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("rate_difficulty: %w", err)
	}

	// Count pieces in FEN.
	parts := strings.SplitN(p.FEN, " ", 2)
	pieceCount := 0
	for _, ch := range parts[0] {
		if (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') {
			pieceCount++
		}
	}

	// Heuristic rating: deeper solutions = harder, fewer pieces = more complex endgame.
	rating := 800 // base
	rating += p.SolutionDepth * 200
	if pieceCount <= 10 {
		rating += 300 // endgame bonus
	} else if pieceCount <= 20 {
		rating += 100
	}

	var difficulty string
	switch {
	case rating < 1000:
		difficulty = "beginner"
	case rating < 1400:
		difficulty = "intermediate"
	case rating < 1800:
		difficulty = "advanced"
	default:
		difficulty = "expert"
	}

	out, _ := json.Marshal(map[string]interface{}{
		"rating":     rating,
		"difficulty": difficulty,
		"pieces":     pieceCount,
	})
	return string(out), nil
}

// TagPuzzleThemesTool tags a puzzle with tactical themes based on position features.
type TagPuzzleThemesTool struct{}

func (t *TagPuzzleThemesTool) Name() string { return "tag_puzzle_themes" }
func (t *TagPuzzleThemesTool) Description() string {
	return "Tag a puzzle with tactical themes based on the solution line and position features."
}
func (t *TagPuzzleThemesTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "Puzzle FEN", Required: true},
		{Name: "solution", Type: "string", Description: "Space-separated solution moves", Required: true},
	}
}

func (t *TagPuzzleThemesTool) Execute(_ context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN      string `json:"fen"`
		Solution string `json:"solution"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("tag_puzzle_themes: %w", err)
	}

	moves := strings.Fields(p.Solution)
	var themes []string

	// Heuristic theme detection based on solution characteristics.
	if len(moves) == 1 {
		themes = append(themes, "one_move")
	} else if len(moves) >= 4 {
		themes = append(themes, "combination")
	}

	// Check if the position likely involves castling-related tactics.
	if strings.Contains(p.FEN, "K") && strings.Contains(p.FEN, "k") {
		themes = append(themes, "middlegame")
	}

	// Short solutions with few pieces suggest endgame.
	parts := strings.SplitN(p.FEN, " ", 2)
	pieceCount := 0
	for _, ch := range parts[0] {
		if (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') {
			pieceCount++
		}
	}
	if pieceCount <= 10 {
		themes = append(themes, "endgame")
	}

	if len(themes) == 0 {
		themes = append(themes, "tactical")
	}

	out, _ := json.Marshal(map[string]interface{}{"themes": themes})
	return string(out), nil
}

// GenerateHintTool produces a hint via shallow engine search.
type GenerateHintTool struct {
	Engine engine.EngineClient
}

func (t *GenerateHintTool) Name() string { return "generate_hint" }
func (t *GenerateHintTool) Description() string {
	return "Generate a hint for a puzzle position using a shallow engine search."
}
func (t *GenerateHintTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "Current puzzle FEN", Required: true},
		{Name: "hint_level", Type: "number", Description: "Hint depth: 1=vague, 2=moderate, 3=specific (default 1)", Required: false},
	}
}

func (t *GenerateHintTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN       string `json:"fen"`
		HintLevel int    `json:"hint_level"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("generate_hint: %w", err)
	}
	if p.HintLevel <= 0 {
		p.HintLevel = 1
	}

	// Use Suggest for a lightweight best-move query.
	bestMove, score, err := t.Engine.Suggest(ctx, p.FEN, p.HintLevel*3)
	if err != nil || bestMove == "" {
		// Fallback to legacy analysis.
		metrics, err2 := t.Engine.Analyze(ctx, p.FEN, p.HintLevel*3)
		if err2 != nil {
			if err != nil {
				return "", fmt.Errorf("generate_hint: %w", err)
			}
			return "", fmt.Errorf("generate_hint: %w", err2)
		}
		bestMove, _ = metrics["best_move"].(string)
	}

	var hint string
	switch p.HintLevel {
	case 1:
		if len(bestMove) >= 2 {
			hint = fmt.Sprintf("Look at the %s file.", string(bestMove[0]))
		} else {
			hint = "Look for a forcing move."
		}
	case 2:
		if len(bestMove) >= 2 {
			hint = fmt.Sprintf("Consider moving a piece to the %s file, around rank %s.", string(bestMove[0]), string(bestMove[1]))
		}
	default:
		hint = fmt.Sprintf("The best move starts with %s.", bestMove[:min(3, len(bestMove))])
	}

	out, _ := json.Marshal(map[string]interface{}{
		"hint":       hint,
		"hint_level": p.HintLevel,
		"score":      score,
	})
	return string(out), nil
}

// RegisterPuzzleTools registers all puzzle-related tools.
func RegisterPuzzleTools(reg *core.ToolRegistry, eng engine.EngineClient) error {
	for _, t := range []core.Tool{
		&FindTacticalMotifTool{Engine: eng},
		&GeneratePuzzleTool{Engine: eng},
		&ValidatePuzzleSolutionTool{Engine: eng},
		&RateDifficultyTool{},
		&TagPuzzleThemesTool{},
		&GenerateHintTool{Engine: eng},
	} {
		if err := reg.Register(t); err != nil {
			return err
		}
	}
	return nil
}
