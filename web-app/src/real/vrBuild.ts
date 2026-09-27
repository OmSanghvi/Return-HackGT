// "Build room in VR" (docs/WEB_TO_QUEST_PIPELINE.md §1): the pure parts --
// which step a build status lights, the words for it, and mock mode's timed
// stand-in for the Unity machine's room builder. The panel is VrBuildPanel.tsx.
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { RoomBuild, RoomBuildStatus } from '../api/types';

export const isActiveBuild = (b?: RoomBuild | null): boolean => !!b && b.status !== 'ready' && b.status !== 'failed';

/** The four steps the panel shows. `packaging` is unused since the APK was dropped (§6) but still reads as building. */
export const BUILD_STEPS: { label: string; statuses: string[] }[] = [
  { label: 'Queued for the room builder', statuses: ['requested', 'claimed'] },
  { label: 'Bringing everything into Unity', statuses: ['syncing'] },
  { label: 'Arranging the room', statuses: ['building', 'packaging'] },
  { label: 'Ready in VR', statuses: ['ready'] },
];

/** Index into BUILD_STEPS; an unknown (newer) status counts as still queued rather than breaking the panel. */
export function buildStep(status: string): number {
  const i = BUILD_STEPS.findIndex((s) => s.statuses.includes(status));
  return i < 0 ? 0 : i;
}

/** How long a build may sit in `requested` before the panel says the builder seems to be offline. */
export const SLOW_PICKUP_MS = 60_000;

/** One warm sentence for where a build is. `waitedMs` = time since it was requested. */
export function buildStatusLine(b: RoomBuild, waitedMs = 0): string {
  switch (b.status) {
    case 'requested':
      return waitedMs > SLOW_PICKUP_MS
        ? "Still queued. The room builder may be finishing another room or offline; this starts as soon as it's free, so it's fine to close this page."
        : 'Waiting for the room builder to pick this up.';
    case 'claimed':
      return 'The room builder picked it up.';
    case 'syncing':
      return 'Bringing your photos, objects and notes into Unity.';
    case 'building':
      return 'NemoClaw is arranging the room around your photos.';
    case 'packaging':
      return 'Adding the finishing touches.';
    case 'ready':
      return 'Ready in VR.';
    case 'failed':
      // The cancel route records "Cancelled by demo-alice."; say it the way the app names people.
      return (
        b.message.replace(/^Cancelled by demo-([\w-]+)\.?$/,(_, who: string) => `Stopped by ${who.charAt(0).toUpperCase()}${who.slice(1)}.`) ||
        'Something went wrong while building the room.'
      );
    default:
      return 'Working on it.';
  }
}

/** "The lake house" -> "the-lake-house": the room name mock mode pretends the builder chose. */
export function slugify(title: string): string {
  return (
    title
      .normalize('NFKD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 48) || 'room'
  );
}

// ---------------------------------------------------------------------------
// Mock mode: a timed build so the offline demo still ends on "Ready in VR".
// Only the start time is stored; the status is read off the clock, so a
// reload mid-build picks up exactly where it was.
// ---------------------------------------------------------------------------

/** When (ms after the request) each status begins. */
export const MOCK_TIMELINE: [RoomBuildStatus, number][] = [
  ['requested', 0],
  ['claimed', 2500],
  ['syncing', 4500],
  ['building', 9000],
  ['ready', 18000],
];

export interface MockBuildSeed {
  build_id: string;
  project_id: string;
  title: string;
  prompt: string;
  requested_by: string;
  started_at: number;
}

/** The simulated build as the backend would report it `now`. */
export function mockBuildAt(seed: MockBuildSeed, now: number): RoomBuild {
  const elapsed = now - seed.started_at;
  let status: RoomBuildStatus = 'requested';
  let since = 0;
  for (const [s, at] of MOCK_TIMELINE) if (elapsed >= at) { status = s; since = at; }
  const slug = slugify(seed.title);
  const claimed = status !== 'requested';
  const ready = status === 'ready';
  return {
    build_id: seed.build_id,
    project_id: seed.project_id,
    requested_by: seed.requested_by,
    prompt: seed.prompt,
    scene_id: '',
    status,
    message: '',
    slug: ready ? slug : '',
    scene_path: ready ? `Assets/SketchScape/AgentRooms/${slug}.unity` : '',
    apk_path: '',
    runner_id: claimed ? 'demo-runner' : '',
    created_at: new Date(seed.started_at).toISOString(),
    updated_at: new Date(seed.started_at + since).toISOString(),
  };
}

interface MockBuildState {
  builds: Record<string, MockBuildSeed>;
  start(projectId: string, title: string, prompt: string, requestedBy: string): void;
}

export const useMockBuilds = create<MockBuildState>()(
  persist(
    (set, get) => ({
      builds: {},
      start: (projectId, title, prompt, requestedBy) =>
        set({
          builds: {
            ...get().builds,
            [projectId]: {
              build_id: Math.random().toString(36).slice(2, 12),
              project_id: projectId,
              title,
              prompt,
              requested_by: requestedBy,
              started_at: Date.now(),
            },
          },
        }),
    }),
    { name: 'return-demo-vr-builds' },
  ),
);
