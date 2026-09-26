import { expect, test } from 'vitest';
import { advance, ME, mine, parseObjects, routeForRoom, seed, tick, type Room } from './store';

test('a room walks invited -> add photos -> building -> ready, and routes follow', () => {
  const now = 1_000_000;
  let r: Room = seed(now).find((x) => x.id === 'ava-graduation')!;
  expect(mine(r)!.status).toBe('invited');
  expect(routeForRoom(r)).toBe('/rooms/ava-graduation/add');

  // I'm the only one left pending. Adding my photos should start the build, not dead-end
  // (mirrors the addPhotos reducer's everyoneDone check).
  const members = r.members.map((m) => (m.id === ME.id ? { ...m, status: 'done' as const, count: 3 } : m));
  r = members.every((m) => m.status === 'done') ? { ...r, members, phase: 'building' as const, progress: 0 } : { ...r, members };
  expect(routeForRoom(r)).toBe('/rooms/ava-graduation');
  expect(r.phase).toBe('building');
  expect(r.progress).toBe(0);

  r = tick([r], now + 3500, 3500)[0];
  expect(r.progress).toBeCloseTo(0.5, 1);
  r = advance(r, now);
  expect(r.phase).toBe('ready');
  expect(routeForRoom(r)).toBe('/rooms/ava-graduation');
});

test('tick leaves untouched state identical, so nothing re-renders', () => {
  const rooms = seed(0).filter((r) => r.phase !== 'building');
  expect(tick(rooms, 1, 1)).toBe(rooms);
});

test('addPhotos with everyone else already done starts the build', () => {
  const now = 1_000_000;
  const r: Room = seed(now).find((x) => x.id === 'ava-graduation')!;
  const members = r.members.map((m) => (m.id === ME.id ? { ...m, status: 'done' as const, count: 3 } : m));
  const next = members.every((m) => m.status === 'done') ? { ...r, members, phase: 'building' as const, progress: 0 } : { ...r, members };
  expect(next.phase).toBe('building');
  expect(next.progress).toBe(0);
});

test('tick holds a built room at progress 1 for a beat before going ready', () => {
  const now = 1_000_000;
  const r: Room = { ...seed(now).find((x) => x.id === 'last-summer')!, phase: 'building', progress: 1, builtAt: now };
  const holding = tick([r], now + 500, 500)[0];
  expect(holding.phase).toBe('building');
  expect(holding.progress).toBe(1);
  const ready = tick([holding], now + 900, 400)[0];
  expect(ready.phase).toBe('ready');
});

test('advance on a building room jumps straight to ready', () => {
  const now = 1_000_000;
  const r: Room = { ...seed(now).find((x) => x.id === 'last-summer')!, phase: 'building', progress: 0.35 };
  const next = advance(r, now);
  expect(next.phase).toBe('ready');
  expect(next.progress).toBe(1);
});

test('advance on a collecting room brings exactly one person in', () => {
  const now = 1_000_000;
  // Add another pending member so advance has someone to bring in without finishing the room.
  let r: Room = seed(now).find((x) => x.id === 'grandmas-porch')!;
  r = { ...r, members: [...r.members, { id: 'x', name: 'Jordan', email: 'jordan@x.io', status: 'invited', invitedAt: now }] };
  const before = r.members.filter((m) => m.status === 'done').length;
  r = advance(r, now);
  const after = r.members.filter((m) => m.status === 'done').length;
  expect(after).toBe(before + 1);
  expect(r.phase).toBe('collecting');
});

test('objects: blank means everything, list is trimmed, deduped and capped', () => {
  expect(parseObjects('  ')).toEqual([]);
  expect(parseObjects('vase, porch swing,, vase ')).toEqual(['vase', 'porch swing']);
  expect(parseObjects(Array.from({ length: 12 }, (_, i) => `o${i}`).join(','))).toHaveLength(8);
});
