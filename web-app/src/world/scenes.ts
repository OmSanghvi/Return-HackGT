// Every painted environment, its baked depth map, and whether it's a dusk scene.
const img = import.meta.glob('../design-system/imagery/*.webp', { eager: true, query: '?url', import: 'default' }) as Record<string, string>;
const dep = import.meta.glob('../assets/depth/*.png', { eager: true, query: '?url', import: 'default' }) as Record<string, string>;

const FILES = {
  meadow: 'return-sky-day-meadow-lake', clouds: 'return-sky-day-cloud-field', painted: 'return-sky-day-golden-plain',
  home: 'return-sky-day-hilltop-home', beach: 'return-sky-day-morning-beach', plain: 'return-sky-day-golden-plain',
  cloudsea: 'return-sky-dusk-cloud-sea', night: 'return-sky-dusk-cloud-sea',
} as const;   // painted and night are aliases: their old oil-sky and photo art didn't match the anime style
export type SceneKey = keyof typeof FILES;

export const SCENES = Object.fromEntries(Object.entries(FILES).map(([k, f]) => [k, {
  image: img[`../design-system/imagery/${f}.webp`],
  depth: dep[`../assets/depth/${f}.png`],
  dusk: f.includes('dusk'),
}])) as Record<SceneKey, { image: string; depth: string; dusk: boolean }>;
