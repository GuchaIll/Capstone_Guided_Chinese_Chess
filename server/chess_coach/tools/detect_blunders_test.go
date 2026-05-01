package chesstools

import (
	"context"
	"encoding/json"
	"testing"

	"chess_coach/engine"
)

type cancelAwareEngine struct {
	cancel      context.CancelFunc
	makeMoveCnt int
}

func (e *cancelAwareEngine) ValidateFEN(context.Context, string) (bool, error) {
	return true, nil
}

func (e *cancelAwareEngine) Analyze(context.Context, string, int) (map[string]interface{}, error) {
	return map[string]interface{}{}, nil
}

func (e *cancelAwareEngine) IsMoveLegal(context.Context, string, string) (bool, error) {
	return true, nil
}

func (e *cancelAwareEngine) LegalMoves(context.Context, string) ([]string, error) {
	return nil, nil
}

func (e *cancelAwareEngine) GetState(context.Context) (map[string]interface{}, error) {
	return map[string]interface{}{}, nil
}

func (e *cancelAwareEngine) MakeMove(ctx context.Context, fen string, _ string) (map[string]interface{}, error) {
	e.makeMoveCnt++
	if e.makeMoveCnt == 1 {
		e.cancel()
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return map[string]interface{}{
		"fen":   fen,
		"valid": true,
	}, nil
}

func (e *cancelAwareEngine) AnalyzePositionFull(context.Context, string, int) (*engine.AnalysisResponse, error) {
	return &engine.AnalysisResponse{}, nil
}

func (e *cancelAwareEngine) BatchAnalyze(ctx context.Context, entries []engine.BatchEntry) ([]engine.MoveFeatureVector, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return []engine.MoveFeatureVector{
		{
			MoveMetadata: engine.MoveMetadata{MoveStr: entries[0].MoveStr},
			SearchMetrics: engine.SearchMetrics{
				Score:         -180,
				CentipawnLoss: 220,
			},
			Classification: engine.MoveClassification{
				Category:   "blunder",
				IsBlunder:  true,
				IsGoodMove: false,
			},
			Alternatives: []engine.AlternativeMove{
				{MoveStr: "h2e2", Score: 50, PieceType: "cannon"},
			},
		},
	}, nil
}

func (e *cancelAwareEngine) Suggest(context.Context, string, int) (string, int, error) {
	return "", 0, nil
}

func (e *cancelAwareEngine) DetectPuzzle(context.Context, string, int) (*engine.PuzzleDetectionResult, error) {
	return &engine.PuzzleDetectionResult{}, nil
}

func TestDetectBlundersIgnoresParentCancellationOnceStarted(t *testing.T) {
	parentCtx, cancel := context.WithCancel(context.Background())
	eng := &cancelAwareEngine{cancel: cancel}
	tool := &DetectBlundersTool{Engine: eng}

	args, err := json.Marshal(map[string]interface{}{
		"fen":   "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1",
		"moves": "h2e2",
	})
	if err != nil {
		t.Fatalf("marshal args: %v", err)
	}

	out, err := tool.Execute(parentCtx, args)
	if err != nil {
		t.Fatalf("Execute() error = %v", err)
	}
	if out == "" {
		t.Fatal("Execute() returned empty output")
	}
}
