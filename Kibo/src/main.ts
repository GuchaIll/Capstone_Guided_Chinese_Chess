import { createScene } from './scene';
import { KiboCharacter } from './KiboCharacter';
import { KiboAPI } from './KiboAPI';
import { FBX_FILES } from './types';
import type { FbxAnimation } from './types';

const MODEL_URL = 'models/Kibo1.fbx'; // base character mesh

function buildKiboWsUrl(): string {
  const wsParam = new URLSearchParams(window.location.search).get('ws');
  const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const rawBridgeWsBase = (import.meta.env.VITE_STATE_BRIDGE_WS_BASE || '').trim();
  const bridgeWsBase = rawBridgeWsBase || `${wsProtocol}://${window.location.hostname}:5003`;
  const bridgeToken = (import.meta.env.VITE_STATE_BRIDGE_TOKEN || '').trim();
  const defaultWsUrl = `${bridgeWsBase.replace(/\/+$/, '')}/ws/kibo`;
  const resolved = new URL(wsParam || defaultWsUrl, window.location.href);

  if (bridgeToken && !resolved.searchParams.has('token')) {
    resolved.searchParams.set('token', bridgeToken);
  }

  return resolved.toString();
}

async function main() {
  const { renderer, camera, scene, clock, controls, updateDebug } = createScene();
  document.getElementById('app')!.appendChild(renderer.domElement);

  // Character
  const character = new KiboCharacter();

  try {
    // No scale correction — keep Kibo at native Mixamo units (~170 units tall).
    // Camera is positioned to match (see scene.ts).
    await character.load(MODEL_URL, scene);
    console.log('[Kibo] Base model loaded');
  } catch {
    console.warn('[Kibo] Base model not found – running without character');
  }

  // Load all FBX animation clips in parallel
  const animationEntries = Object.entries(FBX_FILES) as [FbxAnimation, string][];
  const results = await Promise.allSettled(
    animationEntries.map(([name, file]) =>
      character.loadFbxAnimation(name, `models/${file}`),
    ),
  );
  results.forEach((result, i) => {
    if (result.status === 'rejected') {
      console.warn(`[Kibo] Failed to load animation "${animationEntries[i][0]}":`, result.reason);
    }
  });
  console.log('[Kibo] Animation loading complete');

  // ThoughtfulHeadShake is the idle loop — plays between all trigger animations
  character.setFbxIdle('ThoughtfulHeadShake');

  // API (exposed on window.kiboAPI)
  const api = new KiboAPI(character);

  // Connect to the state bridge Kibo feed. The bridge now requires
  // ?token= auth on browser WebSockets, so we append it centrally here.
  const wsUrl = buildKiboWsUrl();
  api.connectWebSocket(wsUrl);

  // Render loop
  renderer.setAnimationLoop(() => {
    const dt = clock.getDelta();
    controls.update();     // apply damping each frame
    updateDebug();         // refresh camera position overlay
    character.update(dt);
    renderer.render(scene, camera);
  });
}

main();
