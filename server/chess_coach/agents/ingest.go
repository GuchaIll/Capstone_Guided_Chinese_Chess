package agents

import (
	"fmt"
	"go_agent_framework/core"
	"go_agent_framework/observability"
	"regexp"
	"strings"
)

// fenPattern matches a FEN-like string: rows of pieces/digits separated by /,
// followed by side-to-move. Works for both standard chess and xiangqi FEN.
var fenPattern = regexp.MustCompile(`([A-Za-z0-9]+/){2,}[A-Za-z0-9]+\s+[wb][^\n]*`)

// movePattern matches common chess move notations (UCI like e2e4 or algebraic like Nf3, O-O).
var movePattern = regexp.MustCompile(`\b([a-h][1-8][a-h][1-8][qrbn]?|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|O-O(?:-O)?)\b`)

// IngestAgent reads the raw user input (FEN, move, question) from State
// and normalises it for downstream agents. It handles both structured
// input (separate fen/move/question fields) and natural-language input
// (a chat message from which FEN and move are extracted).
type IngestAgent struct{}

func (a *IngestAgent) Name() string        { return "ingest" }
func (a *IngestAgent) Description() string { return "Reads FEN, move, and question from input and sets routing flags." }
func (a *IngestAgent) Capabilities() core.AgentCapabilities { return core.AgentCapabilities{} }

func (a *IngestAgent) Run(ctx *core.Context) error {
	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Parsing user input: extracting FEN, move, and question fields.")

	fen, _ := ctx.State["fen"].(string)
	move, _ := ctx.State["move"].(string)
	question, _ := ctx.State["question"].(string)

	// If the fen field looks like natural language (contains spaces before any
	// slash-separated groups), try to extract a proper FEN from it.
	if fen != "" && !looksLikeFEN(fen) {
		raw := fen
		observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, "Input appears to be natural language, extracting FEN pattern.")

		if found := fenPattern.FindString(raw); found != "" {
			fen = strings.TrimSpace(found)
			// Whatever is not the FEN is the question.
			remaining := strings.Replace(raw, found, "", 1)
			remaining = strings.TrimSpace(remaining)
			if remaining != "" && (question == "" || question == raw) {
				question = remaining
			}
		}

		// Try to extract a move from the remaining text.
		if move == "" {
			if m := movePattern.FindString(question); m != "" {
				move = m
			}
		}

		ctx.State["fen"] = fen
		ctx.State["move"] = move
		ctx.State["question"] = question
	}

	// If no FEN was found anywhere, treat this as a question-only message.
	questionOnly := fen == ""
	if questionOnly && question == "" {
		return fmt.Errorf("ingest: both fen and question are empty")
	}

	ctx.State["question_only"] = questionOnly
	ctx.State["is_question"] = question != ""
	ctx.State["has_move"] = move != ""

	observability.PublishThought(ctx.GraphName, a.Name(), ctx.SessionID, fmt.Sprintf("Input parsed: FEN=%q, move=%q, is_question=%v, question_only=%v", fen, move, question != "", questionOnly))
	ctx.Logger.Info("ingest complete", "fen", fen, "move", move, "has_move", move != "", "is_question", question != "", "question_only", questionOnly)
	return nil
}

// looksLikeFEN returns true when the string starts with a FEN piece-placement
// section (slash-separated rows of piece characters and digits).
func looksLikeFEN(s string) bool {
	s = strings.TrimSpace(s)
	if s == "" {
		return false
	}
	// A real FEN starts with piece rows like "rnbqkbnr/pppppppp/..."
	// Check first token contains a slash before any space.
	spaceIdx := strings.IndexByte(s, ' ')
	slashIdx := strings.IndexByte(s, '/')
	return slashIdx > 0 && (spaceIdx < 0 || slashIdx < spaceIdx)
}
