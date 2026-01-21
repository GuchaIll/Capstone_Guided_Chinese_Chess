
pub enum Side {
    Red,
    Black
}


pub enum GameStage {
    PreGame,
    InGame,
    PostGame
}

pub struct GameState {
    stage: GameStage,
    turn: Side,
    board: Vec<Vec<u8>>,
    captured: Vec<Vec<u8>>,
    history: Vec<Vec<Vec<u8>>>
}


impl GameState {
    fn new () -> GameState {
        GameState {
            stage: GameStage::PreGame,
            turn: Side::Red,
            board: vec![vec![0; 8]; 8],
            captured: vec![vec![0; 8]; 8],
            history: vec![]
        }
    }
    fn update_board (&mut self, new_board: Vec<Vec<u8>>) {
        self.board = new_board;

    }

    fn capture (&mut self, piece: u8, pos: (usize, usize)) {


    }

    fn reset (&mut self) {
        self.board = vec![vec![0; 8]; 8];
        self.GameStage = GameStage::PreGame;

    }
}