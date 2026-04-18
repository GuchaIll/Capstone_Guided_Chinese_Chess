/**
 * Animation state categories for the Kibo character.
 * States are looping animations; emotes are one-shot actions.
 */

/** Looping base animation states */
export type CharacterState = 'Idle' | 'Walking' | 'Running' | 'Dance' | 'Death' | 'Sitting' | 'Standing';

/** One-shot emote animations */
export type CharacterEmote = 'Jump' | 'Yes' | 'No' | 'Wave' | 'Punch' | 'ThumbsUp';

/** Any playable animation clip name */
export type AnimationName = CharacterState | CharacterEmote;

/** Command sent from the orchestration engine to control Kibo */
export interface KiboCommand {
  type: 'setState' | 'playEmote' | 'setExpression' | 'getStatus';
  /** Animation state name (for setState) */
  state?: CharacterState;
  /** Emote name (for playEmote) */
  emote?: CharacterEmote;
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
