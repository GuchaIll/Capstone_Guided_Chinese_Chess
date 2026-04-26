package agents

import (
	"context"
	"strings"
	"testing"

	"chess_coach/engine"
	"go_agent_framework/contrib/llm"
)

const testXiangqiFEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"

type rejectingEngine struct {
	*engine.MockEngine
}

func (e *rejectingEngine) IsMoveLegal(_ context.Context, _, _ string) (bool, error) {
	return false, nil
}

type hangingPieceEngine struct {
	*engine.MockEngine
}

type fixedLLM struct {
	response string
}

func (f *fixedLLM) Generate(_ context.Context, _ string) (string, error) {
	return f.response, nil
}

func (e *hangingPieceEngine) AnalyzePositionFull(_ context.Context, fen string, _ int) (*engine.AnalysisResponse, error) {
	resp, _ := e.MockEngine.AnalyzePositionFull(context.Background(), fen, 10)
	resp.PositionAnalysis.HangingPieces = []engine.HangingPiece{
		{PieceType: "rook", Side: "red", Square: "h0", Value: 900, AttackedBy: []string{"black_cannon"}},
	}
	return resp, nil
}

func TestIngestAgentExtractsFenMoveAndQuestion(t *testing.T) {
	raw := "Why is b0c2 strong here? " + testXiangqiFEN
	ctx := newTestContext(map[string]interface{}{
		"fen": raw,
	})

	if err := (&IngestAgent{}).Run(ctx); err != nil {
		t.Fatalf("ingest run: %v", err)
	}

	if got := ctx.State["fen"]; got != testXiangqiFEN {
		t.Fatalf("fen mismatch: got %v", got)
	}
	if got := ctx.State["move"]; got != "b0c2" {
		t.Fatalf("move mismatch: got %v", got)
	}
	if got := ctx.State["question"]; got != "Why is b0c2 strong here?" {
		t.Fatalf("question mismatch: got %v", got)
	}
	if got := ctx.State["question_only"]; got != false {
		t.Fatalf("question_only mismatch: got %v", got)
	}
}

func TestOrchestratorSetsRoutesAndCoachTrigger(t *testing.T) {
	ctx := newTestContext(map[string]interface{}{
		"fen":                    testXiangqiFEN,
		"question":               "Please explain this move",
		"has_move":               true,
		"move":                   "b0c2",
		"moves_since_last_coach": 3,
	})

	agent := &OrchestratorAgent{
		LLM: &llm.MockLLM{Response: "EXPLAIN"},
	}
	if err := agent.Run(ctx); err != nil {
		t.Fatalf("orchestrator run: %v", err)
	}

	if got := ctx.State["route_blunder_detection"]; got != true {
		t.Fatalf("route_blunder_detection mismatch: got %v", got)
	}
	if got := ctx.State["route_position_analysis"]; got != true {
		t.Fatalf("route_position_analysis mismatch: got %v", got)
	}
	if got := ctx.State["coach_trigger"]; got != "explicit" {
		t.Fatalf("coach_trigger mismatch: got %v", got)
	}
	if got := ctx.State["classified_intent"]; got != "EXPLAIN" {
		t.Fatalf("classified_intent mismatch: got %v", got)
	}
}

func TestPositionAnalystStoresMetricsAndPrincipalVariation(t *testing.T) {
	ctx := newTestContext(map[string]interface{}{
		"fen":                     testXiangqiFEN,
		"route_position_analysis": true,
		"coach_trigger":           "none",
	})
	reg := newTestToolRegistry(t, &engine.MockEngine{})

	agent := &PositionAnalystAgent{Tools: reg, Depth: 4}
	if err := agent.Run(ctx); err != nil {
		t.Fatalf("position analyst run: %v", err)
	}

	if _, ok := ctx.State["engine_metrics"].(map[string]interface{}); !ok {
		t.Fatalf("engine_metrics missing or wrong type: %#v", ctx.State["engine_metrics"])
	}
	if got := ctx.State["game_phase"]; got != "opening" {
		t.Fatalf("game_phase mismatch: got %v", got)
	}
	if _, ok := ctx.State["principal_variation"].(map[string]interface{}); !ok {
		t.Fatalf("principal_variation missing or wrong type: %#v", ctx.State["principal_variation"])
	}
}

func TestCoachAgentBuildsAdviceFromAnalysisState(t *testing.T) {
	ctx := newTestContext(map[string]interface{}{
		"fen":           testXiangqiFEN,
		"question":      "What should Red focus on?",
		"coach_trigger": "explicit",
		"engine_metrics": map[string]interface{}{
			"search_score": 35,
			"move_features": map[string]interface{}{
				"move_metadata": map[string]interface{}{"move_str": "b0c2"},
				"search_metrics": map[string]interface{}{
					"principal_variation": []interface{}{"b0c2", "h7e7"},
				},
			},
		},
		"game_phase": "opening",
	})

	agent := &CoachAgent{
		LLM:    &fixedLLM{response: "Develop your red knight to pressure the center."},
		Skills: newTestSkillRegistry(t),
	}
	if err := agent.Run(ctx); err != nil {
		t.Fatalf("coach run: %v", err)
	}

	advice, _ := ctx.State["coaching_advice"].(string)
	if !strings.Contains(advice, "red knight") {
		t.Fatalf("unexpected coaching advice: %q", advice)
	}
}

func TestCoachAgentUsesDynamicFallbackWhenMockLLMIsActive(t *testing.T) {
	ctx := newTestContext(map[string]interface{}{
		"fen":           testXiangqiFEN,
		"question":      "Comment on this move.",
		"move":          "b0c2",
		"coach_trigger": "explicit",
		"engine_metrics": map[string]interface{}{
			"search_score": 200,
			"move_features": map[string]interface{}{
				"move_metadata": map[string]interface{}{"move_str": "e6e5"},
			},
		},
		"hanging_pieces": []interface{}{map[string]interface{}{"square": "h0"}},
		"rag_context": map[string]interface{}{
			"opening": map[string]interface{}{"text": "Control the center before launching an attack."},
		},
	})

	agent := &CoachAgent{
		LLM:    &llm.MockLLM{Response: "generic mock response"},
		Skills: newTestSkillRegistry(t),
	}
	if err := agent.Run(ctx); err != nil {
		t.Fatalf("coach run: %v", err)
	}

	advice, _ := ctx.State["coaching_advice"].(string)
	if !strings.Contains(advice, "200") {
		t.Fatalf("fallback advice should include engine score context: %q", advice)
	}
	if !strings.Contains(advice, "e6e5") {
		t.Fatalf("fallback advice should include best move: %q", advice)
	}
	if !strings.Contains(advice, "hanging") {
		t.Fatalf("fallback advice should include tactical warning: %q", advice)
	}
}

func TestBlunderDetectionAgentSynthesizesFallbackFromHangingPiece(t *testing.T) {
	ctx := newTestContext(map[string]interface{}{
		"fen":                     testXiangqiFEN,
		"move":                    "b0c2",
		"has_move":                true,
		"route_blunder_detection": true,
		"coach_trigger":           "none",
	})
	reg := newTestToolRegistry(t, &hangingPieceEngine{MockEngine: &engine.MockEngine{}})

	agent := &BlunderDetectionAgent{Tools: reg}
	if err := agent.Run(ctx); err != nil {
		t.Fatalf("blunder detection run: %v", err)
	}

	if got := ctx.State["blunder_abort"]; got != true {
		t.Fatalf("expected fallback blunder_abort=true, got %v", got)
	}
	if got := ctx.State["route_puzzle"]; got != true {
		t.Fatalf("expected puzzle to be routed after fallback blunder, got %v", got)
	}
	if got := ctx.State["coach_trigger"]; got != "tactical_pattern" {
		t.Fatalf("expected tactical_pattern coach trigger, got %v", got)
	}
	blunderData, _ := ctx.State["blunder_analysis"].(map[string]interface{})
	blunders, _ := blunderData["blunders"].([]interface{})
	if len(blunders) == 0 {
		t.Fatalf("expected synthesized blunder entry, got %#v", blunderData)
	}
}

func TestGuardAgentRejectsIllegalAdviceMoves(t *testing.T) {
	ctx := newTestContext(map[string]interface{}{
		"fen":             testXiangqiFEN,
		"coaching_advice": "Play b0c2 immediately to activate the knight.",
	})
	reg := newTestToolRegistry(t, &rejectingEngine{MockEngine: &engine.MockEngine{}})

	agent := &GuardAgent{Tools: reg}
	if err := agent.Run(ctx); err != nil {
		t.Fatalf("guard run: %v", err)
	}

	if got := ctx.State["coach_advice_approved"]; got != false {
		t.Fatalf("coach_advice_approved mismatch: got %v", got)
	}
	if got := ctx.State["coaching_advice"]; got != "" {
		t.Fatalf("coaching_advice should be cleared, got %v", got)
	}
}

func TestFeedbackAgentComposesExplanationPath(t *testing.T) {
	ctx := newTestContext(map[string]interface{}{
		"engine_metrics": map[string]interface{}{
			"search_score": 35,
			"move_features": map[string]interface{}{
				"move_metadata": map[string]interface{}{"move_str": "b0c2"},
			},
		},
		"principal_variation": map[string]interface{}{
			"pv": []interface{}{"b0c2", "h7e7"},
		},
		"coaching_advice":       "Improve central control before launching tactics.",
		"coach_advice_approved": true,
		"coach_trigger":         "move_count",
	})

	if err := (&FeedbackAgent{}).Run(ctx); err != nil {
		t.Fatalf("feedback run: %v", err)
	}

	feedback, _ := ctx.State["feedback"].(string)
	if !strings.Contains(feedback, "Evaluation: 35") {
		t.Fatalf("feedback missing evaluation: %q", feedback)
	}
	if !strings.Contains(feedback, "Best move: b0c2") {
		t.Fatalf("feedback missing best move: %q", feedback)
	}
	if !strings.Contains(feedback, "Coaching advice [move_count]") {
		t.Fatalf("feedback missing coaching section: %q", feedback)
	}
}

func TestFeedbackAgentTruncatesCoachingAdviceTo320Words(t *testing.T) {
	longAdvice := strings.Repeat("careful centralization ", 120)
	ctx := newTestContext(map[string]interface{}{
		"coaching_advice":       longAdvice,
		"coach_advice_approved": true,
		"coach_trigger":         "explicit",
	})

	if err := (&FeedbackAgent{}).Run(ctx); err != nil {
		t.Fatalf("feedback run: %v", err)
	}

	feedback, _ := ctx.State["feedback"].(string)
	parts := strings.SplitN(feedback, "\n", 3)
	if len(parts) < 2 {
		t.Fatalf("unexpected feedback format: %q", feedback)
	}
	adviceLine := parts[len(parts)-1]
	if got := len(strings.Fields(adviceLine)); got > 320 {
		t.Fatalf("coaching advice should be capped at 320 words, got %d: %q", got, adviceLine)
	}
}
