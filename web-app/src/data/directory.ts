// The people directory and a keyword map from a room name to its backdrop scene.
import type { Invitee } from '../ui';
import { KNOWN_PEOPLE } from './store';
import type { SceneKey } from '../world/scenes';

/** Prefix matches on name words or email first, then anywhere-includes matches. Max 5. Empty query = no results. */
export function searchPeople(q: string): Invitee[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return [];
  const starts = (p: Invitee) => [...(p.name || '').toLowerCase().split(' '), p.email].some((w) => w.startsWith(needle));
  return KNOWN_PEOPLE.filter((p) => (p.name + ' ' + p.email).toLowerCase().includes(needle))
    .sort((a, b) => Number(starts(b)) - Number(starts(a))).slice(0, 5);
}

const SCENE_WORDS: [SceneKey, string[]][] = [
  ['meadow', ['lake', 'pond', 'river', 'norman']],
  ['home', ['porch', 'house', 'home', 'grandma', 'cabin']],
  ['beach', ['beach', 'shore', 'island', 'tybee', 'summer', 'sea']],
  ['clouds', ['graduation', 'wedding', 'sky', 'cloud']],
  ['plain', ['field', 'farm', 'plain', 'ranch']],
  ['night', ['night', 'stars', 'camp', 'bonfire']],
  ['cloudsea', ['mountain', 'hike', 'summit']],
];

/** Case-insensitive word-boundary keyword match on a room name. First scene in the list to match wins. */
export function sceneFor(name: string): SceneKey | null {
  const words = new Set(name.toLowerCase().match(/[a-z0-9']+/g) || []);
  for (const [scene, keys] of SCENE_WORDS) if (keys.some((k) => words.has(k))) return scene;
  return null;
}
