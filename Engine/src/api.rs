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

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use tokio::sync::{Mutex, mpsc};
use warp::ws::{Message, WebSocket};
use futures::{StreamExt, SinkExt};
use serde::{Deserialize, Serialize};
use std::time::Instant;

use crate::session::GameSession;

type ClientTx = mpsc::UnboundedSender<Message>;
pub type ClientRegistry = Arc<Mutex<HashMap<usize, ClientTx>>>;
static NEXT_CLIENT_ID: AtomicUsize = AtomicUsize::new(1);

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
        #[serde(default)]
        command_id: Option<String>,
    },
    #[serde(rename = "reset")]
    Reset {
        #[serde(default)]
        command_id: Option<String>,
    },
    #[serde(rename = "get_state")]
    GetState,
    #[serde(rename = "ai_move")]
    AiMove { difficulty: Option<u8> },
    #[serde(rename = "set_position")]
    SetPosition {
        fen: String,
        #[serde(default)]
        resume_seq: Option<u64>,
    },
    #[serde(rename = "legal_moves")]
    LegalMoves { square: String },
    #[serde(rename = "suggest")]
    Suggest { difficulty: Option<u8> },
    #[serde(rename = "suggest_for_fen")]
    SuggestForFen { fen: String, difficulty: Option<u8> },
    #[serde(rename = "analyze_position")]
    AnalyzePosition { fen: Option<String>, difficulty: Option<u8> },
    #[serde(rename = "batch_analyze")]
    BatchAnalyze { moves: Vec<BatchEntryMsg>, difficulty: Option<u8> },
    /// Detect tactical puzzle characteristics in a position.
    #[serde(rename = "detect_puzzle")]
    DetectPuzzle { fen: String, depth: Option<u8> },
    #[serde(rename = "validate_fen")]
    ValidateFen { fen: String },
    #[serde(rename = "legal_moves_for_fen")]
    LegalMovesForFen { fen: String, square: String },
    #[serde(rename = "make_move_for_fen")]
    MakeMoveForFen {
        fen: String,
        #[serde(rename = "move")]
        move_str: String,
    },
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
        seq: u64,
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
        #[serde(skip_serializing_if = "Option::is_none")]
        seq: Option<u64>,
        #[serde(skip_serializing_if = "Option::is_none")]
        command_id: Option<String>,
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
        seq: u64,
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
    #[serde(rename = "validation")]
    Validation {
        valid: bool,
        normalized_fen: Option<String>,
        reason: Option<String>,
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
    Error {
        message: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        command_id: Option<String>,
    },
}

// ========================
//     WEBSOCKET HANDLER
// ========================

pub async fn handle_websocket(ws: WebSocket, session: Arc<Mutex<GameSession>>, clients: ClientRegistry) {
    let client_id = NEXT_CLIENT_ID.fetch_add(1, Ordering::Relaxed);
    let (mut ws_tx, mut ws_rx) = ws.split();
    let (client_tx, mut client_rx) = mpsc::unbounded_channel::<Message>();

    clients.lock().await.insert(client_id, client_tx.clone());

    let writer = tokio::spawn(async move {
        while let Some(message) = client_rx.recv().await {
            if ws_tx.send(message).await.is_err() {
                break;
            }
        }
    });

    // Send initial state
    {
        let guard: tokio::sync::MutexGuard<'_, GameSession> = session.lock().await;
        let state_msg = guard.get_state_message();
        if let Ok(json) = serde_json::to_string(&state_msg) {
            let _ = client_tx.send(Message::text(json));
        }
    }

    println!("[WS] Client connected");

    // Handle incoming messages
    while let Some(result) = ws_rx.next().await {
        match result {
            Ok(msg) => {
                if msg.is_text() {
                    let text = msg.to_str().unwrap_or("");
                    let msg_start = Instant::now();

                    // Log the raw message (truncated for readability)
                    let log_text = if text.len() > 120 { &text[..120] } else { text };
                    println!("[WS] <<< {}", log_text);

                    let parsed = serde_json::from_str::<ClientMessage>(text);
                    let response = match &parsed {
                        Ok(client_msg) => {
                            let mut guard = session.lock().await;
                            handle_client_message(client_msg, &mut guard, &msg_start)
                        }
                        Err(e) => {
                            println!("[WS] Parse error: {}", e);
                            ServerMessage::Error {
                                message: format!("Invalid message format: {}", e),
                                command_id: None,
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
                        if client_tx.send(Message::text(json.clone())).is_err() {
                            eprintln!("[WS] Error sending message to client {}", client_id);
                            break;
                        }
                        if let Ok(client_msg) = &parsed {
                            if should_broadcast(client_msg, &response) {
                                broadcast_to_other_clients(client_id, &clients, &json).await;
                            }
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

    clients.lock().await.remove(&client_id);
    writer.abort();
    println!("[WS] Client disconnected");
}

// ========================
//     MESSAGE DISPATCH
// ========================

fn handle_client_message(
    client_msg: &ClientMessage,
    session: &mut GameSession,
    msg_start: &Instant,
) -> ServerMessage {
    match client_msg {
        ClientMessage::Move { ref move_str, ref command_id } => handle_move(session, move_str, command_id.as_deref()),
        ClientMessage::Reset { ref command_id } => handle_reset(session, command_id.as_deref()),
        ClientMessage::GetState => handle_get_state(session),
        ClientMessage::AiMove { difficulty } => handle_ai_move(session, *difficulty, msg_start),
        ClientMessage::SetPosition { ref fen, resume_seq } => handle_set_position(session, fen, *resume_seq),
        ClientMessage::LegalMoves { ref square } => handle_legal_moves(session, square),
        ClientMessage::Suggest { difficulty } => handle_suggest(session, *difficulty, msg_start),
        ClientMessage::SuggestForFen { ref fen, difficulty } => {
            handle_suggest_for_fen(session, fen, *difficulty)
        }
        ClientMessage::AnalyzePosition { ref fen, difficulty } => {
            handle_analyze_position(session, fen.as_deref(), *difficulty)
        }
        ClientMessage::BatchAnalyze { ref moves, difficulty } => {
            handle_batch_analyze(session, moves, *difficulty)
        }
        ClientMessage::DetectPuzzle { ref fen, depth } => {
            handle_detect_puzzle(session, fen, *depth)
        }
        ClientMessage::ValidateFen { ref fen } => handle_validate_fen(session, fen),
        ClientMessage::LegalMovesForFen { ref fen, ref square } => {
            handle_legal_moves_for_fen(session, fen, square)
        }
        ClientMessage::MakeMoveForFen { ref fen, ref move_str } => {
            handle_make_move_for_fen(session, fen, move_str)
        }
    }
}

fn should_broadcast(client_msg: &ClientMessage, response: &ServerMessage) -> bool {
    match (client_msg, response) {
        (ClientMessage::Move { .. }, ServerMessage::MoveResult { valid: true, .. }) => true,
        (ClientMessage::Reset { .. }, ServerMessage::State { .. }) => true,
        (ClientMessage::AiMove { .. }, ServerMessage::AiMoveResult { .. }) => true,
        _ => false,
    }
}

async fn broadcast_to_other_clients(origin_id: usize, clients: &ClientRegistry, json: &str) {
    let message = Message::text(json.to_string());
    let mut dead: Vec<usize> = Vec::new();

    {
        let locked = clients.lock().await;
        for (client_id, tx) in locked.iter() {
            if *client_id == origin_id {
                continue;
            }
            if tx.send(message.clone()).is_err() {
                dead.push(*client_id);
            }
        }
    }

    if !dead.is_empty() {
        let mut locked = clients.lock().await;
        for client_id in dead {
            locked.remove(&client_id);
        }
    }
}

// ========================
//     ROUTE HANDLERS
// ========================

/// POST move: validate and apply a player move
fn handle_move(session: &mut GameSession, move_str: &str, command_id: Option<&str>) -> ServerMessage {
    println!("[WS] Processing: move '{}'", move_str);
    let resp = session.apply_move(move_str, command_id);
    println!(
        "[WS] Move result: valid={}",
        matches!(&resp, ServerMessage::MoveResult { valid: true, .. })
    );
    resp
}

/// POST reset: reset the board to starting position
fn handle_reset(session: &mut GameSession, command_id: Option<&str>) -> ServerMessage {
    println!("[WS] Processing: reset");
    let resp = session.reset(command_id);
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
        ServerMessage::Error { message, .. } => {
            println!("[WS] AI move error: {}", message);
        }
        _ => {}
    }
    resp
}

/// POST set_position: set board to a FEN string
fn handle_set_position(session: &mut GameSession, fen: &str, resume_seq: Option<u64>) -> ServerMessage {
    println!("[WS] Processing: set_position");
    session.set_position(fen, resume_seq)
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
        ServerMessage::Error { message, .. } => {
            println!("[WS] Suggestion error: {}", message);
        }
        _ => {}
    }
    resp
}

fn handle_suggest_for_fen(
    session: &mut GameSession,
    fen: &str,
    difficulty: Option<u8>,
) -> ServerMessage {
    println!("[WS] Processing: suggest_for_fen (difficulty={:?})", difficulty);
    session.get_suggestion_for_fen(fen, difficulty)
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

fn handle_validate_fen(session: &mut GameSession, fen: &str) -> ServerMessage {
    println!("[WS] Processing: validate_fen");
    session.validate_fen_preview(fen)
}

fn handle_legal_moves_for_fen(session: &mut GameSession, fen: &str, square: &str) -> ServerMessage {
    println!("[WS] Processing: legal_moves_for_fen for '{}'", square);
    session.get_legal_moves_for_piece_at_fen(fen, square)
}

fn handle_make_move_for_fen(session: &mut GameSession, fen: &str, move_str: &str) -> ServerMessage {
    println!("[WS] Processing: make_move_for_fen '{}'", move_str);
    session.preview_move_at_fen(fen, move_str)
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn authoritative_gameplay_messages_broadcast_to_other_clients() {
        assert!(should_broadcast(
            &ClientMessage::Move {
                move_str: "b0c2".to_string(),
                command_id: Some("cmd-1".to_string()),
            },
            &ServerMessage::MoveResult {
                valid: true,
                fen: "fen".to_string(),
                reason: None,
                move_str: Some("b0c2".to_string()),
                is_check: false,
                result: "in_progress".to_string(),
                seq: Some(1),
                command_id: Some("cmd-1".to_string()),
            },
        ));

        assert!(should_broadcast(
            &ClientMessage::Reset {
                command_id: Some("cmd-2".to_string()),
            },
            &ServerMessage::State {
                fen: "fen".to_string(),
                side_to_move: "red".to_string(),
                result: "in_progress".to_string(),
                is_check: false,
                seq: 2,
            },
        ));

        assert!(should_broadcast(
            &ClientMessage::AiMove {
                difficulty: Some(2),
            },
            &ServerMessage::AiMoveResult {
                move_str: "h7e7".to_string(),
                fen: "fen".to_string(),
                score: 12,
                nodes_searched: 42,
                is_check: false,
                result: "in_progress".to_string(),
                seq: 3,
            },
        ));
    }

    #[test]
    fn helper_and_invalid_messages_do_not_broadcast() {
        assert!(!should_broadcast(
            &ClientMessage::Move {
                move_str: "a9a5".to_string(),
                command_id: Some("cmd-3".to_string()),
            },
            &ServerMessage::MoveResult {
                valid: false,
                fen: "fen".to_string(),
                reason: Some("Invalid move".to_string()),
                move_str: None,
                is_check: false,
                result: "in_progress".to_string(),
                seq: None,
                command_id: Some("cmd-3".to_string()),
            },
        ));

        assert!(!should_broadcast(
            &ClientMessage::LegalMoves {
                square: "b0".to_string(),
            },
            &ServerMessage::LegalMovesResult {
                square: "b0".to_string(),
                targets: vec!["c2".to_string()],
            },
        ));

        assert!(!should_broadcast(
            &ClientMessage::ValidateFen {
                fen: "fen".to_string(),
            },
            &ServerMessage::Validation {
                valid: true,
                normalized_fen: Some("fen".to_string()),
                reason: None,
            },
        ));

        assert!(!should_broadcast(
            &ClientMessage::MakeMoveForFen {
                fen: "fen".to_string(),
                move_str: "b0c2".to_string(),
            },
            &ServerMessage::MoveResult {
                valid: true,
                fen: "fen2".to_string(),
                reason: None,
                move_str: Some("b0c2".to_string()),
                is_check: false,
                result: "in_progress".to_string(),
                seq: None,
                command_id: None,
            },
        ));
    }

    #[tokio::test]
    async fn broadcast_skips_origin_and_drops_dead_clients() {
        let clients: ClientRegistry = Arc::new(Mutex::new(HashMap::new()));
        let (origin_tx, mut origin_rx) = mpsc::unbounded_channel();
        let (observer_tx, mut observer_rx) = mpsc::unbounded_channel();
        let (dead_tx, dead_rx) = mpsc::unbounded_channel::<Message>();

        clients.lock().await.insert(1, origin_tx);
        clients.lock().await.insert(2, observer_tx);
        clients.lock().await.insert(3, dead_tx);
        drop(dead_rx);

        broadcast_to_other_clients(1, &clients, r#"{"type":"move_result"}"#).await;

        assert!(origin_rx.try_recv().is_err());

        let received = observer_rx.try_recv().expect("observer should receive broadcast");
        assert_eq!(received.to_str().expect("text frame"), r#"{"type":"move_result"}"#);

        let locked = clients.lock().await;
        assert!(locked.contains_key(&1));
        assert!(locked.contains_key(&2));
        assert!(!locked.contains_key(&3));
    }
}
