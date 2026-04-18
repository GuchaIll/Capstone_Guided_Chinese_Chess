package chesstools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"go_agent_framework/core"
)

// LoadPGNTool parses PGN text and extracts game metadata and moves.
type LoadPGNTool struct{}

func (t *LoadPGNTool) Name() string        { return "load_pgn" }
func (t *LoadPGNTool) Description() string { return "Parse PGN text and extract game metadata and move list." }
func (t *LoadPGNTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "pgn", Type: "string", Description: "PGN text to parse", Required: true},
	}
}

func (t *LoadPGNTool) Execute(_ context.Context, args json.RawMessage) (string, error) {
	var p struct {
		PGN string `json:"pgn"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("load_pgn: %w", err)
	}

	headers, moves := parsePGN(p.PGN)
	out, _ := json.Marshal(map[string]interface{}{
		"headers":     headers,
		"moves":       moves,
		"total_moves": len(moves),
	})
	return string(out), nil
}

// SavePGNTool serializes game data into PGN format.
type SavePGNTool struct{}

func (t *SavePGNTool) Name() string        { return "save_pgn" }
func (t *SavePGNTool) Description() string { return "Serialize game metadata and moves into PGN format." }
func (t *SavePGNTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "white", Type: "string", Description: "White player name", Required: false},
		{Name: "black", Type: "string", Description: "Black player name", Required: false},
		{Name: "result", Type: "string", Description: "Game result (1-0, 0-1, 1/2-1/2, *)", Required: false},
		{Name: "moves", Type: "string", Description: "Space-separated move list in algebraic notation", Required: true},
	}
}

func (t *SavePGNTool) Execute(_ context.Context, args json.RawMessage) (string, error) {
	var p struct {
		White  string `json:"white"`
		Black  string `json:"black"`
		Result string `json:"result"`
		Moves  string `json:"moves"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("save_pgn: %w", err)
	}
	if p.White == "" {
		p.White = "?"
	}
	if p.Black == "" {
		p.Black = "?"
	}
	if p.Result == "" {
		p.Result = "*"
	}

	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("[White \"%s\"]\n", p.White))
	sb.WriteString(fmt.Sprintf("[Black \"%s\"]\n", p.Black))
	sb.WriteString(fmt.Sprintf("[Result \"%s\"]\n\n", p.Result))

	moves := strings.Fields(p.Moves)
	for i, mv := range moves {
		if i%2 == 0 {
			sb.WriteString(fmt.Sprintf("%d. ", i/2+1))
		}
		sb.WriteString(mv + " ")
	}
	sb.WriteString(p.Result)

	out, _ := json.Marshal(map[string]interface{}{
		"pgn": sb.String(),
	})
	return string(out), nil
}

// parsePGN is a simple PGN parser that extracts headers and move list.
func parsePGN(pgn string) (map[string]string, []string) {
	headers := make(map[string]string)
	var moveText strings.Builder

	lines := strings.Split(pgn, "\n")
	inMoves := false

	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			if len(headers) > 0 {
				inMoves = true
			}
			continue
		}
		if !inMoves && strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
			// Parse header: [Key "Value"]
			inner := strings.TrimPrefix(line, "[")
			inner = strings.TrimSuffix(inner, "]")
			parts := strings.SplitN(inner, " ", 2)
			if len(parts) == 2 {
				key := parts[0]
				val := strings.Trim(parts[1], "\"")
				headers[key] = val
			}
			continue
		}
		inMoves = true
		moveText.WriteString(line + " ")
	}

	// Extract moves from move text, removing move numbers and result.
	raw := moveText.String()
	// Remove move numbers (e.g. "1." "12.")
	var moves []string
	for _, token := range strings.Fields(raw) {
		// Skip move numbers like "1." or "12."
		if strings.HasSuffix(token, ".") {
			continue
		}
		// Skip results
		if token == "1-0" || token == "0-1" || token == "1/2-1/2" || token == "*" {
			continue
		}
		// Skip move number prefix like "1..."
		if strings.Contains(token, "...") {
			continue
		}
		if token != "" {
			moves = append(moves, token)
		}
	}

	return headers, moves
}

// RegisterPGNTools registers PGN parsing and serialization tools.
func RegisterPGNTools(reg *core.ToolRegistry) error {
	for _, t := range []core.Tool{
		&LoadPGNTool{},
		&SavePGNTool{},
	} {
		if err := reg.Register(t); err != nil {
			return err
		}
	}
	return nil
}
