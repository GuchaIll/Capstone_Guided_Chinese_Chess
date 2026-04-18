import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type {
  CharacterState,
  CharacterEmote,
  AnimationName,
} from './types';

const STATES: CharacterState[] = ['Idle', 'Walking', 'Running', 'Dance', 'Death', 'Sitting', 'Standing'];
const EMOTES: CharacterEmote[] = ['Jump', 'Yes', 'No', 'Wave', 'Punch', 'ThumbsUp'];

/**
 * Manages the Kibo 3D character: model loading, animation mixing,
 * state transitions, emotes, and facial expressions.
 */
export class KiboCharacter {
  private mixer: THREE.AnimationMixer | null = null;
  private actions: Record<string, THREE.AnimationAction> = {};
  private activeAction: THREE.AnimationAction | null = null;
  private previousAction: THREE.AnimationAction | null = null;
  private face: THREE.Mesh | null = null;

  model: THREE.Group | null = null;
  currentState: CharacterState = 'Idle';
  loaded = false;

  readonly states = STATES;
  readonly emotes = EMOTES;

  /**
   * Load a GLTF/GLB model and set up all animation clips.
   * @param url Path to the .glb/.gltf model file
   * @param scene The Three.js scene to add the model to
   */
  load(url: string, scene: THREE.Scene): Promise<void> {
    return new Promise((resolve, reject) => {
      const loader = new GLTFLoader();
      loader.load(
        url,
        (gltf) => {
          this.model = gltf.scene;
          scene.add(this.model);

          this.mixer = new THREE.AnimationMixer(this.model);
          this.actions = {};

          for (const clip of gltf.animations) {
            const action = this.mixer.clipAction(clip);
            this.actions[clip.name] = action;

            // One-shot animations: emotes and the tail-end states
            if (
              EMOTES.includes(clip.name as CharacterEmote) ||
              STATES.indexOf(clip.name as CharacterState) >= 4
            ) {
              action.clampWhenFinished = true;
              action.loop = THREE.LoopOnce;
            }
          }

          // Try to find a face mesh for morph targets (model-dependent)
          this.face = this.model.getObjectByName('Head_4') as THREE.Mesh | null;

          // Start in Idle
          this.activeAction = this.actions['Idle'] ?? null;
          this.activeAction?.play();
          this.loaded = true;

          resolve();
        },
        undefined,
        (error) => {
          console.error('Failed to load Kibo model:', error);
          reject(error);
        }
      );
    });
  }

  /**
   * Transition to a looping base state.
   */
  setState(state: CharacterState, duration = 0.5): void {
    if (!this.loaded) return;
    this.currentState = state;
    this.fadeToAction(state, duration);
  }

  /**
   * Play a one-shot emote, then return to the current state.
   */
  playEmote(emote: CharacterEmote, duration = 0.2): void {
    if (!this.loaded) return;

    this.fadeToAction(emote, duration);

    const onFinished = () => {
      this.mixer?.removeEventListener('finished', onFinished);
      this.fadeToAction(this.currentState, duration);
    };

    this.mixer?.addEventListener('finished', onFinished);
  }

  /**
   * Set a facial expression morph target weight.
   */
  setExpression(name: string, weight: number): void {
    if (!this.face) return;
    const dict = this.face.morphTargetDictionary;
    const influences = this.face.morphTargetInfluences;
    if (!dict || !influences) return;
    const index = dict[name];
    if (index !== undefined) {
      influences[index] = Math.max(0, Math.min(1, weight));
    }
  }

  /**
   * Get available expression names from the model.
   */
  getExpressionNames(): string[] {
    if (!this.face?.morphTargetDictionary) return [];
    return Object.keys(this.face.morphTargetDictionary);
  }

  /**
   * Advance the animation mixer. Call once per frame.
   */
  update(delta: number): void {
    this.mixer?.update(delta);
  }

  // ---- private ----

  private fadeToAction(name: AnimationName | string, duration: number): void {
    this.previousAction = this.activeAction;
    this.activeAction = this.actions[name] ?? null;

    if (!this.activeAction) return;

    if (this.previousAction && this.previousAction !== this.activeAction) {
      this.previousAction.fadeOut(duration);
    }

    this.activeAction
      .reset()
      .setEffectiveTimeScale(1)
      .setEffectiveWeight(1)
      .fadeIn(duration)
      .play();
  }
}
