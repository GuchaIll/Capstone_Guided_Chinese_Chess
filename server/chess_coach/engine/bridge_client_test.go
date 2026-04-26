package engine

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
)

const testBridgeClientFEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req)
}

func jsonResponse(t *testing.T, status int, body interface{}) *http.Response {
	t.Helper()
	data, err := json.Marshal(body)
	if err != nil {
		t.Fatalf("marshal response: %v", err)
	}
	return &http.Response{
		StatusCode: status,
		Header:     http.Header{"Content-Type": []string{"application/json"}},
		Body:       io.NopCloser(bytes.NewReader(data)),
	}
}

func newTestBridgeClient(t *testing.T, fn roundTripFunc) *BridgeClient {
	t.Helper()
	client := NewBridgeClient("http://bridge.test")
	client.http = &http.Client{Transport: fn}
	return client
}

func TestBridgeClientRoutesCoreRequestsToBridgeEndpoints(t *testing.T) {
	client := newTestBridgeClient(t, func(req *http.Request) (*http.Response, error) {
		switch req.URL.Path {
		case "/engine/validate-fen":
			var body map[string]string
			_ = json.NewDecoder(req.Body).Decode(&body)
			if body["fen"] != testBridgeClientFEN {
				t.Fatalf("validate-fen received wrong fen: %#v", body)
			}
			return jsonResponse(t, http.StatusOK, map[string]bool{"valid": true}), nil
		case "/engine/is-move-legal":
			var body map[string]string
			_ = json.NewDecoder(req.Body).Decode(&body)
			if body["move"] != "b0c2" {
				t.Fatalf("is-move-legal received wrong move: %#v", body)
			}
			return jsonResponse(t, http.StatusOK, map[string]bool{"legal": true}), nil
		case "/engine/legal-moves":
			return jsonResponse(t, http.StatusOK, map[string][]string{"moves": []string{"b0c2", "h2e2"}}), nil
		case "/state":
			return jsonResponse(t, http.StatusOK, map[string]interface{}{"fen": testBridgeClientFEN, "side_to_move": "red"}), nil
		case "/engine/make-move":
			var body map[string]string
			_ = json.NewDecoder(req.Body).Decode(&body)
			if body["move"] != "b0c2" {
				t.Fatalf("make-move received wrong move: %#v", body)
			}
			return jsonResponse(t, http.StatusOK, map[string]interface{}{"valid": true, "fen": "next-fen"}), nil
		default:
			t.Fatalf("unexpected path: %s", req.URL.Path)
			return nil, nil
		}
	})

	ctx := context.Background()

	valid, err := client.ValidateFEN(ctx, testBridgeClientFEN)
	if err != nil || !valid {
		t.Fatalf("ValidateFEN() = %v, %v", valid, err)
	}

	legal, err := client.IsMoveLegal(ctx, testBridgeClientFEN, "b0c2")
	if err != nil || !legal {
		t.Fatalf("IsMoveLegal() = %v, %v", legal, err)
	}

	moves, err := client.LegalMoves(ctx, testBridgeClientFEN)
	if err != nil {
		t.Fatalf("LegalMoves() error = %v", err)
	}
	if len(moves) != 2 || moves[0] != "b0c2" {
		t.Fatalf("LegalMoves() = %#v", moves)
	}

	state, err := client.GetState(ctx)
	if err != nil {
		t.Fatalf("GetState() error = %v", err)
	}
	if got, _ := state["fen"].(string); got != testBridgeClientFEN {
		t.Fatalf("GetState() fen = %q", got)
	}

	moveResult, err := client.MakeMove(ctx, testBridgeClientFEN, "b0c2")
	if err != nil {
		t.Fatalf("MakeMove() error = %v", err)
	}
	if got, _ := moveResult["fen"].(string); got != "next-fen" {
		t.Fatalf("MakeMove() fen = %q", got)
	}
}

func TestBridgeClientSupportsAnalysisAndFeatureEndpoints(t *testing.T) {
	client := newTestBridgeClient(t, func(req *http.Request) (*http.Response, error) {
		switch req.URL.Path {
		case "/engine/analyze":
			return jsonResponse(t, http.StatusOK, map[string]interface{}{
				"fen":          testBridgeClientFEN,
				"phase_name":   "opening",
				"search_score": 35,
				"search_depth": 6,
			}), nil
		case "/engine/batch-analyze":
			return jsonResponse(t, http.StatusOK, []map[string]interface{}{
				{
					"position_analysis": map[string]interface{}{
						"fen":        testBridgeClientFEN,
						"phase_name": "opening",
					},
					"move_metadata": map[string]interface{}{
						"move_str": "b0c2",
					},
					"search_metrics": map[string]interface{}{
						"score":               35,
						"centipawn_loss":      0,
						"score_delta":         5,
						"depth_reached":       6,
						"principal_variation": []string{"b0c2"},
					},
					"classification": map[string]interface{}{
						"category":     "good",
						"is_good_move": true,
					},
					"alternatives": []map[string]interface{}{},
				},
			}), nil
		case "/engine/suggest":
			return jsonResponse(t, http.StatusOK, map[string]interface{}{"move": "b0c2", "score": 50}), nil
		case "/engine/puzzle-detect":
			return jsonResponse(t, http.StatusOK, map[string]interface{}{
				"fen":              testBridgeClientFEN,
				"is_puzzle_worthy": true,
				"motif_score":      42,
				"motifs":           []map[string]interface{}{},
				"themes":           []string{"fork"},
				"difficulty_elo":   1400,
				"difficulty_label": "intermediate",
				"hints":            []map[string]interface{}{},
				"best_move":        "b0c2",
				"phase":            "opening",
				"piece_count":      30,
			}), nil
		default:
			t.Fatalf("unexpected path: %s", req.URL.Path)
			return nil, nil
		}
	})

	ctx := context.Background()

	analysis, err := client.Analyze(ctx, testBridgeClientFEN, 6)
	if err != nil {
		t.Fatalf("Analyze() error = %v", err)
	}
	if got, _ := analysis["phase_name"].(string); got != "opening" {
		t.Fatalf("Analyze() phase_name = %q", got)
	}

	full, err := client.AnalyzePositionFull(ctx, testBridgeClientFEN, 6)
	if err != nil {
		t.Fatalf("AnalyzePositionFull() error = %v", err)
	}
	if full.SearchScore != 35 {
		t.Fatalf("AnalyzePositionFull() search_score = %d", full.SearchScore)
	}

	batch, err := client.BatchAnalyze(ctx, []BatchEntry{{FEN: testBridgeClientFEN, MoveStr: "b0c2"}})
	if err != nil {
		t.Fatalf("BatchAnalyze() error = %v", err)
	}
	if len(batch) != 1 || batch[0].MoveMetadata.MoveStr != "b0c2" {
		t.Fatalf("BatchAnalyze() = %#v", batch)
	}

	move, score, err := client.Suggest(ctx, testBridgeClientFEN, 6)
	if err != nil {
		t.Fatalf("Suggest() error = %v", err)
	}
	if move != "b0c2" || score != 50 {
		t.Fatalf("Suggest() = %q, %d", move, score)
	}

	puzzle, err := client.DetectPuzzle(ctx, testBridgeClientFEN, 6)
	if err != nil {
		t.Fatalf("DetectPuzzle() error = %v", err)
	}
	if !puzzle.IsPuzzleWorthy || puzzle.DifficultyLabel != "intermediate" {
		t.Fatalf("DetectPuzzle() = %#v", puzzle)
	}
}

func TestBridgeClientReturnsHttpErrors(t *testing.T) {
	client := newTestBridgeClient(t, func(req *http.Request) (*http.Response, error) {
		return &http.Response{
			StatusCode: http.StatusBadGateway,
			Header:     http.Header{"Content-Type": []string{"text/plain"}},
			Body:       io.NopCloser(strings.NewReader("bridge unavailable")),
		}, nil
	})

	_, err := client.ValidateFEN(context.Background(), testBridgeClientFEN)
	if err == nil || !strings.Contains(err.Error(), "HTTP 502") {
		t.Fatalf("expected HTTP error, got %v", err)
	}
}
