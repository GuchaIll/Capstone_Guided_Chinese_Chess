package agents

import (
	"context"
	"io"
	"log/slog"
	"testing"

	"chess_coach/engine"
	chesstools "chess_coach/tools"
	"go_agent_framework/core"
)

func newTestContext(state map[string]interface{}) *core.Context {
	if state == nil {
		state = make(map[string]interface{})
	}
	return &core.Context{
		SessionID:  "test-session",
		GraphName:  "test-graph",
		State:      state,
		Logger:     slog.New(slog.NewTextHandler(io.Discard, nil)),
		StdContext: context.Background(),
	}
}

func newTestToolRegistry(t *testing.T, eng engine.EngineClient) *core.ToolRegistry {
	t.Helper()
	reg := core.NewToolRegistry()
	if err := chesstools.RegisterChessTools(reg, eng); err != nil {
		t.Fatalf("register chess tools: %v", err)
	}
	if err := chesstools.RegisterPuzzleDetectorTools(reg, eng); err != nil {
		t.Fatalf("register puzzle detector tools: %v", err)
	}
	return reg
}

func newTestSkillRegistry(t *testing.T) *core.SkillRegistry {
	t.Helper()
	reg := core.NewSkillRegistry()
	if err := reg.Register(&core.Skill{
		Name:        "beginner_coaching",
		Description: "Keep answers concise and beginner friendly.",
		Steps:       []core.SkillStep{{Name: "format_advice", Kind: core.KindLLM}},
	}); err != nil {
		t.Fatalf("register beginner skill: %v", err)
	}
	return reg
}

