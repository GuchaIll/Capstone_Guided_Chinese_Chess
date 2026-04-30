/**
 * Animation state categories for the Kibo character.
 * States are looping animations; emotes are one-shot actions.
 */

/** Looping base animation states */
export type CharacterState = 'Idle' | 'Walking' | 'Running' | 'Dance' | 'Death' | 'Sitting' | 'Standing';

/** One-shot emote animations (from RobotExpressive.glb) */
export type CharacterEmote = 'Jump' | 'Yes' | 'No' | 'Wave' | 'Punch' | 'ThumbsUp';

/**
 * One-shot FBX animations loaded from Kibo/public/models/*.fbx.
 * These are driven by game events via the Kibo trigger system.
 */
export type FbxAnimation =
  | 'Cheering'             // Cheering.fbx  — player wins / high-accuracy move
  | 'KnockedOut'           // Knocked Out.fbx — player loses
  | 'FistPump'             // Fist Pump.fbx — avoids blunder / material gain
  | 'StandingClap'         // Standing Clap.fbx — avoids blunder
  | 'BootyDance'           // Booty Hip Hop Dance.fbx — optimal move
  | 'Dancing'              // Dancing.fbx — optimal move
  | 'NorthernSpin'         // Northern Soul Spin.fbx — optimal move
  | 'SittingDisbelief'     // Sitting Disbelief.fbx — misses strong move
  | 'Crying'               // Crying.fbx — misses strong move
  | 'Angry'                // Angry.fbx — illegal move attempt
  | 'ThoughtfulHeadShake'; // Gestures Pack Basic/thoughtful head shake.fbx — idle loop

/** Maps each FbxAnimation key to the filename under public/models/ */
export const FBX_FILES: Record<FbxAnimation, string> = {
  Cheering:             'Cheering.fbx',
  KnockedOut:           'Knocked Out.fbx',
  FistPump:             'Fist Pump.fbx',
  StandingClap:         'Standing Clap.fbx',
  BootyDance:           'Booty Hip Hop Dance.fbx',
  Dancing:              'Dancing.fbx',
  NorthernSpin:         'Northern Soul Spin.fbx',
  SittingDisbelief:     'Sitting Disbelief.fbx',
  Crying:               'Crying.fbx',
  Angry:                'Angry.fbx',
  ThoughtfulHeadShake:  'Gestures Pack Basic/thoughtful head shake.fbx',
};

/** Any playable animation clip name */
export type AnimationName = CharacterState | CharacterEmote | FbxAnimation;

/**
 * Game event triggers that map to Kibo animations.
 * Sent by the state bridge via /ws/kibo.
 */
export type KiboTrigger =
  | 'player_win'       // game result — player wins
  | 'player_lose'      // game result — player loses
  | 'material_gain'    // large material capture / evaluation swing
  | 'high_accuracy'    // move closely matches engine best
  | 'avoids_blunder'   // player avoids a clearly losing move
  | 'optimal_move'     // player finds the best move in position
  | 'misses_move'      // player overlooks a clearly better option
  | 'illegal_move';    // player attempts an invalid move

/** Command sent from the orchestration engine to control Kibo */
export interface KiboCommand {
  type: 'setState' | 'playEmote' | 'playFbx' | 'playTrigger' | 'setExpression' | 'getStatus';
  /** Animation state name (for setState) */
  state?: CharacterState;
  /** Emote name (for playEmote) */
  emote?: CharacterEmote;
  /** FBX animation name (for playFbx — plays specific clip directly) */
  fbx?: FbxAnimation;
  /** Game trigger (for playTrigger — animation chosen by animationMap) */
  trigger?: KiboTrigger;
  /** Expression morph target name and weight (for setExpression) */
  expression?: { name: string; weight: number };
  /** Transition duration in seconds */
  duration?: number;
}

/** Status response sent back to the orchestration engine */
export interface KiboStatus {
  currentState: CharacterState;
  modelLoaded: boolean;
  availableStates: CharacterState[];
  availableEmotes: CharacterEmote[];
  availableExpressions: string[];
}
