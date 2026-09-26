import { create } from 'zustand';
import type { SceneKey } from './scenes';

// The DOM element the painted window should fill, and which painting it shows.
// Stage components write this; the WebGL layer reads it every frame.
interface World {
  stage: HTMLElement | null; scene: SceneKey; zoom: number; mist: number; blur: number; petals: boolean; fast: boolean;
  portal: { el: HTMLElement; src: string; depth?: string } | null;
  ready: boolean; // true once WebGL is drawing, so stages drop their CSS fallback
}
export const useWorld = create<World>(() => ({ stage: null, scene: 'meadow', zoom: 0, mist: 0, blur: 0, petals: false, fast: false, portal: null, ready: false }));

export const reducedMotion = () => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
export const webglOk = (() => {
  try {
    const ctx = document.createElement('canvas').getContext('webgl2') as WebGL2RenderingContext | null;
    const ok = !!ctx;
    ctx?.getExtension('WEBGL_lose_context')?.loseContext();
    return ok;
  } catch { return false; }
})();
export const immersive = webglOk && !reducedMotion();
