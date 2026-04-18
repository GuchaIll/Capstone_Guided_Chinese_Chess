package engine

import "context"

// EngineClient abstracts the chess engine (e.g. the Rust engine via WebSocket).
type EngineClient interface {
	ValidateFEN(ctx context.Context, fen string) (bool, error)
	Analyze(ctx context.Context, fen string, depth int) (map[string]interface{}, error)
	IsMoveLegal(ctx context.Context, fen string, move string) (bool, error)
	LegalMoves(ctx context.Context, fen string) ([]string, error)
	GetState(ctx context.Context) (map[string]interface{}, error)
	MakeMove(ctx context.Context, fen string, move string) (map[string]interface{}, error)

	// Feature-aware methods (Phase A additions)
	AnalyzePositionFull(ctx context.Context, fen string, depth int) (*AnalysisResponse, error)
	BatchAnalyze(ctx context.Context, entries []BatchEntry) ([]MoveFeatureVector, error)
	Suggest(ctx context.Context, fen string, depth int) (string, int, error)
}

// MockEngine implements EngineClient with canned responses for local dev.
type MockEngine struct{}

func (m *MockEngine) ValidateFEN(_ context.Context, _ string) (bool, error) {
	return true, nil
}

func (m *MockEngine) Analyze(_ context.Context, _ string, _ int) (map[string]interface{}, error) {
	return map[string]interface{}{
		"eval":      "+0.35",
		"best_move": "e2e4",
		"depth":     20,
		"pv":        "e2e4 e7e5 g1f3 b8c6",
	}, nil
}

func (m *MockEngine) IsMoveLegal(_ context.Context, _ string, _ string) (bool, error) {
	return true, nil
}

func (m *MockEngine) LegalMoves(_ context.Context, _ string) ([]string, error) {
	return []string{"e2e4", "d2d4", "g1f3", "b1c3"}, nil
}

func (m *MockEngine) GetState(_ context.Context) (map[string]interface{}, error) {
	return map[string]interface{}{
		"fen":       "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
		"side":      "w",
		"move_list": []string{},
	}, nil
}

func (m *MockEngine) MakeMove(_ context.Context, _ string, _ string) (map[string]interface{}, error) {
	return map[string]interface{}{
		"fen":   "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
		"valid": true,
	}, nil
}

// AnalyzePositionFull returns a realistic mock AnalysisResponse with full feature data.
func (m *MockEngine) AnalyzePositionFull(_ context.Context, fen string, _ int) (*AnalysisResponse, error) {
	return &AnalysisResponse{
		PositionAnalysis: mockPositionAnalysis(fen),
		SearchScore:      35,
		SearchNodes:      125000,
		SearchDepth:      20,
	}, nil
}

// BatchAnalyze returns mock MoveFeatureVectors for each entry.
func (m *MockEngine) BatchAnalyze(_ context.Context, entries []BatchEntry) ([]MoveFeatureVector, error) {
	results := make([]MoveFeatureVector, len(entries))
	for i, e := range entries {
		results[i] = MoveFeatureVector{
			PositionAnalysis: mockPositionAnalysis(e.FEN),
			MoveMetadata: MoveMetadata{
				MoveStr:    e.MoveStr,
				FromSquare: e.MoveStr[:2],
				ToSquare:   e.MoveStr[2:],
				PieceType:  "pawn",
				PieceSide:  "red",
				MoveNumber: i + 1,
			},
			SearchMetrics: SearchMetrics{
				Score:              35 - i*10,
				ScoreDelta:         -10,
				CentipawnLoss:      0,
				DepthReached:       15,
				NodesSearched:      80000,
				NodesPerSecond:     500000,
				SearchTimeMs:       160,
				PrincipalVariation: []string{e.MoveStr},
			},
			Classification: MoveClassification{
				IsGoodMove: true,
				Category:   "good",
			},
			Alternatives:       []AlternativeMove{},
			PostMoveFEN:        e.FEN,
			PostMoveResult:     "in_progress",
		}
	}
	return results, nil
}

// Suggest returns a mock best-move suggestion.
func (m *MockEngine) Suggest(_ context.Context, _ string, _ int) (string, int, error) {
	return "h2e2", 50, nil
}

// mockPositionAnalysis returns a canned PositionAnalysis for testing.
func mockPositionAnalysis(fen string) PositionAnalysis {
	return PositionAnalysis{
		FEN:        fen,
		SideToMove: "red",
		PhaseValue: 1.0,
		PhaseName:  "opening",
		MoveNumber: 1,
		Material: MaterialInfo{
			RedPawns: 5, RedAdvisors: 2, RedElephants: 2, RedKnights: 2, RedCannons: 2, RedRooks: 2,
			BlackPawns: 5, BlackAdvisors: 2, BlackElephants: 2, BlackKnights: 2, BlackCannons: 2, BlackRooks: 2,
			RedMaterialValue: 3200, BlackMaterialValue: 3200, MaterialBalance: 0,
		},
		Mobility: MobilityInfo{
			RedLegalMoves: 44, BlackLegalMoves: 44, MobilityAdvantage: 0,
		},
		RedKingSafety: KingSafety{
			Side: "red", KingSquare: "e0", AdvisorCount: 2, ElephantCount: 2,
			PalaceIntegrity: 1.0,
		},
		BlackKingSafety: KingSafety{
			Side: "black", KingSquare: "e9", AdvisorCount: 2, ElephantCount: 2,
			PalaceIntegrity: 1.0,
		},
		PieceLocations:   []PieceLocation{},
		HangingPieces:    []HangingPiece{},
		PieceRelations:   []PieceRelation{},
		CannonScreens:    []CannonScreen{},
		RookFiles:        []RookFileInfo{},
		PawnChains:       []PawnChain{},
		CrossRiverPieces: []CrossRiverPiece{},
		Forks:            []ForkInfo{},
		Pins:             []PinInfo{},
	}
}
