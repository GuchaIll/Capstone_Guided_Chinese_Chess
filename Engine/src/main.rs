#[allow(non_snake_case)]
pub mod Game;
#[allow(non_snake_case)]
pub mod GameState;
#[allow(non_snake_case)]
pub mod AI {
    pub mod AI;
    pub mod AlphaBetaMinMax;
}
pub mod api;
pub mod session;

use std::sync::Arc;
use tokio::sync::Mutex;
use warp::Filter;

use crate::session::GameSession;
use crate::api::handle_websocket;

// ========================
//     MAIN
// ========================

#[tokio::main]
async fn main() {
    println!("Chinese Chess Engine Server starting...");

    // Create shared game session
    let session = Arc::new(Mutex::new(GameSession::new()));

    // WebSocket route: ws://localhost:8080/ws
    let ws_route = warp::path("ws")
        .and(warp::ws())
        .and(warp::any().map(move || session.clone()))
        .map(|ws: warp::ws::Ws, session: Arc<Mutex<GameSession>>| {
            ws.on_upgrade(move |socket| handle_websocket(socket, session))
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

    println!("Server running at http://localhost:8080");
    println!("WebSocket endpoint: ws://localhost:8080/ws");
    println!("Health check: http://localhost:8080/health");

    warp::serve(routes).run(([0, 0, 0, 0], 8080)).await;
}
