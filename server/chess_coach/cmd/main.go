package main

import (
	"encoding/json"
	"fmt"
	"log"
	"log/slog"
	"net/http"
	"os"
	"time"

	chess "chess_coach"
	"chess_coach/engine"
	chesstools "chess_coach/tools"
	"go_agent_framework/contrib/envutil"
	"go_agent_framework/contrib/llm"
	"go_agent_framework/contrib/skills"
	"go_agent_framework/core"
	"go_agent_framework/observability"
)

func main() {
	envutil.Load(".env")
	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))

	eng := buildEngineClient(logger)
	models := buildModels(logger)

	toolReg := core.NewToolRegistry()
	registerTools(toolReg, eng, logger)
	logger.Info("chess tools registered", "tools", toolReg.List())

	// Set up skill registry and load coaching skills.
	skillReg := core.NewSkillRegistry()
	if err := skills.LoadFromDir("skills", skillReg); err != nil {
		logger.Warn("could not load skills dir, registering inline", "err", err)
		_ = skillReg.Register(&core.Skill{
			Name:        "beginner_coaching",
			Description: "Tailor your chess coaching advice towards beginners: make answers concise, explain key turns, refer to pieces by their full name in addition to color.",
			Steps:       []core.SkillStep{{Name: "format_advice", Kind: core.KindLLM}},
		})
	}
	logger.Info("skills registered", "skills", skillReg.List())

	graph := chess.BuildGraph(toolReg, skillReg, models)
	store := core.NewMemStore()
	orch := core.NewOrchestrator(graph, store, 8)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	})
	mux.HandleFunc("POST /coach", orch.HandleRequest)
	mux.HandleFunc("POST /coach/analyze", makeAnalyzeHandler(graph, store))
	mux.HandleFunc("POST /coach/blunder", makeBlunderHandler(graph, store))
	mux.HandleFunc("POST /coach/puzzle", makePuzzleHandler(graph, store))
	mux.HandleFunc("POST /coach/features", makeFeaturesHandler(toolReg))
	mux.HandleFunc("POST /coach/classify-move", makeClassifyMoveHandler(toolReg))
	mux.Handle("/metrics", observability.Handler())

	// Dashboard with chat
	adapter := &chess.GraphAdapter{Graph: graph}
	chatHandler := makeChatHandler(graph, store)
	dashMux := observability.DashboardMux(adapter, os.DirFS("dashboard/dist"), chatHandler)
	mux.Handle("/dashboard/", dashMux)

	addr := ":8080"
	logger.Info("chess-coach listening", "addr", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func buildModels(logger *slog.Logger) llm.Models {
	apiKey := os.Getenv("OPENROUTER_API_KEY")
	if apiKey != "" {
		logger.Info("using OpenRouter LLMs")
		analysis := observability.InstrumentLLM(
			&llm.OpenRouterClient{APIKey: apiKey, ModelName: "z-ai/glm-4.5-air:free"},
			observability.LLMOptions{},
		)
		orchestration := observability.InstrumentLLM(
			&llm.OpenRouterClient{APIKey: apiKey, ModelName: "liquid/lfm-2.5-1.2b-instruct:free"},
			observability.LLMOptions{},
		)
		return llm.Models{Analysis: analysis, Orchestration: orchestration}
	}

	logger.Info("OPENROUTER_API_KEY not set, using mock LLMs")
	mock := observability.InstrumentLLM(&llm.MockLLM{
		Response:     "Consider controlling the centre with pawns and developing your knights early.",
		ProviderName: "mock",
		ModelName:    "chess-coach-demo",
	}, observability.LLMOptions{})
	return llm.Models{Analysis: mock, Orchestration: mock}
}

func buildEngineClient(logger *slog.Logger) engine.EngineClient {
	if bridgeURL := os.Getenv("BRIDGE_URL"); bridgeURL != "" {
		logger.Info("using BridgeClient (state bridge)", "url", bridgeURL)
		return engine.NewBridgeClient(bridgeURL)
	}
	// WSClient (direct WebSocket to engine) is intentionally excluded from the
	// fallback chain. All engine communication must flow through the state bridge
	// to keep the coaching service decoupled from the engine transport.
	logger.Info("BRIDGE_URL not set — using MockEngine (set BRIDGE_URL to connect to state bridge)")
	return &engine.MockEngine{}
}

func registerTools(toolReg *core.ToolRegistry, eng engine.EngineClient, logger *slog.Logger) {
	if err := chesstools.RegisterChessTools(toolReg, eng); err != nil {
		log.Fatalf("register chess tools: %v", err)
	}
	if err := chesstools.RegisterPuzzleDetectorTools(toolReg, eng); err != nil {
		log.Fatalf("register puzzle tools: %v", err)
	}
	if err := chesstools.RegisterPGNTools(toolReg); err != nil {
		log.Fatalf("register pgn tools: %v", err)
	}
	chromaURL := os.Getenv("CHROMADB_URL")
	if chromaURL == "" {
		logger.Info("CHROMADB_URL not set, RAG tools disabled")
		return
	}
	embeddingURL := os.Getenv("EMBEDDING_URL")
	if embeddingURL == "" {
		embeddingURL = "http://embedding:8100"
	}
	retrievers := chesstools.NewChromaDBRetrievers(chromaURL, embeddingURL)
	if err := chesstools.RegisterRAGTools(toolReg, retrievers); err != nil {
		logger.Warn("could not register RAG tools", "err", err)
	} else {
		logger.Info("RAG tools registered", "chromadb", chromaURL, "embedding", embeddingURL)
	}
}

func makeChatHandler(graph *core.Graph, store core.StateStore) observability.ChatHandler {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Message   string `json:"message"`
			SessionID string `json:"session_id,omitempty"`
			FEN       string `json:"fen,omitempty"`
			Move      string `json:"move,omitempty"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, "invalid JSON", http.StatusBadRequest)
			return
		}
		if body.Message == "" {
			http.Error(w, "message is required", http.StatusBadRequest)
			return
		}

		sessionID := body.SessionID
		if sessionID == "" {
			sessionID = fmt.Sprintf("chat-%d", time.Now().UnixMilli())
		}

		session, err := store.Get(sessionID)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		// Map chat message to chess_coach expected input.
		// IngestAgent will extract FEN, move, and question from the raw message.
		session.State["raw_input"] = body.Message
		session.State["fen"] = body.FEN
		session.State["question"] = body.Message
		session.State["move"] = body.Move

		ctx := &core.Context{
			SessionID:  sessionID,
			State:      session.State,
			Logger:     slog.Default(),
			StdContext: r.Context(),
		}

		if err := graph.Run(ctx); err != nil {
			observability.PublishChatResponse(graph.Name(), sessionID, "Error: "+err.Error())
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		_ = store.Put(session)

		// Extract response from state.
		answer := ""
		if fb, ok := ctx.State["feedback"].(string); ok {
			answer = fb
		}

		observability.PublishChatResponse(graph.Name(), sessionID, answer)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"session_id": sessionID,
			"response":   answer,
			"state":      ctx.State,
		})
	}
}

// makeAnalyzeHandler creates a handler for position-analysis-only requests.
func makeAnalyzeHandler(graph *core.Graph, store core.StateStore) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			FEN   string `json:"fen"`
			Depth int    `json:"depth"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, "invalid JSON", http.StatusBadRequest)
			return
		}
		if body.FEN == "" {
			http.Error(w, "fen is required", http.StatusBadRequest)
			return
		}

		sessionID := fmt.Sprintf("analyze-%d", time.Now().UnixMilli())
		session, _ := store.Get(sessionID)
		session.State["fen"] = body.FEN
		session.State["route_position_analysis"] = true
		session.State["route_blunder_detection"] = false
		session.State["route_puzzle"] = false
		session.State["coach_trigger"] = "explicit"

		ctx := &core.Context{
			SessionID:  sessionID,
			State:      session.State,
			Logger:     slog.Default(),
			StdContext: r.Context(),
		}

		if err := graph.Run(ctx); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		_ = store.Put(session)

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"session_id": sessionID,
			"response":   ctx.State["feedback"],
			"metrics":    ctx.State["engine_metrics"],
			"game_phase": ctx.State["game_phase"],
			"material":   ctx.State["material_info"],
		})
	}
}

// makeBlunderHandler creates a handler for blunder detection requests.
func makeBlunderHandler(graph *core.Graph, store core.StateStore) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			FEN   string `json:"fen"`
			Moves string `json:"moves"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, "invalid JSON", http.StatusBadRequest)
			return
		}
		if body.FEN == "" || body.Moves == "" {
			http.Error(w, "fen and moves are required", http.StatusBadRequest)
			return
		}

		sessionID := fmt.Sprintf("blunder-%d", time.Now().UnixMilli())
		session, _ := store.Get(sessionID)
		session.State["fen"] = body.FEN
		session.State["moves"] = body.Moves
		session.State["has_move"] = true
		session.State["route_position_analysis"] = true
		session.State["route_blunder_detection"] = true
		session.State["route_puzzle"] = false
		session.State["coach_trigger"] = "explicit"

		ctx := &core.Context{
			SessionID:  sessionID,
			State:      session.State,
			Logger:     slog.Default(),
			StdContext: r.Context(),
		}

		if err := graph.Run(ctx); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		_ = store.Put(session)

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"session_id": sessionID,
			"response":   ctx.State["feedback"],
			"blunders":   ctx.State["blunder_analysis"],
		})
	}
}

// makePuzzleHandler creates a handler for puzzle generation requests.
func makePuzzleHandler(graph *core.Graph, store core.StateStore) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			FEN string `json:"fen"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, "invalid JSON", http.StatusBadRequest)
			return
		}
		if body.FEN == "" {
			http.Error(w, "fen is required", http.StatusBadRequest)
			return
		}

		sessionID := fmt.Sprintf("puzzle-%d", time.Now().UnixMilli())
		session, _ := store.Get(sessionID)
		session.State["fen"] = body.FEN
		session.State["route_position_analysis"] = true
		session.State["route_blunder_detection"] = false
		session.State["route_puzzle"] = true
		session.State["coach_trigger"] = "explicit"

		ctx := &core.Context{
			SessionID:  sessionID,
			State:      session.State,
			Logger:     slog.Default(),
			StdContext: r.Context(),
		}

		if err := graph.Run(ctx); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		_ = store.Put(session)

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"session_id": sessionID,
			"response":   ctx.State["feedback"],
			"puzzle":     ctx.State["puzzle"],
			"difficulty": ctx.State["puzzle_difficulty"],
			"themes":     ctx.State["puzzle_themes"],
		})
	}
}

// makeFeaturesHandler creates a lightweight endpoint that returns position features
// without running the full coaching graph.
func makeFeaturesHandler(toolReg *core.ToolRegistry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			FEN      string `json:"fen"`
			Features string `json:"features"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, "invalid JSON", http.StatusBadRequest)
			return
		}
		if body.FEN == "" {
			http.Error(w, "fen is required", http.StatusBadRequest)
			return
		}
		if body.Features == "" {
			body.Features = "material,mobility,king_safety,hanging_pieces,forks,pins,cannon_screens"
		}

		args, _ := json.Marshal(map[string]interface{}{
			"fen":      body.FEN,
			"features": body.Features,
		})
		call := core.ToolCall{ID: "features_1", Name: "get_position_features", Args: args}
		result := toolReg.ExecuteTool(r.Context(), call)
		if result.Error != "" {
			http.Error(w, result.Error, http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, result.Output)
	}
}

// makeClassifyMoveHandler creates a lightweight endpoint that classifies a single move.
func makeClassifyMoveHandler(toolReg *core.ToolRegistry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			FEN  string `json:"fen"`
			Move string `json:"move"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, "invalid JSON", http.StatusBadRequest)
			return
		}
		if body.FEN == "" || body.Move == "" {
			http.Error(w, "fen and move are required", http.StatusBadRequest)
			return
		}

		args, _ := json.Marshal(map[string]interface{}{
			"fen":  body.FEN,
			"move": body.Move,
		})
		call := core.ToolCall{ID: "classify_1", Name: "classify_move", Args: args}
		result := toolReg.ExecuteTool(r.Context(), call)
		if result.Error != "" {
			http.Error(w, result.Error, http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, result.Output)
	}
}
