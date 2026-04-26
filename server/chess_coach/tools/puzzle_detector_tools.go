package chesstools

// puzzle_detector_tools.go — Puzzle tools powered by the Rust puzzle_detector module.
//
// These tools replace the heuristic implementations in puzzle_tools.go.
// They call the state-bridge /engine/puzzle-detect endpoint (which relays to the
// Rust engine's detect_puzzle WebSocket message) and use the structured
// PuzzleDetectionResult response rather than hand-crafted heuristics.
//
// Registration: use RegisterPuzzleDetectorTools instead of RegisterPuzzleTools in
// cmd/main.go to activate these implementations.

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"chess_coach/engine"
	"go_agent_framework/core"
)

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 1. FindTacticalMotifTool — call DetectPuzzle, return structured motifs
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

type PDFindTacticalMotifTool struct {
	Engine engine.EngineClient
}

func (t *PDFindTacticalMotifTool) Name() string { return "find_tactical_motif" }
func (t *PDFindTacticalMotifTool) Description() string {
	return "Detect tactical motifs (fork, pin, skewer, cannon threat, hanging piece, etc.) " +
		"in a position using the Rust puzzle_detector engine module."
}
func (t *PDFindTacticalMotifTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
		{Name: "depth", Type: "number", Description: "Search depth for best-move hint (default 5)", Required: false},
	}
}

func (t *PDFindTacticalMotifTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
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

	det, err := t.Engine.DetectPuzzle(ctx, p.FEN, p.Depth)
	if err != nil {
		return "", fmt.Errorf("find_tactical_motif: %w", err)
	}

	// Build a compact motifs slice for the LLM.
	type motifOut struct {
		Type        string   `json:"type"`
		Description string   `json:"description"`
		Weight      uint32   `json:"weight"`
		Squares     []string `json:"squares"`
	}
	var motifs []motifOut
	for _, m := range det.Motifs {
		motifs = append(motifs, motifOut{
			Type:        m.MotifType,
			Description: m.Description,
			Weight:      m.Weight,
			Squares:     m.Squares,
		})
	}
	if motifs == nil {
		motifs = []motifOut{}
	}

	out, _ := json.Marshal(map[string]interface{}{
		"fen":              p.FEN,
		"motifs":           motifs,
		"motif_score":      det.MotifScore,
		"is_puzzle_worthy": det.IsPuzzleWorthy,
		"phase":            det.Phase,
	})
	return string(out), nil
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 2. GeneratePuzzleTool — build a move solution line then enrich with DetectPuzzle
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

type PDGeneratePuzzleTool struct {
	Engine engine.EngineClient
}

func (t *PDGeneratePuzzleTool) Name() string { return "generate_puzzle" }
func (t *PDGeneratePuzzleTool) Description() string {
	return "Generate a tactical puzzle from a position by finding the best move sequence " +
		"and enriching it with Rust puzzle_detector metadata."
}
func (t *PDGeneratePuzzleTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN starting position for the puzzle", Required: true},
		{Name: "solution_depth", Type: "number", Description: "Number of moves in the solution (default 3)", Required: false},
	}
}

func (t *PDGeneratePuzzleTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
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

	// Build solution line using Suggest.
	currentFEN := p.FEN
	type solutionStep struct {
		Move  string `json:"move"`
		Score int    `json:"score"`
	}
	var solution []solutionStep

	for i := 0; i < p.SolutionDepth; i++ {
		bestMove, score, err := t.Engine.Suggest(ctx, currentFEN, 5)
		if err != nil || bestMove == "" {
			break
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

	// Enrich the starting position with puzzle metadata.
	det, err := t.Engine.DetectPuzzle(ctx, p.FEN, clampDepth(p.SolutionDepth*3))
	if err != nil {
		// Non-fatal: return what we have.
		out, _ := json.Marshal(map[string]interface{}{
			"starting_fen":   p.FEN,
			"solution":       solution,
			"solution_depth": len(solution),
		})
		return string(out), nil
	}

	out, _ := json.Marshal(map[string]interface{}{
		"starting_fen":     p.FEN,
		"solution":         solution,
		"solution_depth":   len(solution),
		"is_puzzle_worthy": det.IsPuzzleWorthy,
		"motif_score":      det.MotifScore,
		"themes":           det.Themes,
		"difficulty_elo":   det.DifficultyElo,
		"difficulty_label": det.DifficultyLabel,
		"hints":            det.Hints,
	})
	return string(out), nil
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 3. ValidatePuzzleSolutionTool — unchanged: batch-analyze based validation
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// PDValidatePuzzleSolutionTool validates a user's solution using BatchAnalyze.
// The puzzle_detector result enriches the response with difficulty context.
type PDValidatePuzzleSolutionTool struct {
	Engine engine.EngineClient
}

func (t *PDValidatePuzzleSolutionTool) Name() string { return "validate_puzzle_solution" }
func (t *PDValidatePuzzleSolutionTool) Description() string {
	return "Validate a user's puzzle solution against the engine's optimal line."
}
func (t *PDValidatePuzzleSolutionTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "Puzzle starting FEN", Required: true},
		{Name: "user_moves", Type: "string", Description: "Space-separated user move sequence", Required: true},
	}
}

func (t *PDValidatePuzzleSolutionTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN       string `json:"fen"`
		UserMoves string `json:"user_moves"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("validate_puzzle_solution: %w", err)
	}

	userMoves := strings.Fields(p.UserMoves)
	currentFEN := p.FEN
	entries := make([]engine.BatchEntry, 0, len(userMoves))
	for _, mv := range userMoves {
		entries = append(entries, engine.BatchEntry{FEN: currentFEN, MoveStr: mv})
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
		return "", fmt.Errorf("validate_puzzle_solution: %w", err)
	}

	correct := true
	wrongAt := -1
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

	// Enrich with puzzle context at the starting position.
	det, detErr := t.Engine.DetectPuzzle(ctx, p.FEN, 5)

	resp := map[string]interface{}{
		"correct":       correct,
		"wrong_at_move": wrongAt,
		"moves_checked": len(userMoves),
		"move_details":  moveResults,
	}
	if detErr == nil {
		resp["difficulty_elo"] = det.DifficultyElo
		resp["difficulty_label"] = det.DifficultyLabel
		resp["themes"] = det.Themes
	}

	out, _ := json.Marshal(resp)
	return string(out), nil
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 4. RateDifficultyTool — use Rust formula via DetectPuzzle
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

type PDRateDifficultyTool struct {
	Engine engine.EngineClient
}

func (t *PDRateDifficultyTool) Name() string { return "rate_difficulty" }
func (t *PDRateDifficultyTool) Description() string {
	return "Estimate puzzle difficulty using the Rust engine's formula: " +
		"800 + depth×200 + piece_count×5, with labels beginner/intermediate/advanced/expert."
}
func (t *PDRateDifficultyTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string", Required: true},
		{Name: "solution_depth", Type: "number", Description: "Number of moves in solution (default 3)", Required: false},
	}
}

func (t *PDRateDifficultyTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN           string `json:"fen"`
		SolutionDepth int    `json:"solution_depth"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("rate_difficulty: %w", err)
	}
	if p.SolutionDepth <= 0 {
		p.SolutionDepth = 3
	}

	det, err := t.Engine.DetectPuzzle(ctx, p.FEN, clampDepth(p.SolutionDepth))
	if err != nil {
		// Fallback to local heuristic so the tool never errors.
		elo, label := localDifficultyRating(p.FEN, p.SolutionDepth)
		out, _ := json.Marshal(map[string]interface{}{
			"rating":     elo,
			"difficulty": label,
			"source":     "local_heuristic",
		})
		return string(out), nil
	}

	out, _ := json.Marshal(map[string]interface{}{
		"rating":      det.DifficultyElo,
		"difficulty":  det.DifficultyLabel,
		"piece_count": det.PieceCount,
		"source":      "rust_engine",
	})
	return string(out), nil
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 5. TagPuzzleThemesTool — use Rust themes from DetectPuzzle
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

type PDTagPuzzleThemesTool struct {
	Engine engine.EngineClient
}

func (t *PDTagPuzzleThemesTool) Name() string { return "tag_puzzle_themes" }
func (t *PDTagPuzzleThemesTool) Description() string {
	return "Tag a puzzle with tactical themes (fork, pin, endgame, combination, etc.) " +
		"using the Rust puzzle_detector engine module."
}
func (t *PDTagPuzzleThemesTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "Puzzle FEN", Required: true},
		{Name: "solution", Type: "string", Description: "Space-separated solution moves (for depth hint)", Required: false},
	}
}

func (t *PDTagPuzzleThemesTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN      string `json:"fen"`
		Solution string `json:"solution"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("tag_puzzle_themes: %w", err)
	}

	depth := len(strings.Fields(p.Solution))
	if depth <= 0 {
		depth = 3
	}

	det, err := t.Engine.DetectPuzzle(ctx, p.FEN, clampDepth(depth))
	if err != nil {
		return "", fmt.Errorf("tag_puzzle_themes: %w", err)
	}

	themes := det.Themes
	if len(themes) == 0 {
		themes = []string{"tactical"}
	}

	out, _ := json.Marshal(map[string]interface{}{
		"themes":      themes,
		"phase":       det.Phase,
		"motif_score": det.MotifScore,
	})
	return string(out), nil
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 6. GenerateHintTool — use structured hints from DetectPuzzle
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

type PDGenerateHintTool struct {
	Engine engine.EngineClient
}

func (t *PDGenerateHintTool) Name() string { return "generate_hint" }
func (t *PDGenerateHintTool) Description() string {
	return "Generate a hint for a puzzle position using the Rust puzzle_detector module. " +
		"hint_level 1=vague (motif type), 2=moderate (piece/file), 3=specific (from-square)."
}
func (t *PDGenerateHintTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "Current puzzle FEN", Required: true},
		{Name: "hint_level", Type: "number", Description: "Hint depth: 1=vague, 2=moderate, 3=specific (default 1)", Required: false},
	}
}

func (t *PDGenerateHintTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN       string `json:"fen"`
		HintLevel int    `json:"hint_level"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("generate_hint: %w", err)
	}
	if p.HintLevel <= 0 || p.HintLevel > 3 {
		p.HintLevel = 1
	}

	// Deeper analysis for higher hint levels to ensure best_move is populated.
	depth := p.HintLevel * 5
	det, err := t.Engine.DetectPuzzle(ctx, p.FEN, clampDepth(depth))
	if err != nil {
		return "", fmt.Errorf("generate_hint: %w", err)
	}

	// Find the hint at the requested level.
	hintText := "Look for the best move."
	for _, h := range det.Hints {
		if int(h.Level) == p.HintLevel {
			hintText = h.Text
			break
		}
	}

	out, _ := json.Marshal(map[string]interface{}{
		"hint":       hintText,
		"hint_level": p.HintLevel,
		"motifs":     len(det.Motifs),
	})
	return string(out), nil
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Registration
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// RegisterPuzzleDetectorTools registers all puzzle tools backed by the Rust
// puzzle_detector module.  Call this instead of RegisterPuzzleTools to use
// the structured, engine-powered implementations.
func RegisterPuzzleDetectorTools(reg *core.ToolRegistry, eng engine.EngineClient) error {
	for _, t := range []core.Tool{
		&PDFindTacticalMotifTool{Engine: eng},
		&PDGeneratePuzzleTool{Engine: eng},
		&PDValidatePuzzleSolutionTool{Engine: eng},
		&PDRateDifficultyTool{Engine: eng},
		&PDTagPuzzleThemesTool{Engine: eng},
		&PDGenerateHintTool{Engine: eng},
	} {
		if err := reg.Register(t); err != nil {
			return err
		}
	}
	return nil
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Helpers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// clampDepth keeps depth within the coaching service's performance target [1, 5].
func clampDepth(d int) int {
	if d < 1 {
		return 1
	}
	if d > 5 {
		return 5
	}
	return d
}

// localDifficultyRating is a fallback when the engine is unavailable.
// Mirrors the Rust formula: 800 + depth×200 + piece_count×5.
func localDifficultyRating(fen string, depth int) (int, string) {
	parts := strings.SplitN(fen, " ", 2)
	pieceCount := 0
	for _, ch := range parts[0] {
		if (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') {
			pieceCount++
		}
	}
	elo := 800 + depth*200 + pieceCount*5
	var label string
	switch {
	case elo < 1000:
		label = "beginner"
	case elo < 1400:
		label = "intermediate"
	case elo < 1800:
		label = "advanced"
	default:
		label = "expert"
	}
	return elo, label
}
