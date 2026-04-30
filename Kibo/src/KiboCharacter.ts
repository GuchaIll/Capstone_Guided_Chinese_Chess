import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { FBXLoader } from 'three/addons/loaders/FBXLoader.js';
import type { GLTF } from 'three/addons/loaders/GLTFLoader.js';
import type {
  CharacterState,
  CharacterEmote,
  FbxAnimation,
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
  private idleAnimationName: string = 'Idle';
  private onFinishedListener: (() => void) | null = null;

  model: THREE.Group | null = null;
  currentState: CharacterState = 'Idle';
  loaded = false;

  readonly states = STATES;
  readonly emotes = EMOTES;

  /**
   * Load the base character model (.fbx or .glb/.gltf) and set up the
   * AnimationMixer.  The model file format is detected from the URL extension.
   * @param url   Path to the model file
   * @param scene The Three.js scene to add the model to
   * @param scale Uniform scale applied to the loaded model (default 1).
   *              Mixamo FBX files are exported in centimetres — pass 0.01 to
   *              convert to Three.js metre units.
   */
  load(url: string, scene: THREE.Scene, scale = 100): Promise<void> {
    const isFbx = url.toLowerCase().endsWith('.fbx');

    const onLoaded = (group: THREE.Group, animations: THREE.AnimationClip[]) => {
      this.model = group;
      if (scale !== 1) this.model.scale.setScalar(scale);
      scene.add(this.model);

      this.mixer = new THREE.AnimationMixer(this.model);
      this.actions = {};

      for (const clip of animations) {
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

      // Start in Idle if that clip exists, otherwise just mark as loaded
      this.activeAction = this.actions['Idle'] ?? null;
      this.activeAction?.play();
      this.loaded = true;
    };

    return new Promise((resolve, reject) => {
      if (isFbx) {
        const loader = new FBXLoader();
        loader.load(
          url,
          (fbx) => {
            onLoaded(fbx, fbx.animations);
            resolve();
          },
          undefined,
          (error) => {
            console.error('Failed to load Kibo FBX model:', error);
            reject(error);
          },
        );
      } else {
        const loader = new GLTFLoader();
        loader.load(
          url,
          (gltf: GLTF) => {
            onLoaded(gltf.scene, gltf.animations);
            resolve();
          },
          undefined,
          (error) => {
            console.error('Failed to load Kibo GLB model:', error);
            reject(error);
          },
        );
      }
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
   * Load a single FBX animation file and register it under a logical name.
   * The animation clip is retargeted onto the already-loaded model skeleton.
   *
   * @param name  Logical AnimationName key used to address the clip
   * @param url   URL of the .fbx file (relative to the document root)
   */
  loadFbxAnimation(name: FbxAnimation, url: string): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.mixer || !this.model) {
        reject(new Error('loadFbxAnimation called before model is loaded'));
        return;
      }
      const loader = new FBXLoader();
      loader.load(
        url,
        (fbx) => {
          if (!fbx.animations.length) {
            console.warn(`[KiboCharacter] No animations found in ${url}`);
            resolve();
            return;
          }
          // Take the first clip and retarget it to our model's mixer
          const clip = fbx.animations[0];
          clip.name = name; // rename to our logical key
          // Strip root-motion position tracks so the character stays planted.
          // Mixamo bakes root translation into the Hips bone position track.
          clip.tracks = clip.tracks.filter(
            track => !(
              track.name.toLowerCase().includes('hips') &&
              track.name.endsWith('.position')
            ),
          );
          const action = this.mixer!.clipAction(clip);
          action.clampWhenFinished = true;
          action.loop = THREE.LoopOnce;
          this.actions[name] = action;
          resolve();
        },
        undefined,
        (error) => {
          console.error(`[KiboCharacter] Failed to load FBX ${url}:`, error);
          reject(error);
        },
      );
    });
  }

  /**
   * Set the FBX animation that loops as idle between trigger animations.
   * Adjusts the action to LoopRepeat and immediately transitions to it.
   */
  setFbxIdle(name: FbxAnimation): void {
    this.idleAnimationName = name;
    const action = this.actions[name];
    if (action) {
      action.loop = THREE.LoopRepeat;
      action.clampWhenFinished = false;
    }
    this.fadeToAction(name, 0.5);
  }

  /**
   * Play a one-shot FBX animation, then return to the idle animation.
   * Replaces any stale finished-listener from a previous call.
   */
  playFbx(name: FbxAnimation, duration = 0.3): void {
    if (!this.loaded) return;

    // Cancel any pending return-to-idle listener from a previous one-shot
    if (this.onFinishedListener) {
      this.mixer?.removeEventListener('finished', this.onFinishedListener);
      this.onFinishedListener = null;
    }

    this.fadeToAction(name, duration);

    this.onFinishedListener = () => {
      this.mixer?.removeEventListener('finished', this.onFinishedListener!);
      this.onFinishedListener = null;
      this.fadeToAction(this.idleAnimationName, duration);
    };
    this.mixer?.addEventListener('finished', this.onFinishedListener);
  }

  /**
   * Advance the animation mixer. Call once per frame.
   */
  update(delta: number): void {
    this.mixer?.update(delta);
  }

  // ---- private ----

  private fadeToAction(name: string, duration: number): void {
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
