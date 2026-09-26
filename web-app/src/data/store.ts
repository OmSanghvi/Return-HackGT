// Demo-only room data: seeded rooms, local actions and a simulator that plays the other people.
// ponytail: all in localStorage, swap actions for API calls when the backend lands.
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { SceneKey } from '../world/scenes';
import { REAL_MODE } from '../config';

export type MemberStatus = 'invited' | 'joined' | 'done';
export interface Member { id: string; name: string; email: string; status: MemberStatus; count?: number; note?: string; isOwner?: boolean; invitedAt: number; etaAt?: number }
export type Phase = 'collecting' | 'building' | 'ready';
export interface Room {
  id: string; title: string; place?: string; date?: string;
  cover?: string; scene: SceneKey; photos: string[]; note?: string;
  members: Member[]; phase: Phase; progress: number; invitedBy?: string; createdAt: number; builtAt?: number;
  objects?: string[]; // what to rebuild; empty = everything in the photos
}
export const ME = { id: 'me', name: 'Dylan Houle', email: 'dylan@return.world' };
export const KNOWN_PEOPLE = [
  { name: 'Mom', email: 'maria.houle@gmail.com' }, { name: 'Sam Park', email: 'sam.park@gatech.edu' },
  { name: 'Samira Ali', email: 'samira@hey.com' }, { name: 'Ava Lin', email: 'ava@lin.dev' }, { name: 'Jordan Reyes', email: 'jordan@reyes.me' },
];

const MIN = 60_000, HOUR = 60 * MIN;
const BUILD_MS = 7000;
const NOTES = ['The dock at sunset, every single night.', 'I still hear the screen door.', 'We stayed out until the fireflies came.'];

const uid = () => Math.random().toString(36).slice(2, 10);
const nameFor = (email: string) => KNOWN_PEOPLE.find((p) => p.email === email)?.name || email.split('@')[0];
const member = (email: string, now: number, extra: Partial<Member> = {}): Member => ({ id: uid(), name: nameFor(email), email, status: 'invited', invitedAt: now, ...extra });

export function seed(now = Date.now()): Room[] {
  const me = (x: Partial<Member>) => ({ ...ME, invitedAt: now - 30 * HOUR, ...x }) as Member;
  return [
    { id: 'lake-house', title: 'The lake house', place: 'Lake Norman', date: 'July 14, 2019', scene: 'meadow', photos: [], phase: 'ready', progress: 1, createdAt: now - 72 * HOUR,
      members: [me({ status: 'done', count: 4, isOwner: true }), member('maria.houle@gmail.com', now, { status: 'done', count: 5, note: NOTES[0] }), member('sam.park@gatech.edu', now, { status: 'done', count: 4 })] },
    { id: 'grandmas-porch', title: "Grandma's porch", place: 'Asheville', scene: 'home', photos: [], phase: 'collecting', progress: 0, createdAt: now - 26 * HOUR,
      members: [me({ status: 'done', count: 4, isOwner: true, note: NOTES[1] }), member('maria.houle@gmail.com', now, { status: 'done', count: 5 }), member('sam.park@gatech.edu', now - 2 * HOUR)] },
    { id: 'last-summer', title: 'Last day of summer', place: 'Tybee Island', scene: 'beach', photos: [], phase: 'building', progress: 0.35, createdAt: now - 5 * HOUR,
      members: [me({ status: 'done', count: 6, isOwner: true }), member('jordan@reyes.me', now, { status: 'done', count: 5 })] },
    { id: 'ava-graduation', title: "Ava's graduation", place: 'Athens', scene: 'clouds', photos: [], phase: 'collecting', progress: 0, invitedBy: 'Ava Lin', createdAt: now - 3 * HOUR,
      members: [member('ava@lin.dev', now, { status: 'done', count: 7, isOwner: true }), me({ status: 'invited', invitedAt: now - 3 * HOUR })] },
  ];
}

/** "vase, porch swing" -> ['vase', 'porch swing']. Caps match the backend: 8 objects, 100 chars each. */
export const parseObjects = (s: string) => [...new Set(s.split(',').map((x) => x.trim().slice(0, 100)).filter(Boolean))].slice(0, 8);

export const mine = (r: Room) => r.members.find((m) => m.id === ME.id);
export const pending = (r: Room) => r.members.filter((m) => m.status !== 'done');

/** Where a room opens, from its status. */
export function routeForRoom(r: Room) {
  return r.phase === 'collecting' && mine(r)?.status !== 'done' ? `/rooms/${r.id}/add` : `/rooms/${r.id}`;
}

/** Pure simulator step: people arrive, building advances, ready lands. */
export function tick(rooms: Room[], now: number, dt: number): Room[] {
  let changed = false;
  const next = rooms.map((r) => {
    if (r.phase === 'collecting') {
      if (mine(r)?.status !== 'done') return r;
      const members = r.members.map((m) => (m.etaAt && m.etaAt <= now && m.status !== 'done'
        ? { ...m, status: 'done' as const, count: 3 + (m.name.length % 5), note: NOTES[m.name.length % NOTES.length], etaAt: undefined } : m));
      const arrived = members.some((m, i) => m !== r.members[i]);
      if (!arrived) return r;
      changed = true;
      return members.every((m) => m.status === 'done') ? { ...r, members, phase: 'building' as const, progress: 0 } : { ...r, members };
    }
    if (r.phase === 'building') {
      if (r.progress >= 1) {
        // Hold on "Ready to return" for a beat before flipping, so it's visible.
        if (r.builtAt != null && now - r.builtAt >= 900) { changed = true; return { ...r, phase: 'ready' as const }; }
        return r;
      }
      changed = true;
      const progress = Math.min(1, r.progress + dt / BUILD_MS);
      return progress >= 1 ? { ...r, progress: 1, builtAt: now } : { ...r, progress };
    }
    return r;
  });
  return changed ? next : rooms;
}

/** Demo fast-forward: one visible step for the given room. */
export function advance(r: Room, now: number): Room {
  if (r.phase === 'building') return { ...r, progress: 1, phase: 'ready' };
  if (r.phase !== 'collecting') return r;
  const next = pending(r).find((m) => m.id !== ME.id);
  if (!next) return r;
  return tick([{ ...r, members: r.members.map((m) => (m === next ? { ...m, etaAt: now } : m)) }], now, 0)[0];
}

interface State {
  rooms: Room[]; signedIn: boolean;
  /** False until real mode's first fetch lands; always true in mock mode. */
  synced: boolean;
  signIn(): void; signOut(): void; reset(): void;
  createRoom(title: string, emails: string[], scene?: SceneKey): string;
  invite(id: string, email: string): void; uninvite(id: string, memberId: string): void; resend(id: string, memberId: string): void;
  join(id: string): void; decline(id: string): void;
  addPhotos(id: string, photos: string[], note: string, objects?: string[]): void;
  startBuilding(id: string): void; rename(id: string, title: string): void; leave(id: string): void; remove(id: string): void;
  step(now: number, dt: number): void; fastForward(id: string): void;
}

export const useRooms = create<State>()(persist((set, get) => {
  const patch = (id: string, fn: (r: Room) => Room) => set({ rooms: get().rooms.map((r) => (r.id === id ? fn(r) : r)) });
  const drop = (id: string) => set({ rooms: get().rooms.filter((r) => r.id !== id) });
  return {
    rooms: REAL_MODE ? [] : seed(), signedIn: false, synced: !REAL_MODE,
    signIn: () => set({ signedIn: true }), signOut: () => set({ signedIn: false }),
    reset: () => set({ rooms: seed(), signedIn: false }),
    createRoom(title, emails, scene) {
      const now = Date.now(), id = uid();
      const scenes: SceneKey[] = ['home', 'meadow', 'plain', 'beach', 'clouds'];
      const room: Room = { id, title: title.trim() || 'Untitled room', scene: scene || scenes[get().rooms.length % scenes.length], photos: [], phase: 'collecting', progress: 0, createdAt: now,
        members: [{ ...ME, status: 'joined', isOwner: true, invitedAt: now }, ...emails.map((e) => member(e, now))] };
      set({ rooms: [room, ...get().rooms] });
      return id;
    },
    invite: (id, email) => patch(id, (r) => (r.members.some((m) => m.email === email) ? r
      : { ...r, members: [...r.members, member(email, Date.now())] })),
    uninvite: (id, memberId) => patch(id, (r) => ({ ...r, members: r.members.filter((m) => m.id !== memberId) })),
    resend: (id, memberId) => patch(id, (r) => ({ ...r, members: r.members.map((m) => (m.id === memberId ? { ...m, invitedAt: Date.now() } : m)) })),
    join: (id) => patch(id, (r) => ({ ...r, members: r.members.map((m) => (m.id === ME.id ? { ...m, status: 'joined' } : m)) })),
    decline: drop,
    addPhotos: (id, photos, note, objects) => patch(id, (r) => {
      const members = r.members.map((m) => (m.id === ME.id ? { ...m, status: 'done' as const, count: photos.length, note: note.trim() || undefined } : m));
      const everyoneDone = members.every((m) => m.status === 'done');
      return {
        ...r, photos, cover: r.cover || photos[0], objects: objects ?? r.objects, members,
        ...(everyoneDone ? { phase: 'building' as const, progress: 0 } : null),
      };
    }),
    startBuilding: (id) => patch(id, (r) => ({ ...r, phase: 'building', progress: 0, members: r.members.filter((m) => m.status === 'done') })),
    rename: (id, title) => patch(id, (r) => ({ ...r, title })),
    leave: drop, remove: drop,
    step: (now, dt) => { const rooms = tick(get().rooms, now, dt); if (rooms !== get().rooms) set({ rooms }); },
    fastForward: (id) => patch(id, (r) => advance(r, Date.now())),
  };
}, REAL_MODE
  // Real mode: rooms come from the backend (src/real/rooms.ts); only the sign-in flag persists.
  ? { name: 'return-real-session', partialize: (s) => ({ signedIn: s.signedIn }) as State }
  : { name: 'return-demo-v1', partialize: ({ synced: _, ...s }) => s as State }));

export const agoText = (t: number) => {
  const m = Math.round((Date.now() - t) / MIN);
  return m < 1 ? 'just now' : m < 60 ? `${m} minute${m === 1 ? '' : 's'} ago` : `${Math.round(m / 60)} hour${Math.round(m / 60) === 1 ? '' : 's'} ago`;
};
