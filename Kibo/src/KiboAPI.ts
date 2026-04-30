import { KiboCharacter } from './KiboCharacter';
import type { KiboCommand, KiboStatus, CharacterState, CharacterEmote, FbxAnimation } from './types';
import { pickAnimation } from './animationMap';

/**
 * KiboAPI – the control surface the orchestration engine uses to stage
 * the Kibo character.
 *
 * Supports two integration modes:
 *  1. **Direct JS** – import and call methods on the singleton.
 *  2. **WebSocket** – connect from the engine and send JSON KiboCommands.
 *
 * The API is also exposed on `window.kiboAPI` for console/debug use.
 */
export class KiboAPI {
  private character: KiboCharacter;
  private ws: WebSocket | null = null;

  constructor(character: KiboCharacter) {
    this.character = character;

    // Expose globally for orchestrator integration / debugging
    (window as unknown as Record<string, unknown>).kiboAPI = this;
  }

  // ─── Direct JS interface ───────────────────────────────────────

  setState(state: CharacterState, duration?: number): void {
    this.character.setState(state, duration);
  }

  playEmote(emote: CharacterEmote, duration?: number): void {
    this.character.playEmote(emote, duration);
  }

  playFbx(name: FbxAnimation, duration?: number): void {
    this.character.playFbx(name, duration);
  }

  setExpression(name: string, weight: number): void {
    this.character.setExpression(name, weight);
  }

  getStatus(): KiboStatus {
    return {
      currentState: this.character.currentState,
      modelLoaded: this.character.loaded,
      availableStates: [...this.character.states],
      availableEmotes: [...this.character.emotes],
      availableExpressions: this.character.getExpressionNames(),
    };
  }

  // ─── WebSocket interface ───────────────────────────────────────

  /**
   * Start listening for commands from the orchestration engine over WS.
   * @param url WebSocket URL, e.g. "ws://localhost:8080/ws/kibo"
   */
  connectWebSocket(url: string): void {
    this.ws = new WebSocket(url);

    this.ws.addEventListener('open', () => {
      console.log('[KiboAPI] WebSocket connected to', url);
      this.sendStatus();
    });

    this.ws.addEventListener('message', (event) => {
      try {
        const cmd: KiboCommand = JSON.parse(event.data);
        this.handleCommand(cmd);
      } catch (err) {
        console.error('[KiboAPI] Invalid message:', event.data, err);
      }
    });

    this.ws.addEventListener('close', () => {
      console.log('[KiboAPI] WebSocket disconnected');
      this.ws = null;
    });

    this.ws.addEventListener('error', (err) => {
      console.error('[KiboAPI] WebSocket error:', err);
    });
  }

  /**
   * Process an incoming KiboCommand (from WS or direct call).
   */
  handleCommand(cmd: KiboCommand): void {
    switch (cmd.type) {
      case 'setState':
        if (cmd.state) this.setState(cmd.state, cmd.duration);
        break;
      case 'playEmote':
        if (cmd.emote) this.playEmote(cmd.emote, cmd.duration);
        break;
      case 'playFbx':
        if (cmd.fbx) this.playFbx(cmd.fbx, cmd.duration);
        break;
      case 'playTrigger':
        if (cmd.trigger) {
          const anim = pickAnimation(cmd.trigger);
          if (anim) {
            this.playFbx(anim, cmd.duration);
          } else {
            console.warn('[KiboAPI] No animation mapped for trigger:', cmd.trigger);
          }
        }
        break;
      case 'setExpression':
        if (cmd.expression) {
          this.setExpression(cmd.expression.name, cmd.expression.weight);
        }
        break;
      case 'getStatus':
        this.sendStatus();
        break;
    }
  }

  private sendStatus(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(this.getStatus()));
    }
  }
}
