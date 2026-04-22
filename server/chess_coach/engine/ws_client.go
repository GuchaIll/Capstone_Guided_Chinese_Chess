package engine

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// WSClient implements EngineClient by communicating with the Rust engine over WebSocket.
type WSClient struct {
	url  string
	conn *websocket.Conn
	mu   sync.Mutex

	// reconnect settings
	maxRetries int
	baseDelay  time.Duration
	connected  bool
}

// NewWSClient creates a new WebSocket engine client.
// url defaults to ENGINE_WS_URL env var or ws://localhost:8080/ws.
func NewWSClient(url string) *WSClient {
	if url == "" {
		url = os.Getenv("ENGINE_WS_URL")
	}
	if url == "" {
		url = "ws://localhost:8080/ws"
	}
	return &WSClient{
		url:        url,
		maxRetries: 5,
		baseDelay:  500 * time.Millisecond,
	}
}

// Connect establishes the WebSocket connection with retries.
func (c *WSClient) Connect() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	var err error
	delay := c.baseDelay
	for i := 0; i <= c.maxRetries; i++ {
		c.conn, _, err = websocket.DefaultDialer.Dial(c.url, nil)
		if err == nil {
			c.connected = true
			log.Printf("[WSClient] Connected to engine at %s", c.url)
			return nil
		}
		if i < c.maxRetries {
			log.Printf("[WSClient] Connection attempt %d failed: %v, retrying in %v", i+1, err, delay)
			time.Sleep(delay)
			delay *= 2
		}
	}
	return fmt.Errorf("ws_client: failed to connect after %d attempts: %w", c.maxRetries+1, err)
}

// Close closes the WebSocket connection.
func (c *WSClient) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.connected = false
	if c.conn != nil {
		return c.conn.Close()
	}
	return nil
}

// reconnect attempts to re-establish the connection.
func (c *WSClient) reconnect() error {
	if c.conn != nil {
		c.conn.Close()
	}
	c.connected = false

	var err error
	delay := c.baseDelay
	for i := 0; i <= c.maxRetries; i++ {
		c.conn, _, err = websocket.DefaultDialer.Dial(c.url, nil)
		if err == nil {
			c.connected = true
			log.Printf("[WSClient] Reconnected to engine")
			return nil
		}
		if i < c.maxRetries {
			time.Sleep(delay)
			delay *= 2
		}
	}
	return fmt.Errorf("ws_client: reconnect failed: %w", err)
}

// sendAndReceive sends a JSON message and reads the typed response.
func (c *WSClient) sendAndReceive(msg interface{}) (json.RawMessage, error) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if !c.connected {
		if err := c.reconnect(); err != nil {
			return nil, err
		}
	}

	if err := c.conn.WriteJSON(msg); err != nil {
		// Try reconnect once on write failure.
		if reconnErr := c.reconnect(); reconnErr != nil {
			return nil, fmt.Errorf("ws_client: write failed and reconnect failed: %w", err)
		}
		if err := c.conn.WriteJSON(msg); err != nil {
			return nil, fmt.Errorf("ws_client: write failed after reconnect: %w", err)
		}
	}

	_, raw, err := c.conn.ReadMessage()
	if err != nil {
		return nil, fmt.Errorf("ws_client: read failed: %w", err)
	}
	return json.RawMessage(raw), nil
}

// ── EngineClient interface methods ──

func (c *WSClient) ValidateFEN(ctx context.Context, fen string) (bool, error) {
	// The engine validates via set_position; a successful state response means valid.
	raw, err := c.sendAndReceive(map[string]interface{}{
		"type": "set_position",
		"fen":  fen,
	})
	if err != nil {
		return false, err
	}
	var resp struct {
		Type    string `json:"type"`
		Message string `json:"message"`
	}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return false, err
	}
	return resp.Type != "error", nil
}

func (c *WSClient) Analyze(ctx context.Context, fen string, depth int) (map[string]interface{}, error) {
	raw, err := c.sendAndReceive(map[string]interface{}{
		"type":       "analyze_position",
		"fen":        fen,
		"difficulty": depth,
	})
	if err != nil {
		return nil, err
	}
	var resp map[string]interface{}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return nil, err
	}
	if t, _ := resp["type"].(string); t == "error" {
		msg, _ := resp["message"].(string)
		return nil, fmt.Errorf("engine error: %s", msg)
	}
	return resp, nil
}

func (c *WSClient) IsMoveLegal(ctx context.Context, fen string, move string) (bool, error) {
	// Set position, get legal moves for the from-square, check if to-square is in targets.
	if _, err := c.sendAndReceive(map[string]interface{}{
		"type": "set_position",
		"fen":  fen,
	}); err != nil {
		return false, err
	}

	if len(move) < 4 {
		return false, fmt.Errorf("invalid move format: %s", move)
	}
	fromSquare := move[:2]
	toSquare := move[2:]

	raw, err := c.sendAndReceive(map[string]interface{}{
		"type":   "legal_moves",
		"square": fromSquare,
	})
	if err != nil {
		return false, err
	}

	var resp struct {
		Type    string   `json:"type"`
		Targets []string `json:"targets"`
	}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return false, err
	}
	for _, t := range resp.Targets {
		if t == toSquare {
			return true, nil
		}
	}
	return false, nil
}

func (c *WSClient) LegalMoves(ctx context.Context, fen string) ([]string, error) {
	// Set position first, then query legal_moves for each occupied square.
	// More efficient: use the engine's get_state or iterate known squares.
	// For now, we collect legal moves by querying a-i × 0-9.
	if _, err := c.sendAndReceive(map[string]interface{}{
		"type": "set_position",
		"fen":  fen,
	}); err != nil {
		return nil, err
	}

	var allMoves []string
	files := "abcdefghi"
	for _, f := range files {
		for r := 0; r <= 9; r++ {
			sq := fmt.Sprintf("%c%d", f, r)
			raw, err := c.sendAndReceive(map[string]interface{}{
				"type":   "legal_moves",
				"square": sq,
			})
			if err != nil {
				continue
			}
			var resp struct {
				Type    string   `json:"type"`
				Targets []string `json:"targets"`
			}
			if err := json.Unmarshal(raw, &resp); err != nil {
				continue
			}
			for _, t := range resp.Targets {
				allMoves = append(allMoves, sq+t)
			}
		}
	}
	return allMoves, nil
}

func (c *WSClient) GetState(ctx context.Context) (map[string]interface{}, error) {
	raw, err := c.sendAndReceive(map[string]interface{}{
		"type": "get_state",
	})
	if err != nil {
		return nil, err
	}
	var resp map[string]interface{}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return nil, err
	}
	return resp, nil
}

func (c *WSClient) MakeMove(ctx context.Context, fen string, move string) (map[string]interface{}, error) {
	// Set position then apply move.
	if _, err := c.sendAndReceive(map[string]interface{}{
		"type": "set_position",
		"fen":  fen,
	}); err != nil {
		return nil, err
	}

	raw, err := c.sendAndReceive(map[string]interface{}{
		"type": "move",
		"move": move,
	})
	if err != nil {
		return nil, err
	}

	var resp map[string]interface{}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return nil, err
	}
	if t, _ := resp["type"].(string); t == "error" {
		msg, _ := resp["message"].(string)
		return nil, fmt.Errorf("engine error: %s", msg)
	}
	return resp, nil
}

// ── Feature-aware methods ──

func (c *WSClient) AnalyzePositionFull(ctx context.Context, fen string, depth int) (*AnalysisResponse, error) {
	raw, err := c.sendAndReceive(map[string]interface{}{
		"type":       "analyze_position",
		"fen":        fen,
		"difficulty": depth,
	})
	if err != nil {
		return nil, err
	}

	// Check for error response.
	var check struct {
		Type    string `json:"type"`
		Message string `json:"message"`
	}
	if err := json.Unmarshal(raw, &check); err == nil && check.Type == "error" {
		return nil, fmt.Errorf("engine error: %s", check.Message)
	}

	// The engine wraps the response as {"type":"analysis","features":{...}}.
	// Extract the "features" field which contains the AnalysisResponse.
	var envelope struct {
		Features json.RawMessage `json:"features"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return nil, fmt.Errorf("ws_client: parse envelope: %w", err)
	}

	var resp AnalysisResponse
	if err := json.Unmarshal(envelope.Features, &resp); err != nil {
		return nil, fmt.Errorf("ws_client: parse features: %w", err)
	}
	return &resp, nil
}

func (c *WSClient) BatchAnalyze(ctx context.Context, entries []BatchEntry) ([]MoveFeatureVector, error) {
	raw, err := c.sendAndReceive(map[string]interface{}{
		"type":  "batch_analyze",
		"moves": entries,
	})
	if err != nil {
		return nil, err
	}

	var check struct {
		Type    string `json:"type"`
		Message string `json:"message"`
	}
	if err := json.Unmarshal(raw, &check); err == nil && check.Type == "error" {
		return nil, fmt.Errorf("engine error: %s", check.Message)
	}

	// Envelope: {"type":"batch_analysis","results":[...],"total_moves":N}
	var envelope struct {
		Results []json.RawMessage `json:"results"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return nil, fmt.Errorf("ws_client: parse batch envelope: %w", err)
	}

	feats := make([]MoveFeatureVector, 0, len(envelope.Results))
	for i, r := range envelope.Results {
		// Each result is a BatchResult: {"features":{...},"expert_commentary":...}
		var br BatchResult
		if err := json.Unmarshal(r, &br); err != nil {
			return nil, fmt.Errorf("ws_client: parse batch result %d: %w", i, err)
		}
		feats = append(feats, br.Features)
	}
	return feats, nil
}

func (c *WSClient) Suggest(ctx context.Context, fen string, depth int) (string, int, error) {
	// Set position then request suggestion.
	if _, err := c.sendAndReceive(map[string]interface{}{
		"type": "set_position",
		"fen":  fen,
	}); err != nil {
		return "", 0, err
	}

	raw, err := c.sendAndReceive(map[string]interface{}{
		"type":       "suggest",
		"difficulty": depth,
	})
	if err != nil {
		return "", 0, err
	}

	var resp struct {
		Type  string `json:"type"`
		Move  string `json:"move"`
		Score int    `json:"score"`
	}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return "", 0, fmt.Errorf("ws_client: parse suggest: %w", err)
	}
	if resp.Type == "error" {
		return "", 0, fmt.Errorf("engine error on suggest")
	}
	return resp.Move, resp.Score, nil
}

// DetectPuzzle sends a detect_puzzle message directly to the engine WebSocket
// and returns the structured puzzle detection result.
func (c *WSClient) DetectPuzzle(ctx context.Context, fen string, depth int) (*PuzzleDetectionResult, error) {
	raw, err := c.sendAndReceive(map[string]interface{}{
		"type":  "detect_puzzle",
		"fen":   fen,
		"depth": depth,
	})
	if err != nil {
		return nil, fmt.Errorf("ws_client: detect_puzzle: %w", err)
	}

	// Envelope: {"type":"puzzle_detection","detection":{...}}
	var envelope struct {
		Type      string                 `json:"type"`
		Detection *PuzzleDetectionResult `json:"detection"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return nil, fmt.Errorf("ws_client: parse puzzle_detection: %w", err)
	}
	if envelope.Type == "error" {
		return nil, fmt.Errorf("engine error on detect_puzzle")
	}
	if envelope.Detection == nil {
		return nil, fmt.Errorf("ws_client: puzzle_detection: missing detection field")
	}
	return envelope.Detection, nil
}
