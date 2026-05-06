export type TurnPhase =
  | 'player_idle'       // Player's turn, no pending move yet
  | 'player_pending'    // Player has a tentative move; can take back or End Turn
  | 'awaiting_engine'   // Move committed; waiting for engine response (player or AI)
  | 'engine_done';      // Engine moved; player must End Turn to acknowledge
