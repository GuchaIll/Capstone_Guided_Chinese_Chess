// GameState module - manages overall game state including board, history, and captured pieces
use crate::board::{Board, Side};

pub enum GameStage {
    PreGame,
    InGame,
    PostGame,
}

pub struct GameState {
    pub stage: GameStage,
    pub board: Board,
    pub history: Vec<String>,  // Store moves as strings for now
    pub captured_red: Vec<u8>,
    pub captured_black: Vec<u8>,
}

impl GameState {
    pub fn new() -> GameState {
        GameState {
            stage: GameStage::PreGame,
            board: Board::new(),
            history: vec![],
            captured_red: vec![],
            captured_black: vec![],
        }
    }
    
    pub fn start_game(&mut self) {
        self.stage = GameStage::InGame;
        self.board.reset();
        self.history.clear();
        self.captured_red.clear();
        self.captured_black.clear();
    }
    
    pub fn reset(&mut self) {
        self.stage = GameStage::PreGame;
        self.board = Board::new();
        self.history.clear();
        self.captured_red.clear();
        self.captured_black.clear();
    }
    
    pub fn get_current_side(&self) -> &Side {
        &self.board.side
    }
}

impl Default for GameState {
    fn default() -> Self {
        Self::new()
    }
}
