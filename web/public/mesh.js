// 3D mesh viewer for the Sample panel: one WebGL canvas, reused across samples. Drag to orbit,
// scroll to zoom; it turns slowly on its own until you touch it. Meshes are GLB, in the
// pipeline's flow axes (x along the flow, z up).

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const loader = new GLTFLoader();
const cache = new Map(); // url -> Promise<THREE.Object3D>

export function createViewer(el) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  el.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
  camera.up.set(0, 0, 1);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a80, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(-2, -3, 4);
  scene.add(sun);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 1.5;
  controls.addEventListener("start", () => (controls.autoRotate = false));

  let current = null;
  let shown = ""; // url and colour on screen, so a re-render doesn't reset the camera
  let token = 0;

  function resize() {
    const w = el.clientWidth, h = el.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(el);

  renderer.setAnimationLoop(() => {
    if (!el.isConnected) return;
    controls.update();
    renderer.render(scene, camera);
  });

  async function show(url, { failed = false } = {}) {
    const key = `${url}|${failed}`;
    if (key === shown) return;
    shown = key;
    const mine = ++token;
    if (!cache.has(url)) {
      cache.set(url, loader.loadAsync(url).then((g) => g.scene).catch((e) => (cache.delete(url), (shown = ""), Promise.reject(e))));
    }
    const obj = (await cache.get(url)).clone();
    if (mine !== token) return; // a newer request won
    const color = getComputedStyle(el).getPropertyValue(failed ? "--critical" : "--mesh").trim() || "#8a8a90";
    obj.traverse((o) => {
      if (!o.isMesh) return;
      if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();
      o.material = new THREE.MeshStandardMaterial({ color, roughness: 0.65, metalness: 0.05, side: THREE.DoubleSide });
    });
    if (current) scene.remove(current);
    current = obj;
    scene.add(obj);
    // Frame it: centre on the origin, camera at a three-quarter view from the front.
    const box = new THREE.Box3().setFromObject(obj);
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    obj.position.sub(box.getCenter(new THREE.Vector3()));
    camera.position.set(-0.9, -1.1, 0.7).multiplyScalar(size * 1.1);
    controls.target.set(0, 0, 0);
    controls.autoRotate = true;
    resize();
  }

  function clear() {
    token++; // a pending show() for the previous sample won't paint
    shown = "";
    if (current) scene.remove(current);
    current = null;
  }

  return { show, clear };
}
