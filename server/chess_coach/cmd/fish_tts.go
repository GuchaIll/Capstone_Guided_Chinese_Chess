package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type fishReferenceClip struct {
	ClipID         string            `json:"clip_id"`
	VoiceID        string            `json:"voice_id"`
	AudioPath      string            `json:"audio_path"`
	TranscriptPath string            `json:"transcript_path"`
	StylePath      string            `json:"style_path"`
	Transcript     string            `json:"transcript"`
	Style          map[string]string `json:"style"`
	Ready          bool              `json:"ready"`
}

type fishReferenceBundle struct {
	GeneratedAt  string              `json:"generated_at"`
	VoiceID      string              `json:"voice_id"`
	PromptText   string              `json:"prompt_text"`
	StyleSummary string              `json:"style_summary"`
	References   []fishReferenceClip `json:"references"`
}

type modalFishReference struct {
	Filename    string            `json:"filename"`
	AudioBase64 string            `json:"audio_base64"`
	Text        string            `json:"text"`
	Style       map[string]string `json:"style,omitempty"`
}

type modalFishRequest struct {
	Text           string               `json:"text"`
	Model          string               `json:"model,omitempty"`
	ResponseFormat string               `json:"response_format,omitempty"`
	PromptText     string               `json:"prompt_text,omitempty"`
	StyleSummary   string               `json:"style_summary,omitempty"`
	References     []modalFishReference `json:"references"`
}

type fishTTSClient struct {
	UpstreamURL         string
	APIKey              string
	Model               string
	ReferenceBundlePath string
	HTTPClient          *http.Client
}

func newFishTTSClientFromEnv() *fishTTSClient {
	baseURL := strings.TrimSpace(firstNonEmptyEnv("FISH_TTS_API_URL"))
	if baseURL == "" {
		return nil
	}

	bundlePath := strings.TrimSpace(firstNonEmptyEnv(
		"FISH_TTS_REFERENCE_BUNDLE",
		"TTS_REFERENCE_BUNDLE",
	))
	if bundlePath == "" {
		bundlePath = "tts/out/chopper_reference_bundle.json"
	}

	timeout := envDurationSeconds("FISH_TTS_TIMEOUT_SECONDS", 90*time.Second)
	return &fishTTSClient{
		UpstreamURL:         normalizeFishTTSURL(baseURL),
		APIKey:              strings.TrimSpace(firstNonEmptyEnv("FISH_TTS_API_KEY")),
		Model:               strings.TrimSpace(firstNonEmptyEnv("FISH_TTS_MODEL")),
		ReferenceBundlePath: bundlePath,
		HTTPClient:          &http.Client{Timeout: timeout},
	}
}

func normalizeFishTTSURL(raw string) string {
	trimmed := strings.TrimRight(strings.TrimSpace(raw), "/")
	if trimmed == "" {
		return ""
	}
	if strings.HasSuffix(trimmed, "/tts") {
		return trimmed
	}
	return trimmed + "/tts"
}

func makeTTSHandler(client *fishTTSClient) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if client == nil {
			http.Error(w, "fish tts is not configured", http.StatusServiceUnavailable)
			return
		}

		var body struct {
			Text string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, "invalid JSON", http.StatusBadRequest)
			return
		}
		if strings.TrimSpace(body.Text) == "" {
			http.Error(w, "text is required", http.StatusBadRequest)
			return
		}

		audioBytes, contentType, err := client.Synthesize(r.Context(), body.Text)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadGateway)
			return
		}

		w.Header().Set("Content-Type", firstNonEmptyString(contentType, "audio/wav"))
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(audioBytes)
	}
}

func (c *fishTTSClient) Synthesize(ctx context.Context, text string) ([]byte, string, error) {
	requestBody, err := c.buildRequestPayload(text)
	if err != nil {
		return nil, "", err
	}

	bodyBytes, err := json.Marshal(requestBody)
	if err != nil {
		return nil, "", fmt.Errorf("marshal fish tts request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.UpstreamURL, bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, "", fmt.Errorf("create fish tts request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "audio/wav")
	if c.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.APIKey)
	}

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, "", fmt.Errorf("call fish tts upstream: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 16*1024))
		msg := strings.TrimSpace(string(body))
		if msg == "" {
			msg = resp.Status
		}
		return nil, "", fmt.Errorf("fish tts upstream returned %d: %s", resp.StatusCode, msg)
	}

	audioBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, "", fmt.Errorf("read fish tts upstream response: %w", err)
	}
	return audioBytes, resp.Header.Get("Content-Type"), nil
}

func (c *fishTTSClient) buildRequestPayload(text string) (*modalFishRequest, error) {
	bundle, err := loadFishReferenceBundle(c.ReferenceBundlePath)
	if err != nil {
		return nil, err
	}

	references := make([]modalFishReference, 0, len(bundle.References))
	for _, ref := range bundle.References {
		if !ref.Ready || strings.TrimSpace(ref.Transcript) == "" {
			continue
		}

		audioBytes, err := os.ReadFile(filepath.Clean(ref.AudioPath))
		if err != nil {
			return nil, fmt.Errorf("read reference audio %s: %w", ref.AudioPath, err)
		}
		references = append(references, modalFishReference{
			Filename:    filepath.Base(ref.AudioPath),
			AudioBase64: base64.StdEncoding.EncodeToString(audioBytes),
			Text:        strings.TrimSpace(ref.Transcript),
			Style:       ref.Style,
		})
	}

	if len(references) == 0 {
		return nil, errors.New("no ready reference clips in fish tts bundle")
	}

	return &modalFishRequest{
		Text:           strings.TrimSpace(text),
		Model:          c.Model,
		ResponseFormat: "wav",
		PromptText:     strings.TrimSpace(bundle.PromptText),
		StyleSummary:   strings.TrimSpace(bundle.StyleSummary),
		References:     references,
	}, nil
}

func loadFishReferenceBundle(path string) (*fishReferenceBundle, error) {
	raw, err := os.ReadFile(filepath.Clean(path))
	if err != nil {
		return nil, fmt.Errorf("read fish tts reference bundle: %w", err)
	}

	var bundle fishReferenceBundle
	if err := json.Unmarshal(raw, &bundle); err != nil {
		return nil, fmt.Errorf("decode fish tts reference bundle: %w", err)
	}
	if len(bundle.References) == 0 {
		return nil, errors.New("fish tts reference bundle has no references")
	}
	return &bundle, nil
}
