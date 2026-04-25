#[allow(non_snake_case)]
pub mod Game;
#[allow(non_snake_case)]
pub mod GameState;
#[allow(non_snake_case)]
pub mod AI {
    pub mod AI;
    pub mod AlphaBetaMinMax;
    pub mod piece_square_tables;
    pub mod position_analyzer;
    pub mod feature_extractor;
    pub mod explainability_gen;
    pub mod puzzle_detector;
}
pub mod api;
pub mod session;

use std::sync::Arc;
use std::{env, net::IpAddr};
use tokio::sync::Mutex;
use warp::Filter;

use crate::session::GameSession;
use crate::api::{handle_websocket, ClientRegistry};

// ========================
//     MAIN
// ========================

#[tokio::main]
async fn main() {
    println!("Chinese Chess Engine Server starting...");

    let bind_host = env::var("ENGINE_BIND_HOST")
        .ok()
        .and_then(|value| value.parse::<IpAddr>().ok())
        .unwrap_or_else(|| "127.0.0.1".parse().expect("valid default bind host"));
    let bind_port = env::var("ENGINE_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or(8080);

    // Create shared game session
    let session = Arc::new(Mutex::new(GameSession::new()));
    let clients: ClientRegistry = Arc::new(Mutex::new(std::collections::HashMap::new()));

    // WebSocket route: ws://localhost:8080/ws
    let ws_route = warp::path("ws")
        .and(warp::ws())
        .and(warp::any().map(move || session.clone()))
        .and(warp::any().map(move || clients.clone()))
        .map(|ws: warp::ws::Ws, session: Arc<Mutex<GameSession>>, clients: ClientRegistry| {
            ws.on_upgrade(move |socket| handle_websocket(socket, session, clients))
        });

    // CORS configuration
    let cors = warp::cors()
        .allow_any_origin()
        .allow_headers(vec!["content-type"])
        .allow_methods(vec!["GET", "POST", "OPTIONS"]);

    // Health check route: GET /health
    let health = warp::path("health")
        .map(|| warp::reply::json(&serde_json::json!({"status": "ok"})));

    let routes = ws_route.or(health).with(cors);

    println!("Server running at http://{}:{}", bind_host, bind_port);
    println!("WebSocket endpoint: ws://{}:{}/ws", bind_host, bind_port);
    println!("Health check: http://{}:{}/health", bind_host, bind_port);

    warp::serve(routes).run((bind_host, bind_port)).await;
}
