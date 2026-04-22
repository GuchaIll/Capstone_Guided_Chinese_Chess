package engine

// Typed Go structs mirroring the Rust engine's feature extraction output.
// Field names and JSON tags match the Rust serde serialization exactly (snake_case, no renames).
// See Engine/src/AI/FEATURE_SCHEMA.md and Engine/src/AI/position_analyzer.rs / feature_extractor.rs.

// ── Position Analysis sub-structs ──

type MaterialInfo struct {
	RedPawns           int `json:"red_pawns"`
	RedAdvisors        int `json:"red_advisors"`
	RedElephants       int `json:"red_elephants"`
	RedKnights         int `json:"red_knights"`
	RedCannons         int `json:"red_cannons"`
	RedRooks           int `json:"red_rooks"`
	BlackPawns         int `json:"black_pawns"`
	BlackAdvisors      int `json:"black_advisors"`
	BlackElephants     int `json:"black_elephants"`
	BlackKnights       int `json:"black_knights"`
	BlackCannons       int `json:"black_cannons"`
	BlackRooks         int `json:"black_rooks"`
	RedMaterialValue   int `json:"red_material_value"`
	BlackMaterialValue int `json:"black_material_value"`
	MaterialBalance    int `json:"material_balance"`
}

type MobilityInfo struct {
	RedLegalMoves     int `json:"red_legal_moves"`
	BlackLegalMoves   int `json:"black_legal_moves"`
	MobilityAdvantage int `json:"mobility_advantage"`
}

type KingSafety struct {
	Side              string  `json:"side"`
	KingSquare        string  `json:"king_square"`
	AdvisorCount      int     `json:"advisor_count"`
	ElephantCount     int     `json:"elephant_count"`
	PalaceIntegrity   float64 `json:"palace_integrity"`
	AttackersNearKing int     `json:"attackers_near_king"`
	KingFileOpen      bool    `json:"king_file_open"`
	KingExposed       bool    `json:"king_exposed"`
}

type PieceLocation struct {
	PieceType    string `json:"piece_type"`
	Side         string `json:"side"`
	Square       string `json:"square"`
	File         int    `json:"file"`
	Rank         int    `json:"rank"`
	CrossedRiver bool   `json:"crossed_river"`
}

type HangingPiece struct {
	PieceType  string   `json:"piece_type"`
	Side       string   `json:"side"`
	Square     string   `json:"square"`
	Value      int      `json:"value"`
	AttackedBy []string `json:"attacked_by"`
}

type PieceRelation struct {
	PieceA   string `json:"piece_a"`
	PieceB   string `json:"piece_b"`
	Relation string `json:"relation"`
	Distance int    `json:"distance"`
}

type CannonScreen struct {
	CannonSquare string  `json:"cannon_square"`
	CannonSide   string  `json:"cannon_side"`
	ScreenSquare string  `json:"screen_square"`
	ScreenPiece  string  `json:"screen_piece"`
	TargetSquare *string `json:"target_square"`
	TargetPiece  *string `json:"target_piece"`
	Direction    string  `json:"direction"`
}

type RookFileInfo struct {
	RookSquare   string `json:"rook_square"`
	RookSide     string `json:"rook_side"`
	File         int    `json:"file"`
	IsOpenFile   bool   `json:"is_open_file"`
	IsSemiOpen   bool   `json:"is_semi_open"`
	ControlsRank bool   `json:"controls_rank"`
}

type PawnChain struct {
	Side         string   `json:"side"`
	Squares      []string `json:"squares"`
	CrossedRiver bool     `json:"crossed_river"`
	Connected    bool     `json:"connected"`
}

type CrossRiverPiece struct {
	PieceType      string `json:"piece_type"`
	Side           string `json:"side"`
	Square         string `json:"square"`
	DepthIntoEnemy int    `json:"depth_into_enemy"`
}

type ForkInfo struct {
	AttackerType   string   `json:"attacker_type"`
	AttackerSquare string   `json:"attacker_square"`
	AttackerSide   string   `json:"attacker_side"`
	Targets        []string `json:"targets"`
}

type PinInfo struct {
	PinnedPiece  string `json:"pinned_piece"`
	PinnedSquare string `json:"pinned_square"`
	PinnerType   string `json:"pinner_type"`
	PinnerSquare string `json:"pinner_square"`
	PinnedTo     string `json:"pinned_to"`
}

// PositionAnalysis is the full positional snapshot produced by the engine's position_analyzer.
type PositionAnalysis struct {
	FEN              string            `json:"fen"`
	SideToMove       string            `json:"side_to_move"`
	PhaseValue       float64           `json:"phase_value"`
	PhaseName        string            `json:"phase_name"`
	MoveNumber       int               `json:"move_number"`
	HalfmoveClock    int               `json:"halfmove_clock"`
	Material         MaterialInfo      `json:"material"`
	Mobility         MobilityInfo      `json:"mobility"`
	RedKingSafety    KingSafety        `json:"red_king_safety"`
	BlackKingSafety  KingSafety        `json:"black_king_safety"`
	RedPSTScore      int               `json:"red_pst_score"`
	BlackPSTScore    int               `json:"black_pst_score"`
	PieceLocations   []PieceLocation   `json:"piece_locations"`
	HangingPieces    []HangingPiece    `json:"hanging_pieces"`
	PieceRelations   []PieceRelation   `json:"piece_relations"`
	CannonScreens    []CannonScreen    `json:"cannon_screens"`
	RookFiles        []RookFileInfo    `json:"rook_files"`
	PawnChains       []PawnChain       `json:"pawn_chains"`
	CrossRiverPieces []CrossRiverPiece `json:"cross_river_pieces"`
	Forks            []ForkInfo        `json:"forks"`
	Pins             []PinInfo         `json:"pins"`
	RedInCheck       bool              `json:"red_in_check"`
	BlackInCheck     bool              `json:"black_in_check"`
	IsCheckmate      bool              `json:"is_checkmate"`
	IsStalemate      bool              `json:"is_stalemate"`
	RepetitionCount  int               `json:"repetition_count"`
}

// ── Move Feature Vector sub-structs ──

type SearchMetrics struct {
	Score              int      `json:"score"`
	ScoreDelta         int      `json:"score_delta"`
	CentipawnLoss      int      `json:"centipawn_loss"`
	DepthReached       int      `json:"depth_reached"`
	NodesSearched      uint64   `json:"nodes_searched"`
	NodesPerSecond     float64  `json:"nodes_per_second"`
	SearchTimeMs       float64  `json:"search_time_ms"`
	PrincipalVariation []string `json:"principal_variation"`
	TTHits             uint64   `json:"tt_hits"`
	TTCuts             uint64   `json:"tt_cuts"`
	TTStores           uint64   `json:"tt_stores"`
	TTCollisions       uint64   `json:"tt_collisions"`
	TTHitRate          float64  `json:"tt_hit_rate"`
}

type MoveMetadata struct {
	MoveStr           string  `json:"move_str"`
	FromSquare        string  `json:"from_square"`
	ToSquare          string  `json:"to_square"`
	PieceType         string  `json:"piece_type"`
	PieceSide         string  `json:"piece_side"`
	IsCapture         bool    `json:"is_capture"`
	CapturedPieceType *string `json:"captured_piece_type"`
	CapturedValue     *int    `json:"captured_value"`
	GivesCheck        bool    `json:"gives_check"`
	IsCheckmate       bool    `json:"is_checkmate"`
	MoveNumber        int     `json:"move_number"`
}

type MoveClassification struct {
	IsSacrifice  bool   `json:"is_sacrifice"`
	IsBlunder    bool   `json:"is_blunder"`
	IsInaccuracy bool   `json:"is_inaccuracy"`
	IsGoodMove   bool   `json:"is_good_move"`
	IsBrilliant  bool   `json:"is_brilliant"`
	IsBookMove   bool   `json:"is_book_move"`
	Category     string `json:"category"`
}

type AlternativeMove struct {
	MoveStr   string `json:"move_str"`
	Score     int    `json:"score"`
	PieceType string `json:"piece_type"`
	IsCapture bool   `json:"is_capture"`
}

// MoveFeatureVector is the complete per-move feature vector from the engine's feature_extractor.
type MoveFeatureVector struct {
	PositionAnalysis   PositionAnalysis   `json:"position_analysis"`
	MoveMetadata       MoveMetadata       `json:"move_metadata"`
	SearchMetrics      SearchMetrics      `json:"search_metrics"`
	Classification     MoveClassification `json:"classification"`
	Alternatives       []AlternativeMove  `json:"alternatives"`
	PostMoveFEN        string             `json:"post_move_fen"`
	PostMoveInCheck    bool               `json:"post_move_in_check"`
	PostMoveIsGameOver bool               `json:"post_move_is_game_over"`
	PostMoveResult     string             `json:"post_move_result"`
}

// BatchEntry is a single FEN+move pair sent to the engine's batch_analyze endpoint.
type BatchEntry struct {
	FEN              string  `json:"fen"`
	MoveStr          string  `json:"move_str"`
	ExpertCommentary *string `json:"expert_commentary,omitempty"`
}

// BatchResult is what the engine returns per entry in a batch analysis.
type BatchResult struct {
	Features         MoveFeatureVector `json:"features"`
	ExpertCommentary *string           `json:"expert_commentary"`
}

// ── Engine Analysis Response (wraps what session.rs::analyze_position returns) ──

// AnalysisResponse is the combined JSON that the engine's analyze_position endpoint returns.
// It contains the full PositionAnalysis fields at the top level, plus optional move_features,
// search_score, search_nodes, search_depth injected by session.rs.
type AnalysisResponse struct {
	PositionAnalysis
	MoveFeatures *MoveFeatureVector `json:"move_features,omitempty"`
	SearchScore  int                `json:"search_score"`
	SearchNodes  uint64             `json:"search_nodes"`
	SearchDepth  int                `json:"search_depth"`
}

// ── Puzzle Detection structs (mirrors puzzle_detector.rs output) ──

// TacticalMotif represents a single detected tactical pattern in a position.
type TacticalMotif struct {
	MotifType   string   `json:"motif_type"`
	Description string   `json:"description"`
	Weight      uint32   `json:"weight"`
	Squares     []string `json:"squares"`
}

// PuzzleHint is a hint at a given specificity level (1=vague, 2=moderate, 3=specific).
type PuzzleHint struct {
	Level uint8  `json:"level"`
	Text  string `json:"text"`
}

// PuzzleDetectionResult is the full puzzle analysis result from the Rust engine's
// puzzle_detector module, returned by /engine/puzzle-detect via the state bridge.
type PuzzleDetectionResult struct {
	FEN             string          `json:"fen"`
	IsPuzzleWorthy  bool            `json:"is_puzzle_worthy"`
	MotifScore      uint32          `json:"motif_score"`
	Motifs          []TacticalMotif `json:"motifs"`
	Themes          []string        `json:"themes"`
	DifficultyElo   uint32          `json:"difficulty_elo"`
	DifficultyLabel string          `json:"difficulty_label"`
	Hints           []PuzzleHint    `json:"hints"`
	BestMove        *string         `json:"best_move"`
	Phase           string          `json:"phase"`
	PieceCount      uint32          `json:"piece_count"`
}
