package agents

import (
	"encoding/json"
	"fmt"
	"regexp"

	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// guardMovePattern matches Xiangqi algebraic moves embedded in coaching text (e.g. "e3e5").
var guardMovePattern = regexp.MustCompile(`\b[a-i][0-9][a-i][0-9]\b`)

// GuardAgent is a scoring gate that runs after CoachAgent on the slow path.
// It verifies that every move referenced in the coaching advice is legal,
// then approves or rejects the advice before it reaches Feedback.
type GuardAgent struct {
	Tools *core.ToolRegistry
}

func (a *GuardAgent) Name() string { return "guard" }
func (a *GuardAgent) Description() string {
	return "Scores coaching advice: approves if all referenced moves are legal, rejects otherwise."
}
func (a *GuardAgent) Capabilities() core.AgentCapabilities {
	return core.AgentCapabilities{Tools: []string{"is_move_legal", "get_legal_moves"}}
}

func (a *GuardAgent) Run(ctx *core.Context) error {
	if abort, _ := ctx.State["blunder_abort"].(bool); abort {
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Blunder abort active, skipping guard.")
		return nil
	}
	advice, _ := ctx.State["coaching_advice"].(string)
	if advice == "" {
		// Coach did not run (fast path) — nothing to score.
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "No coaching advice present, skipping guard.")
		return nil
	}

	fen, _ := ctx.State["fen"].(string)

	// Fetch the full set of legal moves for this position.
	legalMoves, err := a.fetchLegalMoves(ctx, fen)
	if err != nil {
		// Non-fatal: if we cannot reach the engine, approve by default.
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
			fmt.Sprintf("Could not fetch legal moves (%v) — approving advice by default.", err))
		ctx.State["coach_advice_approved"] = true
		return nil
	}

	// Check every move string found in the advice text.
	mentioned := guardMovePattern.FindAllString(advice, -1)
	reason, ok := a.checkMoves(ctx, fen, mentioned, legalMoves)
	if !ok {
		ctx.State["coach_advice_approved"] = false
		ctx.State["coach_abort_reason"] = reason
		ctx.State["coaching_advice"] = ""
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
			fmt.Sprintf("Advice rejected: %s", reason))
		ctx.Logger.Info("guard: advice rejected", "reason", reason)
		return nil
	}

	ctx.State["coach_advice_approved"] = true
	ctx.State["move_legal"] = true
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID,
		fmt.Sprintf("Advice approved — %d move(s) verified.", len(mentioned)))
	ctx.Logger.Info("guard: advice approved", "moves_checked", len(mentioned))
	return nil
}

func (a *GuardAgent) fetchLegalMoves(ctx *core.Context, fen string) (map[string]bool, error) {
	args, _ := json.Marshal(map[string]string{"fen": fen})
	call := core.ToolCall{ID: "guard_legal_1", Name: "get_legal_moves", Args: args}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, call.Name, map[string]string{"fen": fen})

	result := a.Tools.ExecuteTool(ctx.StdContext, call)
	if result.Error != "" {
		return nil, fmt.Errorf("get_legal_moves: %s", result.Error)
	}

	var out struct {
		Moves []string `json:"moves"`
	}
	if err := json.Unmarshal([]byte(result.Output), &out); err != nil {
		return nil, fmt.Errorf("parse legal moves: %w", err)
	}

	legal := make(map[string]bool, len(out.Moves))
	for _, m := range out.Moves {
		legal[m] = true
	}
	return legal, nil
}

// checkMoves verifies each move string found in the advice. Returns (reason, ok).
func (a *GuardAgent) checkMoves(ctx *core.Context, fen string, moves []string, legal map[string]bool) (string, bool) {
	if len(moves) == 0 {
		return "no candidate move found in advice text", false
	}
	for _, mv := range moves {
		if legal[mv] {
			continue
		}
		// Not in pre-fetched list — do a direct legality check as fallback.
		if !a.isMoveLegal(ctx, fen, mv) {
			return fmt.Sprintf("move %q in advice is illegal", mv), false
		}
	}
	return "", true
}

func (a *GuardAgent) isMoveLegal(ctx *core.Context, fen, move string) bool {
	args, _ := json.Marshal(map[string]string{"fen": fen, "move": move})
	call := core.ToolCall{ID: "guard_check_" + move, Name: "is_move_legal", Args: args}
	observability.PublishToolCall(ctx.GraphName, a.Name(), ctx.SessionID, call.Name,
		map[string]string{"fen": fen, "move": move})

	result := a.Tools.ExecuteTool(ctx.StdContext, call)
	if result.Error != "" {
		return false
	}
	var out struct {
		Legal bool `json:"legal"`
	}
	_ = json.Unmarshal([]byte(result.Output), &out)
	return out.Legal
}
