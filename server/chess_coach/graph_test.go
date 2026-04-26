package chess

import (
	"context"
	"io"
	"log/slog"
	"strings"
	"testing"

	"chess_coach/engine"
	chesstools "chess_coach/tools"
	"go_agent_framework/contrib/llm"
	"go_agent_framework/core"
)

const testGraphFEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"

type countingLLM struct {
	response string
	calls    int
}

func (c *countingLLM) Generate(_ context.Context, _ string) (string, error) {
	c.calls++
	return c.response, nil
}

func (c *countingLLM) Provider() string { return "counting" }
func (c *countingLLM) Model() string    { return "counting-llm" }

type rejectingMoveEngine struct {
	*engine.MockEngine
}

func (e *rejectingMoveEngine) IsMoveLegal(_ context.Context, _, _ string) (bool, error) {
	return false, nil
}

type blunderEngine struct {
	*engine.MockEngine
}

func (e *blunderEngine) BatchAnalyze(_ context.Context, entries []engine.BatchEntry) ([]engine.MoveFeatureVector, error) {
	results := make([]engine.MoveFeatureVector, len(entries))
	for i, entry := range entries {
		results[i] = engine.MoveFeatureVector{
			PositionAnalysis: engine.PositionAnalysis{FEN: entry.FEN, PhaseName: "opening"},
			MoveMetadata: engine.MoveMetadata{
				MoveStr:   entry.MoveStr,
				PieceType: "knight",
				PieceSide: "red",
			},
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
				{MoveStr: "h2e2", Score: 50, PieceType: "cannon", IsCapture: false},
			},
			PostMoveFEN: entry.FEN,
		}
	}
	return results, nil
}

func newGraphForTest(t *testing.T, eng engine.EngineClient, models llm.Models) *core.Graph {
	t.Helper()
	toolReg := core.NewToolRegistry()
	if err := chesstools.RegisterChessTools(toolReg, eng); err != nil {
		t.Fatalf("register chess tools: %v", err)
	}
	if err := chesstools.RegisterPuzzleDetectorTools(toolReg, eng); err != nil {
		t.Fatalf("register puzzle tools: %v", err)
	}
	return BuildGraph(toolReg, core.NewSkillRegistry(), models)
}

func newGraphContext(state map[string]interface{}) *core.Context {
	return &core.Context{
		SessionID:  "graph-test-session",
		State:      state,
		Logger:     slog.New(slog.NewTextHandler(io.Discard, nil)),
		StdContext: context.Background(),
	}
}

func TestBuildGraphFastPathSkipsCoachLLMAndReturnsAnalysis(t *testing.T) {
	coachLLM := &countingLLM{response: "This should never be used on the fast path."}
	graph := newGraphForTest(t, &engine.MockEngine{}, llm.Models{
		Analysis:      coachLLM,
		Orchestration: &countingLLM{response: "EXPLAIN"},
	})

	ctx := newGraphContext(map[string]interface{}{
		"fen":                    testGraphFEN,
		"question":               "What is the evaluation here?",
		"moves_since_last_coach": 0,
	})

	if err := graph.Run(ctx); err != nil {
		t.Fatalf("graph run: %v", err)
	}

	feedback, _ := ctx.State["feedback"].(string)
	if feedback == "" {
		t.Fatalf("feedback should not be empty")
	}
	if !strings.Contains(feedback, "Evaluation:") {
		t.Fatalf("feedback missing evaluation: %q", feedback)
	}
	if strings.Contains(feedback, "Coaching advice [") {
		t.Fatalf("fast path should not include coaching advice: %q", feedback)
	}
	if got, _ := ctx.State["coaching_advice"].(string); got != "" {
		t.Fatalf("fast path should not generate coaching_advice, got %q", got)
	}
	if coachLLM.calls != 0 {
		t.Fatalf("coach LLM should not be called on fast path, got %d calls", coachLLM.calls)
	}
}

func TestBuildGraphSlowPathInvokesCoachLLMAndGuard(t *testing.T) {
	coachLLM := &countingLLM{response: "Play b0c2 to prioritize central development and king safety."}
	graph := newGraphForTest(t, &engine.MockEngine{}, llm.Models{
		Analysis:      coachLLM,
		Orchestration: &countingLLM{response: "EXPLAIN"},
	})

	ctx := newGraphContext(map[string]interface{}{
		"fen":                    testGraphFEN,
		"question":               "What should Red do here?",
		"moves_since_last_coach": 3,
	})

	if err := graph.Run(ctx); err != nil {
		t.Fatalf("graph run: %v", err)
	}

	feedback, _ := ctx.State["feedback"].(string)
	if feedback == "" {
		t.Fatalf("feedback should not be empty")
	}
	if !strings.Contains(feedback, "Evaluation:") {
		t.Fatalf("feedback missing evaluation: %q", feedback)
	}
	if !strings.Contains(feedback, "Coaching advice [move_count]") {
		t.Fatalf("feedback missing coaching advice section: %q", feedback)
	}
	if !strings.Contains(feedback, "Play b0c2") {
		t.Fatalf("feedback missing LLM advice: %q", feedback)
	}
	if coachLLM.calls != 1 {
		t.Fatalf("coach LLM should be called once on slow path, got %d calls", coachLLM.calls)
	}
	if approved, _ := ctx.State["coach_advice_approved"].(bool); !approved {
		t.Fatalf("guard should approve legal advice")
	}
}

func TestBuildGraphMoveCommentRequestTriggersSlowPathWithoutMoveCount(t *testing.T) {
	coachLLM := &countingLLM{response: "The move e6e5 fights for space but you must still watch loose pieces."}
	graph := newGraphForTest(t, &engine.MockEngine{}, llm.Models{
		Analysis:      coachLLM,
		Orchestration: &countingLLM{response: "EXPLAIN"},
	})

	ctx := newGraphContext(map[string]interface{}{
		"fen":                    testGraphFEN,
		"question":               "Comment on this move.",
		"move":                   "e6e5",
		"has_move":               true,
		"moves_since_last_coach": 0,
	})

	if err := graph.Run(ctx); err != nil {
		t.Fatalf("graph run: %v", err)
	}

	if coachLLM.calls != 1 {
		t.Fatalf("coach LLM should be called for explicit move commentary, got %d calls", coachLLM.calls)
	}
	if got, _ := ctx.State["coach_trigger"].(string); got != "explicit" {
		t.Fatalf("expected explicit coach trigger, got %q", got)
	}
}

func TestBuildGraphSuppressesIllegalAdviceOnSlowPath(t *testing.T) {
	graph := newGraphForTest(t, &rejectingMoveEngine{MockEngine: &engine.MockEngine{}}, llm.Models{
		Analysis:      &countingLLM{response: "Play a0a3 immediately to attack."},
		Orchestration: &countingLLM{response: "EXPLAIN"},
	})

	ctx := newGraphContext(map[string]interface{}{
		"fen":                    testGraphFEN,
		"question":               "What should Red do here?",
		"moves_since_last_coach": 3,
	})

	if err := graph.Run(ctx); err != nil {
		t.Fatalf("graph run: %v", err)
	}

	feedback, _ := ctx.State["feedback"].(string)
	if strings.Contains(feedback, "a0a3") {
		t.Fatalf("illegal advice move should not appear in final feedback: %q", feedback)
	}
	if strings.Contains(feedback, "Coaching advice [") {
		t.Fatalf("guarded feedback should omit coaching section when advice is rejected: %q", feedback)
	}
	if approved, _ := ctx.State["coach_advice_approved"].(bool); approved {
		t.Fatalf("guard should reject illegal advice")
	}
}

func TestBuildGraphBlunderAbortSkipsCoachAndReturnsBlunderSummary(t *testing.T) {
	coachLLM := &countingLLM{response: "This should not run when blunder_abort is true."}
	graph := newGraphForTest(t, &blunderEngine{MockEngine: &engine.MockEngine{}}, llm.Models{
		Analysis:      coachLLM,
		Orchestration: &countingLLM{response: "BLUNDER_CHECK"},
	})

	ctx := newGraphContext(map[string]interface{}{
		"fen":                    testGraphFEN,
		"question":               "Was b0c2 a mistake?",
		"move":                   "b0c2",
		"has_move":               true,
		"moves_since_last_coach": 3,
	})

	if err := graph.Run(ctx); err != nil {
		t.Fatalf("graph run: %v", err)
	}

	feedback, _ := ctx.State["feedback"].(string)
	if !strings.Contains(feedback, "BLUNDER DETECTED") {
		t.Fatalf("feedback should contain blunder summary: %q", feedback)
	}
	if strings.Contains(feedback, "Coaching advice [") {
		t.Fatalf("blunder abort path should skip coaching advice: %q", feedback)
	}
	if abort, _ := ctx.State["blunder_abort"].(bool); !abort {
		t.Fatalf("blunder_abort should be true")
	}
	if coachLLM.calls != 0 {
		t.Fatalf("coach LLM should not run on blunder abort path, got %d calls", coachLLM.calls)
	}
	if _, ok := ctx.State["puzzle"].(map[string]interface{}); !ok {
		t.Fatalf("puzzle_curator should still generate a follow-up puzzle on blunder abort")
	}
}

func TestBuildGraphOpeningPathUsesRAGWhenImplemented(t *testing.T) {
	t.Skip("Pending: position_analyst/coach do not yet invoke get_opening_plan in the live graph")
}

func TestBuildGraphQuestionOnlyPathUsesGeneralAdviceRAGWhenImplemented(t *testing.T) {
	t.Skip("Pending: coach does not yet invoke get_general_advice in the live graph")
}
