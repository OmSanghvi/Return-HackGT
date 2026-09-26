// One persistent WebGL canvas behind the whole app. It draws the painted window wherever the current
// Stage sits, morphs between stages, and flies through mist from one painting to the next.
import { Suspense, useEffect, useMemo, useRef } from 'react';
import { Canvas, useFrame, useLoader, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { SCENES, type SceneKey } from './scenes';
import { useWorld } from './state';
import { vertex, fragment } from './shader';

const KEYS = Object.keys(SCENES) as SceneKey[];
const FOG = { day: new THREE.Color(0.72, 0.77, 0.84), dusk: new THREE.Color(0.05, 0.07, 0.15) };   // day haze is a muted mid-tone, never white: flights and resolves pass through it
const flat = (() => { const t = new THREE.DataTexture(new Uint8Array([40, 40, 40, 255]), 1, 1); t.needsUpdate = true; return t; })();
const ease = (t: number) => 1 - Math.pow(1 - t, 3);
type Rect = [number, number, number, number];
type TexPair = { img: THREE.Texture; dep: THREE.Texture };
const rectOf = (el: HTMLElement): Rect => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; };
const idle = (fn: () => void) => ('requestIdleCallback' in window ? requestIdleCallback(fn) : setTimeout(fn, 0));

// Paintings decode off the main thread (ImageBitmap) and upload to the GPU in idle time, so a flight
// never stalls on its first frame. Scene textures are shared by URL between the main window and the portal.
const cache = new Map<string, Promise<THREE.Texture>>();
const sceneUrls = new Set(KEYS.flatMap((k) => [SCENES[k].image, SCENES[k].depth]));
const depthUrls = new Set(KEYS.map((k) => SCENES[k].depth));
function loadTex(gl: THREE.WebGLRenderer, url: string): Promise<THREE.Texture> {
  const hit = cache.get(url);
  if (hit) return hit;
  const p = fetch(url).then((r) => r.blob()).then((b) => createImageBitmap(b, { imageOrientation: 'flipY', premultiplyAlpha: 'none' })).then(
    (bmp) => new Promise<THREE.Texture>((res) => {
      const t = new THREE.Texture(bmp as unknown as HTMLImageElement);
      t.flipY = false;
      if (depthUrls.has(url)) { t.generateMipmaps = false; t.minFilter = THREE.LinearFilter; }   // depth is sampled without mip bias
      t.needsUpdate = true;
      idle(() => { gl.initTexture(t); res(t); });
    }));
  if (sceneUrls.has(url)) cache.set(url, p);
  return p;
}

function useMaterial(arch: boolean) {
  return useMemo(() => new THREE.ShaderMaterial({
    vertexShader: vertex, fragmentShader: fragment, transparent: true, depthTest: false, depthWrite: false,
    uniforms: {
      uTexA: { value: flat }, uDepA: { value: flat }, uTexB: { value: flat }, uDepB: { value: flat },
      uAspA: { value: 16 / 9 }, uAspB: { value: 16 / 9 }, uMix: { value: 1 }, uMist: { value: 1 }, uTime: { value: 0 }, uZoom: { value: 0 },
      uRadius: { value: 32 }, uDpr: { value: 1 }, uArch: { value: arch ? 1 : 0 }, uAlpha: { value: 0 }, uHalo: { value: 0 }, uLight: { value: 0.1 }, uDusk: { value: 0 },
      uBlur: { value: 0 }, uPetals: { value: 0 }, uPhoto: { value: 0 },
      uRect: { value: new THREE.Vector4() }, uRes: { value: new THREE.Vector2() }, uPointer: { value: new THREE.Vector2() }, uFog: { value: FOG.day.clone() },
    },
  }), [arch]);
}

const pointer = { x: 0.5, y: 0.5, sx: 0.5, sy: 0.5, speed: 0 };
const dusk = () => document.documentElement.dataset.theme === 'dusk';

function MainWindow() {
  const initial = useMemo(() => useWorld.getState().scene, []);
  const [initImg, initDep] = useLoader(THREE.TextureLoader, [SCENES[initial].image, SCENES[initial].depth]);
  const tex = useRef<Partial<Record<SceneKey, TexPair>>>({ [initial]: { img: initImg, dep: initDep } } as Partial<Record<SceneKey, TexPair>>);
  useMemo(() => { cache.set(SCENES[initial].image, Promise.resolve(initImg)); cache.set(SCENES[initial].depth, Promise.resolve(initDep)); }, [initial, initImg, initDep]);
  const mat = useMaterial(false);
  const { gl, size } = useThree();
  const s = useRef({ scene: null as SceneKey | null, t: 1, dur: 2.8, el: null as HTMLElement | null, radius: 0, from: null as Rect | null, shown: [0, 0, 0, 0] as Rect, mt: 1, mist: 1, zoom: 0, blur: 0, petals: 0 });

  // Load the rest of the paintings after the first frame, off the critical path.
  useEffect(() => {
    let cancelled = false;
    idle(() => {
      if (cancelled) return;
      KEYS.filter((k) => k !== initial).forEach((k) => {
        void loadTex(gl, SCENES[k].image).then((img) => { if (!cancelled) tex.current[k] = { ...(tex.current[k] as TexPair), img }; });
        void loadTex(gl, SCENES[k].depth).then((dep) => { if (!cancelled) tex.current[k] = { ...(tex.current[k] as TexPair), dep }; });
      });
    });
    return () => { cancelled = true; };
  }, [initial, gl]);

  useEffect(() => {
    const canvas = gl.domElement;
    const onLost = (e: Event) => { e.preventDefault(); useWorld.setState({ ready: false }); };
    canvas.addEventListener('webglcontextlost', onLost);
    return () => canvas.removeEventListener('webglcontextlost', onLost);
  }, [gl]);

  useEffect(() => {
    const onResize = () => { if (s.current.el) s.current.radius = parseFloat(getComputedStyle(s.current.el).borderTopLeftRadius) || 0; };
    addEventListener('resize', onResize);
    return () => removeEventListener('resize', onResize);
  }, []);

  useFrame((state, dt) => {
    const w = useWorld.getState(), st = s.current, u = mat.uniforms;
    dt = Math.min(dt, 0.1);
    // Scene: start a flight when the painting changes, once its textures have arrived.
    if (w.scene !== st.scene) {
      const next = tex.current[w.scene];
      if (next && next.img && next.dep) {
        const dur = w.fast ? 1.0 : 2.8;
        if (st.scene && st.t < 0.5) {
          // a flight is mid-way: keep A as it is, only swap the destination so nothing pops
          u.uTexB.value = next.img; u.uDepB.value = next.dep; u.uAspB.value = 16 / 9;
          st.t = 0; st.dur = dur; st.scene = w.scene;
        } else {
          const prev = st.scene ? tex.current[st.scene] : next;
          u.uTexA.value = prev!.img; u.uDepA.value = prev!.dep; u.uAspA.value = 16 / 9;
          u.uTexB.value = next.img; u.uDepB.value = next.dep;
          st.t = st.scene ? 0 : 1; st.dur = dur; st.scene = w.scene;
        }
      } // else: textures not ready yet, keep showing the current scene and retry next frame
    }
    st.t = Math.min(1, st.t + dt / st.dur);
    // Frame: follow the stage; when it changes, morph from where the window was.
    if (w.stage !== st.el) {
      if (w.stage) { st.from = st.shown[2] ? [...st.shown] as Rect : null; st.mt = 0; }
      st.el = w.stage;
      if (st.el) st.radius = parseFloat(getComputedStyle(st.el).borderTopLeftRadius) || 0;
    }
    if (st.el) {
      const target = rectOf(st.el);
      st.mt = Math.min(1, st.mt + dt / 1.4);
      const e = ease(st.mt);
      st.shown = st.from && st.mt < 1 ? target.map((v, i) => st.from![i] + (v - st.from![i]) * e) as Rect : target;
      u.uRadius.value = st.radius;
    }
    pointer.sx += (pointer.x - pointer.sx) * 0.04; pointer.sy += (pointer.y - pointer.sy) * 0.04;
    pointer.speed *= Math.max(0, 1 - dt * 3);
    st.mist += (w.mist - st.mist) * Math.min(1, dt * 2.2);
    st.zoom += (w.zoom - st.zoom) * Math.min(1, dt * 3);
    st.blur += (w.blur - st.blur) * Math.min(1, dt * 2.2);
    st.petals += ((w.petals ? 1 : 0) - st.petals) * Math.min(1, dt * 1.5);
    u.uMix.value = st.t < 1 ? ease(st.t) : 1;
    u.uMist.value = st.mist; u.uZoom.value = st.zoom; u.uBlur.value = st.blur; u.uPetals.value = st.petals;
    u.uAlpha.value += ((st.shown[2] > 0 ? 1 : 0) - u.uAlpha.value) * Math.min(1, dt * 3);
    u.uLight.value += ((0.05 + Math.min(0.12, pointer.speed * 0.15)) - u.uLight.value) * Math.min(1, dt * 4);
    u.uTime.value = state.clock.elapsedTime;
    u.uRect.value.set(...st.shown);
    u.uDpr.value = gl.getPixelRatio();
    u.uRes.value.set(size.width * gl.getPixelRatio(), size.height * gl.getPixelRatio());
    const px = st.shown[2] ? (pointer.sx * innerWidth - st.shown[0]) / st.shown[2] - 0.5 : 0;
    let py = st.shown[3] ? (pointer.sy * innerHeight - st.shown[1]) / st.shown[3] - 0.5 : 0;
    py += (st.zoom - 0.2) * 0.3;
    u.uPointer.value.set(Math.max(-0.6, Math.min(0.6, px)), Math.max(-0.6, Math.min(0.6, py)));
    (u.uFog.value as THREE.Color).lerp(dusk() ? FOG.dusk : FOG.day, Math.min(1, dt * 1.5));
    u.uDusk.value += ((st.scene && SCENES[st.scene].dusk ? 1 : 0) - u.uDusk.value) * Math.min(1, dt * 1.5);   // stars and fireflies only over dusk paintings
    if (!w.ready && u.uAlpha.value > 0.95) useWorld.setState({ ready: true });
  });
  return <mesh material={mat} frustumCulled={false}><planeGeometry /></mesh>;
}

function PortalWindow() {
  const portal = useWorld((w) => w.portal);
  const mat = useMaterial(true);
  const h = useRef(false);   // pointer over the portal, tracked by events instead of a per-frame :hover query
  const { gl, size } = useThree();
  useEffect(() => {
    if (!portal) return;
    let stale = false;
    const loaded: THREE.Texture[] = [];
    // Scene paintings are shared with the main window (already on the GPU); only one-off covers are ours to dispose.
    const own = (url: string, t: THREE.Texture) => { if (!sceneUrls.has(url)) { if (stale) t.dispose(); else loaded.push(t); } };
    mat.uniforms.uTexA.value = mat.uniforms.uTexB.value = flat;   // don't flash the previous room
    loadTex(gl, portal.src).then((t) => {
      own(portal.src, t); if (stale) return;
      mat.uniforms.uTexA.value = mat.uniforms.uTexB.value = t; mat.uniforms.uAspA.value = mat.uniforms.uAspB.value = (t.image as ImageBitmap).width / (t.image as ImageBitmap).height;
    }).catch(() => {});
    if (portal.depth) loadTex(gl, portal.depth).then((t) => {
      own(portal.depth!, t); if (stale) return;
      mat.uniforms.uDepA.value = mat.uniforms.uDepB.value = t;
    }).catch(() => {});
    else mat.uniforms.uDepA.value = mat.uniforms.uDepB.value = flat;
    mat.uniforms.uPhoto.value = sceneUrls.has(portal.src) ? 0 : 1;
    const el = portal.el;
    const on = () => { h.current = true; }, off = () => { h.current = false; };
    el.addEventListener('pointerenter', on); el.addEventListener('pointerleave', off);
    return () => { stale = true; loaded.forEach((t) => t.dispose()); h.current = false; el.removeEventListener('pointerenter', on); el.removeEventListener('pointerleave', off); };
  }, [portal, mat, gl]);
  useFrame((state, dt) => {
    const u = mat.uniforms, el = portal?.el;
    const on = !!el && u.uTexB.value !== flat;
    u.uAlpha.value += ((on ? 1 : 0) - u.uAlpha.value) * Math.min(1, dt * 1.5);
    u.uMist.value += ((on ? 0 : 1) - u.uMist.value) * Math.min(1, dt * 0.8);   // the room resolves out of fog
    if (!el) { u.uHalo.value = 0; u.uAlpha.value = 0; return; }
    const r = el.getBoundingClientRect();
    u.uRect.value.set(r.left, r.top, r.width, r.height);
    const hover = h.current || el.dataset.state === 'entering';
    u.uHalo.value += ((hover ? 0.75 : 0.35) * u.uAlpha.value - u.uHalo.value) * Math.min(1, dt * 4);
    const idleZoom = 0.12 + 0.08 * Math.sin(state.clock.elapsedTime * 0.25);
    u.uZoom.value += ((el.dataset.state === 'entering' ? 2.5 : hover ? 0.25 : idleZoom) - u.uZoom.value) * Math.min(1, dt * 2);
    u.uTime.value = state.clock.elapsedTime;
    u.uDpr.value = gl.getPixelRatio();
    u.uBlur.value = 0;
    u.uRes.value.set(size.width * gl.getPixelRatio(), size.height * gl.getPixelRatio());
    u.uPointer.value.set(Math.max(-0.6, Math.min(0.6, (pointer.sx * innerWidth - r.left) / r.width - 0.5)), Math.max(-0.6, Math.min(0.6, (pointer.sy * innerHeight - r.top) / r.height - 0.5)));
    (u.uFog.value as THREE.Color).lerp(dusk() ? FOG.dusk : FOG.day, Math.min(1, dt * 1.5));
    u.uDusk.value += ((dusk() ? 1 : 0) - u.uDusk.value) * Math.min(1, dt * 1.5);
    u.uPetals.value = 1 - u.uDusk.value;
  });
  return <mesh material={mat} visible={!!portal} frustumCulled={false} renderOrder={1}><planeGeometry /></mesh>;
}

export default function SkyWorld() {
  useEffect(() => {
    const move = (e: PointerEvent) => {
      const nx = e.clientX / innerWidth, ny = e.clientY / innerHeight;
      pointer.speed = Math.min(1, pointer.speed + Math.hypot(nx - pointer.x, ny - pointer.y) * 8);
      pointer.x = nx; pointer.y = ny;
    };
    addEventListener('pointermove', move);
    return () => removeEventListener('pointermove', move);
  }, []);
  return (
    <Canvas className="app-world" flat linear dpr={1} gl={{ alpha: true, antialias: false, powerPreference: 'high-performance' }} style={{ position: 'fixed' }}>
      <Suspense fallback={null}><MainWindow /><PortalWindow /></Suspense>
    </Canvas>
  );
}
