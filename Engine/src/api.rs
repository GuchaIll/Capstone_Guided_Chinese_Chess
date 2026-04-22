// ========================
//     API MODULE
// ========================
//
// WebSocket Endpoint: ws://localhost:8080/ws
// HTTP Endpoint:      GET /health
//
// WebSocket Message Protocol:
//
// 1. move          { type: "move", move: "e3e4" }
//                  → move_result { valid, fen, reason?, move?, is_check, result }
//                  Player submits a move. Validates and applies it.
//
// 2. reset         { type: "reset" }
//                  → state { fen, side_to_move, result, is_check }
//                  Resets the board to starting position.
//
// 3. get_state     { type: "get_state" }
//                  → state { fen, side_to_move, result, is_check }
//                  Returns current board state.
//
// 4. ai_move       { type: "ai_move", difficulty?: u8 }
//                  → ai_move { move, fen, score, nodes_searched, is_check, result }
//                  AI generates and applies a move.
//
// 5. set_position  { type: "set_position", fen: "..." }
//                  → state { fen, side_to_move, result, is_check }
//                  Sets board to a specific FEN position.
//
// 6. legal_moves   { type: "legal_moves", square: "e0" }
//                  → legal_moves { square, targets: ["e1", "d0", ...] }
//                  Returns legal target squares for the piece at given square.
//
// 7. suggest       { type: "suggest", difficulty?: u8 }
//                  → suggestion { move, from, to, score, nodes_searched }
//                  AI generates best move suggestion without applying it.
//

use std::sync::Arc;
use tokio::sync::Mutex;
use warp::ws::{Message, WebSocket};
use futures::{StreamExt, SinkExt};
use serde::{Deserialize, Serialize};
use std::time::Instant;

use crate::session::GameSession;

// ========================
//     MESSAGE TYPES
// ========================

#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
pub enum ClientMessage {
    #[serde(rename = "move")]
    Move {
        #[serde(rename = "move")]
        move_str: String,
    },
    #[serde(rename = "reset")]
    Reset,
    #[serde(rename = "get_state")]
    GetState,
    #[serde(rename = "ai_move")]
    AiMove { difficulty: Option<u8> },
    #[serde(rename = "set_position")]
    SetPosition { fen: String },
    #[serde(rename = "legal_moves")]
    LegalMoves { square: String },
    #[serde(rename = "suggest")]
    Suggest { difficulty: Option<u8> },
    #[serde(rename = "analyze_position")]
    AnalyzePosition { fen: Option<String>, difficulty: Option<u8> },
    #[serde(rename = "batch_analyze")]
    BatchAnalyze { moves: Vec<BatchEntryMsg>, difficulty: Option<u8> },
    /// Detect tactical puzzle characteristics in a position.
    #[serde(rename = "detect_puzzle")]
    DetectPuzzle { fen: String, depth: Option<u8> },
}

#[derive(Debug, Deserialize)]
pub struct BatchEntryMsg {
    pub fen: String,
    pub move_str: String,
    pub expert_commentary: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(tag = "type")]
pub enum ServerMessage {
    #[serde(rename = "state")]
    State {
        fen: String,
        side_to_move: String,
        result: String,
        is_check: bool,
    },
    #[serde(rename = "move_result")]
    MoveResult {
        valid: bool,
        fen: String,
        reason: Option<String>,
        #[serde(rename = "move")]
        move_str: Option<String>,
        is_check: bool,
        result: String,
    },
    #[serde(rename = "ai_move")]
    AiMoveResult {
        #[serde(rename = "move")]
        move_str: String,
        fen: String,
        score: i32,
        nodes_searched: u64,
        is_check: bool,
        result: String,
    },
    #[serde(rename = "legal_moves")]
    LegalMovesResult {
        square: String,
        targets: Vec<String>,
    },
    #[serde(rename = "suggestion")]
    Suggestion {
        #[serde(rename = "move")]
        move_str: String,
        from: String,
        to: String,
        score: i32,
        nodes_searched: u64,
    },
    #[serde(rename = "analysis")]
    Analysis {
        features: serde_json::Value,
    },
    #[serde(rename = "batch_analysis")]
    BatchAnalysis {
        results: Vec<serde_json::Value>,
        total_moves: usize,
    },
    #[serde(rename = "puzzle_detection")]
    PuzzleDetection {
        detection: serde_json::Value,
    },
    #[serde(rename = "error")]
    Error { message: String },
}

// ========================
//     WEBSOCKET HANDLER
// ========================

pub async fn handle_websocket(ws: WebSocket, session: Arc<Mutex<GameSession>>) {
    let (mut tx, mut rx) = ws.split();

    // Send initial state
    {
        let guard: tokio::sync::MutexGuard<'_, GameSession> = session.lock().await;
        let state_msg = guard.get_state_message();
        if let Ok(json) = serde_json::to_string(&state_msg) {
            let _ = tx.send(Message::text(json)).await;
        }
    }

    println!("[WS] Client connected");

    // Handle incoming messages
    while let Some(result) = rx.next().await {
        match result {
            Ok(msg) => {
                if msg.is_text() {
                    let text = msg.to_str().unwrap_or("");
                    let msg_start = Instant::now();

                    // Log the raw message (truncated for readability)
                    let log_text = if text.len() > 120 { &text[..120] } else { text };
                    println!("[WS] <<< {}", log_text);

                    let response = match serde_json::from_str::<ClientMessage>(text) {
                        Ok(client_msg) => {
                            let mut guard = session.lock().await;
                            handle_client_message(client_msg, &mut guard, &msg_start)
                        }
                        Err(e) => {
                            println!("[WS] Parse error: {}", e);
                            ServerMessage::Error {
                                message: format!("Invalid message format: {}", e),
                            }
                        }
                    };

                    let total_elapsed = msg_start.elapsed();
                    if total_elapsed.as_millis() > 100 {
                        println!(
                            "[WS] >>> Response sent (took {:.1}ms)",
                            total_elapsed.as_secs_f64() * 1000.0
                        );
                    }

                    if let Ok(json) = serde_json::to_string(&response) {
                        if let Err(e) = tx.send(Message::text(json)).await {
                            eprintln!("[WS] Error sending message: {}", e);
                            break;
                        }
                    }
                } else if msg.is_close() {
                    println!("[WS] Client requested close");
                    break;
                }
            }
            Err(e) => {
                eprintln!("[WS] WebSocket error: {}", e);
                break;
            }
        }
    }

    println!("[WS] Client disconnected");
}

// ========================
//     MESSAGE DISPATCH
// ========================

fn handle_client_message(
    client_msg: ClientMessage,
    session: &mut GameSession,
    msg_start: &Instant,
) -> ServerMessage {
    match client_msg {
        ClientMessage::Move { ref move_str } => handle_move(session, move_str),
        ClientMessage::Reset => handle_reset(session),
        ClientMessage::GetState => handle_get_state(session),
        ClientMessage::AiMove { difficulty } => handle_ai_move(session, difficulty, msg_start),
        ClientMessage::SetPosition { ref fen } => handle_set_position(session, fen),
        ClientMessage::LegalMoves { ref square } => handle_legal_moves(session, square),
        ClientMessage::Suggest { difficulty } => handle_suggest(session, difficulty, msg_start),
        ClientMessage::AnalyzePosition { ref fen, difficulty } => {
            handle_analyze_position(session, fen.as_deref(), difficulty)
        }
        ClientMessage::BatchAnalyze { ref moves, difficulty } => {
            handle_batch_analyze(session, moves, difficulty)
        }
        ClientMessage::DetectPuzzle { ref fen, depth } => {
            handle_detect_puzzle(session, fen, depth)
        }
    }
}

// ========================
//     ROUTE HANDLERS
// ========================

/// POST move: validate and apply a player move
fn handle_move(session: &mut GameSession, move_str: &str) -> ServerMessage {
    println!("[WS] Processing: move '{}'", move_str);
    let resp = session.apply_move(move_str);
    println!(
        "[WS] Move result: valid={}",
        matches!(&resp, ServerMessage::MoveResult { valid: true, .. })
    );
    resp
}

/// POST reset: reset the board to starting position
fn handle_reset(session: &mut GameSession) -> ServerMessage {
    println!("[WS] Processing: reset");
    session.reset();
    let resp = session.get_state_message();
    println!("[WS] Board reset complete");
    resp
}

/// GET state: return current board state
fn handle_get_state(session: &GameSession) -> ServerMessage {
    println!("[WS] Processing: get_state");
    session.get_state_message()
}

/// POST ai_move: AI generates and applies a move
fn handle_ai_move(
    session: &mut GameSession,
    difficulty: Option<u8>,
    msg_start: &Instant,
) -> ServerMessage {
    println!("[WS] Processing: ai_move (difficulty={:?})", difficulty);
    println!("[WS] AI search starting...");
    let resp = session.generate_ai_move(difficulty);
    let elapsed = msg_start.elapsed();
    match &resp {
        ServerMessage::AiMoveResult {
            move_str,
            score,
            nodes_searched,
            ..
        } => {
            println!(
                "[WS] AI move complete: {} (score={}, nodes={}, time={:.1}ms)",
                move_str,
                score,
                nodes_searched,
                elapsed.as_secs_f64() * 1000.0
            );
        }
        ServerMessage::Error { message } => {
            println!("[WS] AI move error: {}", message);
        }
        _ => {}
    }
    resp
}

/// POST set_position: set board to a FEN string
fn handle_set_position(session: &mut GameSession, fen: &str) -> ServerMessage {
    println!("[WS] Processing: set_position");
    session.set_position(fen)
}

/// GET legal_moves: return legal target squares for a piece
fn handle_legal_moves(session: &mut GameSession, square: &str) -> ServerMessage {
    println!("[WS] Processing: legal_moves for '{}'", square);
    let resp = session.get_legal_moves_for_piece(square);
    if let ServerMessage::LegalMovesResult { ref targets, .. } = resp {
        println!("[WS] Legal targets: {} moves", targets.len());
    }
    resp
}

/// POST suggest: AI generates a suggestion without applying it
fn handle_suggest(
    session: &mut GameSession,
    difficulty: Option<u8>,
    msg_start: &Instant,
) -> ServerMessage {
    println!("[WS] Processing: suggest (difficulty={:?})", difficulty);
    println!("[WS] Suggestion search starting...");
    let resp = session.get_suggestion(difficulty);
    let elapsed = msg_start.elapsed();
    match &resp {
        ServerMessage::Suggestion {
            move_str,
            score,
            nodes_searched,
            ..
        } => {
            println!(
                "[WS] Suggestion complete: {} (score={}, nodes={}, time={:.1}ms)",
                move_str,
                score,
                nodes_searched,
                elapsed.as_secs_f64() * 1000.0
            );
        }
        ServerMessage::Error { message } => {
            println!("[WS] Suggestion error: {}", message);
        }
        _ => {}
    }
    resp
}

/// POST analyze_position: deep position analysis with feature extraction
fn handle_analyze_position(
    session: &mut GameSession,
    fen: Option<&str>,
    difficulty: Option<u8>,
) -> ServerMessage {
    println!("[WS] Processing: analyze_position (fen={:?}, difficulty={:?})", fen, difficulty);
    session.analyze_position(fen, difficulty)
}

/// POST detect_puzzle: analyse a position for tactical puzzle characteristics
fn handle_detect_puzzle(
    session: &mut GameSession,
    fen: &str,
    depth: Option<u8>,
) -> ServerMessage {
    let d = depth.unwrap_or(5);
    println!("[WS] Processing: detect_puzzle (fen={:?}, depth={})", fen, d);
    session.detect_puzzle(fen, d)
}

/// POST batch_analyze: analyze a full game (list of FEN+move pairs)
fn handle_batch_analyze(
    session: &mut GameSession,
    moves: &[BatchEntryMsg],
    difficulty: Option<u8>,
) -> ServerMessage {
    println!("[WS] Processing: batch_analyze ({} moves, difficulty={:?})", moves.len(), difficulty);
    session.batch_analyze(moves, difficulty)
}
