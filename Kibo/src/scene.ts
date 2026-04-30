import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

/**
 * Set up the base Three.js scene: camera, lights, ground, grid, renderer.
 * Returns OrbitControls for free camera roaming and an updateDebug()
 * function to refresh the camera position overlay — call both each frame.
 */
export function createScene() {
  // Renderer
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(window.innerWidth, window.innerHeight);

  // Camera — Kibo is at native Mixamo scale (~170 units tall).
  // Matches the camera position used in the Three.js FBX example.
  const camera = new THREE.PerspectiveCamera(
    45,
    window.innerWidth / window.innerHeight,
    1,
    2000,
  );
  camera.position.set(100, 200, 300);
  camera.lookAt(0, 100, 0);

  // Scene
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe0e0e0);
  scene.fog = new THREE.Fog(0xe0e0e0, 200, 1000);

  // Lights
  const hemiLight = new THREE.HemisphereLight(0xffffff, 0x8d8d8d, 3);
  hemiLight.position.set(0, 20, 0);
  scene.add(hemiLight);

  const dirLight = new THREE.DirectionalLight(0xffffff, 3);
  dirLight.position.set(0, 20, 10);
  scene.add(dirLight);

  // Ground
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(2000, 2000),
    new THREE.MeshPhongMaterial({ color: 0xcbcbcb, depthWrite: false }),
  );
  ground.rotation.x = -Math.PI / 2;
  scene.add(ground);

  // Grid
  const grid = new THREE.GridHelper(200, 40, 0x000000, 0x000000);
  (grid.material as THREE.Material).opacity = 0.2;
  (grid.material as THREE.Material).transparent = true;
  scene.add(grid);

  // Clock
  const clock = new THREE.Clock();

  // ── OrbitControls — free camera roaming ──────────────────────────
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 100, 0); // waist height at native Mixamo scale
  controls.enableDamping = true;  // smooth inertia
  controls.dampingFactor = 0.08;
  controls.update();

  // ── Camera debug overlay ─────────────────────────────────────────
  const panel = document.createElement('div');
  panel.style.cssText = [
    'position:fixed', 'bottom:12px', 'left:12px',
    'background:rgba(0,0,0,0.55)', 'color:#e8e8e8',
    'font:12px/1.6 monospace', 'padding:8px 12px',
    'border-radius:6px', 'pointer-events:none',
    'white-space:pre', 'z-index:9999',
  ].join(';');
  document.body.appendChild(panel);

  const f = (n: number) => n.toFixed(3).padStart(8);

  function updateDebug() {
    const p = camera.position;
    const t = controls.target;
    panel.textContent =
      `pos    x:${f(p.x)}  y:${f(p.y)}  z:${f(p.z)}\n` +
      `target x:${f(t.x)}  y:${f(t.y)}  z:${f(t.z)}`;
  }

  // Resize handler
  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  return { renderer, camera, scene, clock, controls, updateDebug };
}
