package chesstools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"go_agent_framework/core"
)

// VisualizeBoardTool renders a FEN position as ASCII art.
type VisualizeBoardTool struct{}

func (t *VisualizeBoardTool) Name() string        { return "visualize_board" }
func (t *VisualizeBoardTool) Description() string { return "Render a FEN position as an ASCII board diagram." }
func (t *VisualizeBoardTool) Parameters() []core.ToolParameter {
	return []core.ToolParameter{
		{Name: "fen", Type: "string", Description: "FEN position string to visualize", Required: true},
	}
}

func (t *VisualizeBoardTool) Execute(_ context.Context, args json.RawMessage) (string, error) {
	var p struct {
		FEN string `json:"fen"`
	}
	if err := json.Unmarshal(args, &p); err != nil {
		return "", fmt.Errorf("visualize_board: %w", err)
	}

	board := renderASCII(p.FEN)
	out, _ := json.Marshal(map[string]interface{}{
		"fen":   p.FEN,
		"board": board,
	})
	return string(out), nil
}

// renderASCII converts a FEN string to an ASCII board representation.
func renderASCII(fen string) string {
	parts := strings.SplitN(fen, " ", 2)
	ranks := strings.Split(parts[0], "/")

	var sb strings.Builder
	sb.WriteString("  a b c d e f g h\n")
	for i, rank := range ranks {
		rankNum := 8 - i
		sb.WriteString(fmt.Sprintf("%d ", rankNum))
		for _, ch := range rank {
			if ch >= '1' && ch <= '9' {
				count := int(ch - '0')
				for j := 0; j < count; j++ {
					sb.WriteString(". ")
				}
			} else {
				sb.WriteString(fmt.Sprintf("%c ", ch))
			}
		}
		sb.WriteString(fmt.Sprintf("%d\n", rankNum))
	}
	sb.WriteString("  a b c d e f g h\n")
	return sb.String()
}

// RegisterVisualizationTools registers board visualization tools.
func RegisterVisualizationTools(reg *core.ToolRegistry) error {
	return reg.Register(&VisualizeBoardTool{})
}
