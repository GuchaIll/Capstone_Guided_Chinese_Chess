package chesstools

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"go_agent_framework/core"
)

// ChromaDBRetriever implements core.Retriever by querying a ChromaDB HTTP API.
// It uses an external embedding service to convert query text into vectors.
type ChromaDBRetriever struct {
	BaseURL      string // e.g. "http://chromadb:8000"
	EmbeddingURL string // e.g. "http://embedding:8100"
	Collection   string // collection name, e.g. "openings"
	collectionID string // resolved lazily on first query
	client       *http.Client
}

// NewChromaDBRetriever creates a retriever for the given collection.
func NewChromaDBRetriever(baseURL, embeddingURL, collection string) *ChromaDBRetriever {
	return &ChromaDBRetriever{
		BaseURL:      baseURL,
		EmbeddingURL: embeddingURL,
		Collection:   collection,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// resolveCollection looks up the collection ID by name (cached after first call).
func (r *ChromaDBRetriever) resolveCollection(ctx context.Context) (string, error) {
	if r.collectionID != "" {
		return r.collectionID, nil
	}

	url := fmt.Sprintf("%s/api/v2/tenants/default_tenant/databases/default_database/collections/%s",
		r.BaseURL, r.Collection)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", fmt.Errorf("chromadb: build request: %w", err)
	}

	resp, err := r.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("chromadb: get collection %q: %w", r.Collection, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("chromadb: get collection %q: status %d: %s", r.Collection, resp.StatusCode, body)
	}

	var result struct {
		ID string `json:"id"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", fmt.Errorf("chromadb: decode collection response: %w", err)
	}
	r.collectionID = result.ID
	return r.collectionID, nil
}

// Retrieve queries ChromaDB for the top-K documents matching the query text.
func (r *ChromaDBRetriever) Retrieve(ctx context.Context, query string, topK int) ([]core.Chunk, error) {
	collID, err := r.resolveCollection(ctx)
	if err != nil {
		return nil, err
	}

	if topK <= 0 {
		topK = 5
	}

	// Get embedding for the query text
	qEmbed, err := r.embed(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("chromadb: embed query: %w", err)
	}

	// ChromaDB v2 query endpoint
	url := fmt.Sprintf("%s/api/v2/tenants/default_tenant/databases/default_database/collections/%s/query",
		r.BaseURL, collID)

	payload := map[string]interface{}{
		"query_embeddings": [][]float64{qEmbed},
		"n_results":        topK,
		"include":          []string{"documents", "distances"},
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("chromadb: marshal query: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("chromadb: build query request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := r.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("chromadb: query %q: %w", r.Collection, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("chromadb: query %q: status %d: %s", r.Collection, resp.StatusCode, respBody)
	}

	// ChromaDB query response structure:
	// { "ids": [["id1","id2"]], "documents": [["doc1","doc2"]], "distances": [[0.1, 0.2]] }
	var result struct {
		IDs       [][]string  `json:"ids"`
		Documents [][]string  `json:"documents"`
		Distances [][]float64 `json:"distances"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("chromadb: decode query response: %w", err)
	}

	// Convert to core.Chunk slice
	if len(result.IDs) == 0 || len(result.IDs[0]) == 0 {
		return nil, nil
	}

	ids := result.IDs[0]
	docs := result.Documents[0]
	dists := result.Distances[0]

	chunks := make([]core.Chunk, len(ids))
	for i := range ids {
		// ChromaDB returns distances (lower = better). Convert to similarity score.
		score := float32(1.0 / (1.0 + dists[i]))
		chunks[i] = core.Chunk{
			ID:      ids[i],
			Content: docs[i],
			Score:   score,
		}
	}

	return chunks, nil
}

// NewChromaDBRetrievers creates a map of retrievers for all standard chess coach
// collections, suitable for passing to RegisterRAGTools.
func NewChromaDBRetrievers(baseURL, embeddingURL string) map[string]core.Retriever {
	collections := []string{"openings", "tactics", "endgames", "beginner_principles"}
	retrievers := make(map[string]core.Retriever, len(collections))
	for _, name := range collections {
		retrievers[name] = NewChromaDBRetriever(baseURL, embeddingURL, name)
	}
	return retrievers
}

// embed calls the embedding service to convert text into a vector.
func (r *ChromaDBRetriever) embed(ctx context.Context, text string) ([]float64, error) {
	payload := map[string]interface{}{
		"texts": []string{text},
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}

	url := fmt.Sprintf("%s/embed", r.EmbeddingURL)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := r.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("embedding service: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("embedding service: status %d: %s", resp.StatusCode, respBody)
	}

	var result struct {
		Embeddings [][]float64 `json:"embeddings"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("embedding service: decode: %w", err)
	}
	if len(result.Embeddings) == 0 {
		return nil, fmt.Errorf("embedding service: no embeddings returned")
	}
	return result.Embeddings[0], nil
}
