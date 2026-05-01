package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestFishTTSClientBuildRequestPayload(t *testing.T) {
	tempDir := t.TempDir()
	audioPath := filepath.Join(tempDir, "ref.wav")
	if err := os.WriteFile(audioPath, []byte("reference-audio"), 0o644); err != nil {
		t.Fatalf("write audio: %v", err)
	}

	bundlePath := filepath.Join(tempDir, "bundle.json")
	bundle := fishReferenceBundle{
		VoiceID:      "chopper",
		PromptText:   "Move the horse to f3.",
		StyleSummary: "mood=calm",
		References: []fishReferenceClip{{
			ClipID:     "clip-1",
			VoiceID:    "chopper",
			AudioPath:  audioPath,
			Transcript: "Move the horse to f3.",
			Style:      map[string]string{"mood": "calm"},
			Ready:      true,
		}},
	}
	raw, _ := json.Marshal(bundle)
	if err := os.WriteFile(bundlePath, raw, 0o644); err != nil {
		t.Fatalf("write bundle: %v", err)
	}

	client := &fishTTSClient{
		UpstreamURL:         "https://example.com/tts",
		Model:               "s2-pro",
		ReferenceBundlePath: bundlePath,
	}
	payload, err := client.buildRequestPayload("Explain the plan.")
	if err != nil {
		t.Fatalf("build payload: %v", err)
	}

	if payload.Text != "Explain the plan." {
		t.Fatalf("text = %q", payload.Text)
	}
	if len(payload.References) != 1 {
		t.Fatalf("references = %d", len(payload.References))
	}
	if payload.References[0].Text != "Move the horse to f3." {
		t.Fatalf("reference transcript = %q", payload.References[0].Text)
	}
	if got := string(mustDecodeBase64(t, payload.References[0].AudioBase64)); got != "reference-audio" {
		t.Fatalf("reference audio = %q", got)
	}
}

func TestMakeTTSHandlerStreamsUpstreamAudio(t *testing.T) {
	tempDir := t.TempDir()
	audioPath := filepath.Join(tempDir, "ref.wav")
	if err := os.WriteFile(audioPath, []byte("reference-audio"), 0o644); err != nil {
		t.Fatalf("write audio: %v", err)
	}
	bundlePath := filepath.Join(tempDir, "bundle.json")
	raw, _ := json.Marshal(fishReferenceBundle{
		PromptText: "Reference prompt.",
		References: []fishReferenceClip{{
			AudioPath:  audioPath,
			Transcript: "Reference prompt.",
			Ready:      true,
		}},
	})
	if err := os.WriteFile(bundlePath, raw, 0o644); err != nil {
		t.Fatalf("write bundle: %v", err)
	}

	handler := makeTTSHandler(&fishTTSClient{
		UpstreamURL:         "https://fish.example/tts",
		ReferenceBundlePath: bundlePath,
		HTTPClient: &http.Client{
			Timeout: 5 * time.Second,
			Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
				if r.Method != http.MethodPost {
					t.Fatalf("method = %s", r.Method)
				}
				var req modalFishRequest
				if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
					t.Fatalf("decode upstream request: %v", err)
				}
				if req.Text != "Speak this." {
					t.Fatalf("req.Text = %q", req.Text)
				}
				if len(req.References) != 1 {
					t.Fatalf("len(req.References) = %d", len(req.References))
				}
				return &http.Response{
					StatusCode: http.StatusOK,
					Header:     http.Header{"Content-Type": []string{"audio/wav"}},
					Body:       io.NopCloser(strings.NewReader("wav-bytes")),
				}, nil
			}),
		},
	})

	body := bytes.NewBufferString(`{"text":"Speak this."}`)
	req := httptest.NewRequest(http.MethodPost, "/dashboard/tts", body)
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler(rr, req.WithContext(context.Background()))

	if rr.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", rr.Code, rr.Body.String())
	}
	if got := rr.Header().Get("Content-Type"); got != "audio/wav" {
		t.Fatalf("content type = %q", got)
	}
	if got := rr.Body.String(); got != "wav-bytes" {
		t.Fatalf("body = %q", got)
	}
}

func TestFishTTSClientPropagatesUpstreamErrors(t *testing.T) {
	tempDir := t.TempDir()
	audioPath := filepath.Join(tempDir, "ref.wav")
	if err := os.WriteFile(audioPath, []byte("reference-audio"), 0o644); err != nil {
		t.Fatalf("write audio: %v", err)
	}
	bundlePath := filepath.Join(tempDir, "bundle.json")
	raw, _ := json.Marshal(fishReferenceBundle{
		References: []fishReferenceClip{{
			AudioPath:  audioPath,
			Transcript: "Reference prompt.",
			Ready:      true,
		}},
	})
	if err := os.WriteFile(bundlePath, raw, 0o644); err != nil {
		t.Fatalf("write bundle: %v", err)
	}

	client := &fishTTSClient{
		UpstreamURL:         "https://fish.example/tts",
		ReferenceBundlePath: bundlePath,
		HTTPClient: &http.Client{
			Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
				return &http.Response{
					StatusCode: http.StatusBadGateway,
					Body:       io.NopCloser(strings.NewReader("boom")),
					Header:     make(http.Header),
				}, nil
			}),
		},
	}
	_, _, err := client.Synthesize(context.Background(), "Speak this.")
	if err == nil || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("expected upstream error, got %v", err)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) {
	return fn(r)
}

func mustDecodeBase64(t *testing.T, value string) []byte {
	t.Helper()
	decoded, err := base64.StdEncoding.DecodeString(value)
	if err != nil {
		t.Fatalf("decode base64: %v", err)
	}
	return decoded
}
