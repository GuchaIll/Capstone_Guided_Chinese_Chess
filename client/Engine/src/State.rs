

trait State
{
    fn state_name (&self) -> String;
    fn start (&mut self);
    fn update (&mut self);
    fn end (&mut self);
}

impl State for PreGameState {
    fn state_name (&self) -> String {
        return "PreGameState".to_string();
    }

    fn start (&mut self) {
    }

    fn update (&mut self) {

    }

    fn end (&mut self) {

    }
}

impl State for PostGameState {
    fn state_name (&self) -> String {
        return "PostGameState".to_string();
    }

    fn start (&mut self) {
    }

    fn update (&mut self) {

    }
}
