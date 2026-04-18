import { createScene } from './scene';
import { KiboCharacter } from './KiboCharacter';
import { KiboAPI } from './KiboAPI';

const MODEL_URL = 'models/RobotExpressive.glb'; // placeholder – swap for Kibo model

async function main() {
  const { renderer, camera, scene, clock } = createScene();
  document.getElementById('app')!.appendChild(renderer.domElement);

  // Character
  const character = new KiboCharacter();

  try {
    await character.load(MODEL_URL, scene);
    console.log('[Kibo] Model loaded');
  } catch {
    console.warn('[Kibo] Model not found – running without character');
  }

  // API (exposed on window.kiboAPI)
  const api = new KiboAPI(character);

  // Connect to orchestration engine WS
  // Priority: ?ws= query param → same-origin /ws/kibo → dev default
  const wsParam = new URLSearchParams(window.location.search).get('ws');
  const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const defaultWsUrl = `${wsProtocol}://${window.location.host}/ws/kibo`;
  const wsUrl = wsParam || defaultWsUrl;
  api.connectWebSocket(wsUrl);

  // Render loop
  renderer.setAnimationLoop(() => {
    const dt = clock.getDelta();
    character.update(dt);
    renderer.render(scene, camera);
  });
}

main();
