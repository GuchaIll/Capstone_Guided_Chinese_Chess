use Serde::{Deserialize, Serialize};
use std::sync::mpsc;
mod handler;
mod ws;

//Reference: https://blog.logrocket.com/build-websocket-server-with-rust/
pub struct Client {
    pub user_id: usize,
    pub topics: Vec<String>,
    pub sender: Option<mpsc::UnboundedSender<std::result::Result<Message, warp::Error>>>,
}

#[derive(Deserialize, Serialize)]
pub struct RegisterResponse {
    user_id: usize,
}

#[derive(Deserialize, Serialize)]
pub struct RegisterResponse {
    url: String,
}

#[derive(Deserialize, Serialize)]
pub struct Event {
    topic: String,
    user_id: Option<usize>,
    message: String,
}

#[derive(Deserialize, Serialize)]
pub struct TopicsRequest {
    topics: Vec<String>,
}

type Result<T> = std::result::Result<T, warp::Error>;
type Clients = Arc<Mutex<HashMap<String, Client>>>;

#[tokio::main]
async fn main() {
    let clients: Clients = Arc::new(Mutex::new(HashMap::new()));
    let health_route = warp::path!("health").and_then(handler::health_handler);

    let register = warp::path("register");
    let register_routes = register("")

}
pub struct App{

}
fn main() {
    println!("Hello, world!");
}
