// Xiangqi (Chinese Chess) Engine
// Main entry point

mod board;
mod Game;
mod GameState;

use board::Board;

fn main() {
    println!("Xiangqi Engine - Step 2: Coordinate System Implementation");
    println!("=========================================================\n");
    
    // Create a new board
    let mut board = Board::new();
    
    // Set to starting position
    board.reset();
    
    println!("Starting position:\n");
    println!("{}", board.to_string());
    
    println!("\n--- Game State Demo ---\n");
    
    // Create game state
    let mut game = GameState::GameState::new();
    game.start_game();
    
    println!("Game started with side to move: {:?}", game.get_current_side());
}

