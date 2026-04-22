package engine

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// BridgeClient implements EngineClient by calling the state-bridge REST API.
// Use when the coaching service runs inside Docker alongside the state bridge.
type BridgeClient struct {
	baseURL string
	http    *http.Client
}

// NewBridgeClient creates a BridgeClient pointing at the given base URL,
// e.g. "http://state-bridge:5003".
func NewBridgeClient(baseURL string) *BridgeClient {
	return &BridgeClient{
		baseURL: baseURL,
		http:    &http.Client{Timeout: 30 * time.Second},
	}
}

// post sends a JSON POST to path and decodes the response into out.
func (c *BridgeClient) post(ctx context.Context, path string, body interface{}, out interface{}) error {
	b, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("bridge marshal: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, bytes.NewReader(b))
	if err != nil {
		return fmt.Errorf("bridge request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("bridge %s: %w", path, err)
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("bridge read: %w", err)
	}
	if resp.StatusCode >= 400 {
		return fmt.Errorf("bridge %s: HTTP %d: %s", path, resp.StatusCode, string(data))
	}
	if out != nil {
		if err := json.Unmarshal(data, out); err != nil {
			return fmt.Errorf("bridge decode: %w", err)
		}
	}
	return nil
}

func (c *BridgeClient) ValidateFEN(ctx context.Context, fen string) (bool, error) {
	var out struct {
		Valid bool `json:"valid"`
	}
	if err := c.post(ctx, "/engine/validate-fen", map[string]string{"fen": fen}, &out); err != nil {
		return false, err
	}
	return out.Valid, nil
}

func (c *BridgeClient) Analyze(ctx context.Context, fen string, depth int) (map[string]interface{}, error) {
	var out map[string]interface{}
	if err := c.post(ctx, "/engine/analyze", map[string]interface{}{"fen": fen, "depth": depth}, &out); err != nil {
		return nil, err
	}
	return out, nil
}

func (c *BridgeClient) IsMoveLegal(ctx context.Context, fen string, move string) (bool, error) {
	var out struct {
		Legal bool `json:"legal"`
	}
	if err := c.post(ctx, "/engine/is-move-legal", map[string]string{"fen": fen, "move": move}, &out); err != nil {
		return false, err
	}
	return out.Legal, nil
}

func (c *BridgeClient) LegalMoves(ctx context.Context, fen string) ([]string, error) {
	var out struct {
		Moves []string `json:"moves"`
	}
	if err := c.post(ctx, "/engine/legal-moves", map[string]string{"fen": fen}, &out); err != nil {
		return nil, err
	}
	return out.Moves, nil
}

func (c *BridgeClient) GetState(ctx context.Context) (map[string]interface{}, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+"/state", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return out, nil
}

func (c *BridgeClient) MakeMove(ctx context.Context, fen string, move string) (map[string]interface{}, error) {
	var out map[string]interface{}
	if err := c.post(ctx, "/engine/make-move", map[string]string{"fen": fen, "move": move}, &out); err != nil {
		return nil, err
	}
	return out, nil
}

func (c *BridgeClient) AnalyzePositionFull(ctx context.Context, fen string, depth int) (*AnalysisResponse, error) {
	raw, err := c.Analyze(ctx, fen, depth)
	if err != nil {
		return nil, err
	}
	// Re-marshal and decode into typed struct.
	b, _ := json.Marshal(raw)
	var out AnalysisResponse
	if err := json.Unmarshal(b, &out); err != nil {
		// Fallback: populate what we can from the raw map.
		if score, ok := raw["score"].(float64); ok {
			out.SearchScore = int(score)
		}
	}
	return &out, nil
}

func (c *BridgeClient) BatchAnalyze(ctx context.Context, entries []BatchEntry) ([]MoveFeatureVector, error) {
	type batchReq struct {
		Moves []map[string]string `json:"moves"`
	}
	moves := make([]map[string]string, len(entries))
	for i, e := range entries {
		moves[i] = map[string]string{"fen": e.FEN, "move_str": e.MoveStr}
	}
	var out []MoveFeatureVector
	if err := c.post(ctx, "/engine/batch-analyze", batchReq{Moves: moves}, &out); err != nil {
		return nil, err
	}
	return out, nil
}

func (c *BridgeClient) Suggest(ctx context.Context, fen string, depth int) (string, int, error) {
	var out struct {
		Move  string `json:"move"`
		Score int    `json:"score"`
	}
	if err := c.post(ctx, "/engine/suggest", map[string]interface{}{"fen": fen, "depth": depth}, &out); err != nil {
		return "", 0, err
	}
	return out.Move, out.Score, nil
}

func (c *BridgeClient) DetectPuzzle(ctx context.Context, fen string, depth int) (*PuzzleDetectionResult, error) {
	var out PuzzleDetectionResult
	if err := c.post(ctx, "/engine/puzzle-detect", map[string]interface{}{"fen": fen, "depth": depth}, &out); err != nil {
		return nil, err
	}
	return &out, nil
}
