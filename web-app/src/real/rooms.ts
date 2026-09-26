// Real mode's bridge to the original room screens: turns backend projects into
// the same `Room` shape the mock store uses, and backs each screen action with
// real API calls. The screens stay the source of the look; this is plumbing.
//
// Mapping (backend has no room phases or email invites, so they're derived):
// - members  = contributors; "done" once they've uploaded a photo, count = uploads,
//              note = the first memory text they typed.
// - phase    = ready when every reconstruction asset has settled, building while
//              any is processing or once everyone is done (segmenting, then Make 3D
//              fires on its own), collecting otherwise.
// - invites  = projects this browser knows about (the other account created them)
//              that the current account can't read yet; joining uses the stored code.
import {
  ApiError, createContributor, createProject, createSelections, createUpload, detectUploadObjects,
  fetchImageObjectUrl, generateSelectedObjects, getProject, listContributors, listProjectAssets, listUploads,
} from '../api/client';
import type { Contributor, ProjectAsset, UploadRecord } from '../api/types';
import { accountLabel, useAccount } from '../api/account';
import { DEMO_ACCOUNTS } from '../config';
import { ME, useRooms, type Member, type Room } from '../data/store';
import { sceneFor } from '../data/directory';
import type { SceneKey } from '../world/scenes';
import { forgetProject, listKnownProjects, rememberProject, updateKnownProject, type KnownProject } from './localProjects';

const SCENES: SceneKey[] = ['home', 'meadow', 'plain', 'beach', 'clouds'];
const sceneOf = (name: string, i: number) => sceneFor(name) ?? SCENES[i % SCENES.length];
const newId = () => (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2));
const me = () => useAccount.getState().current;
const t = (iso?: string) => (iso ? Date.parse(iso) : Date.now());

// ponytail: blob URLs cached for the tab's lifetime, never revoked; fine for a demo-sized room count.
const covers = new Map<string, Promise<string | undefined>>();
const coverFor = (projectId: string, uploadId: string) => {
  if (!covers.has(uploadId)) covers.set(uploadId, fetchImageObjectUrl(`/v1/projects/${projectId}/uploads/${uploadId}/image`).catch(() => undefined));
  return covers.get(uploadId)!;
};

const generating = new Set<string>();

/**
 * Everyone's in: send this account's found objects to Make 3D, once. Only the
 * uploader may generate (backend require_upload_owner), so each account's
 * client builds its own photos; switching accounts picks up the other half.
 */
async function autoGenerate(projectId: string, uploads: UploadRecord[]) {
  if (generating.has(projectId)) return;
  const batches = uploads.filter((u) => u.uploader_user_id === me()).map((u) => ({ id: u.upload_id, sel: u.selections.filter((s) => s.status === 'segmented').map((s) => s.selection_id) })).filter((b) => b.sel.length);
  if (!batches.length) return;
  generating.add(projectId);
  try {
    await Promise.all(batches.map((b) => generateSelectedObjects(projectId, b.id, b.sel).catch((e) => {
      if (!(e instanceof ApiError && e.status === 409)) throw e; // 409: another client already started it
    })));
  } finally {
    generating.delete(projectId);
  }
}

function toRoom(k: KnownProject, i: number, contributors: Contributor[], uploads: UploadRecord[], assets: ProjectAsset[], createdBy?: string | null): Room {
  const account = me();
  const members: Member[] = contributors.map((c) => {
    const theirs = uploads.filter((u) => c.clerk_user_id && u.uploader_user_id === c.clerk_user_id);
    return {
      id: c.clerk_user_id === account ? ME.id : c.contributor_id,
      name: c.display_name, email: c.clerk_user_id ?? c.contributor_id,
      status: theirs.length ? 'done' : 'joined', count: theirs.length || undefined,
      note: theirs.flatMap((u) => u.selections).find((s) => s.memory_text)?.memory_text || undefined,
      isOwner: !!createdBy && c.clerk_user_id === createdBy, invitedAt: t(c.joined_at),
    };
  });
  // The other demo account is always implicitly invited (it sees the room as an invitation), so show it as such.
  for (const acc of DEMO_ACCOUNTS) {
    if (!contributors.some((c) => c.clerk_user_id === acc) && !k.declinedBy?.includes(acc)) {
      members.push({ id: acc === account ? ME.id : `invite-${acc}`, name: accountLabel(acc), email: acc, status: 'invited', invitedAt: t(contributors[0]?.joined_at) });
    }
  }
  const recon = assets.filter((a) => a.kind === 'reconstruction');
  const settled = recon.filter((a) => a.status === 'ready' || a.status === 'failed').length;
  const selections = uploads.flatMap((u) => u.selections);
  const finding = selections.filter((s) => s.status === 'pending').length;
  const found = selections.filter((s) => s.status === 'segmented').length; // found, not yet sent to Make 3D
  const allIn = members.length > 0 && members.every((m) => m.status === 'done');
  const go = allIn || (k.forced && members.some((m) => m.status === 'done'));
  let phase: Room['phase'] = 'collecting', progress = 0;
  if (recon.length && settled === recon.length && !found && !finding) { phase = 'ready'; progress = 1; }
  else if (recon.length || go) {
    phase = 'building';
    // Each object walks finding (0.1) -> found (0.3) -> building (0.6) -> done (1).
    const total = recon.length + found + finding;
    progress = Math.max(0.05, (settled + 0.6 * (recon.length - settled) + 0.3 * found + 0.1 * finding) / Math.max(1, total));
    const mineFinding = uploads.some((u) => u.uploader_user_id === me() && u.selections.some((s) => s.status === 'pending'));
    if (go && !mineFinding) void autoGenerate(k.project_id, uploads);
  }
  return {
    id: k.project_id, title: k.name, scene: sceneOf(k.name, i), photos: [], members, phase, progress,
    createdAt: t(contributors[0]?.joined_at), objects: [],
    ...(k.forced ? { members: members.filter((m) => m.status === 'done') } : null),
  };
}

async function loadOne(k: KnownProject, i: number): Promise<Room | null> {
  const account = me();
  try {
    const [project, contributors, uploads, assets] = await Promise.all([
      getProject(k.project_id), listContributors(k.project_id), listUploads(k.project_id), listProjectAssets(k.project_id),
    ]);
    if (project.invite_code && project.invite_code !== k.invite_code) updateKnownProject(k.project_id, { invite_code: project.invite_code, creator: project.created_by ?? k.creator });
    const room = toRoom({ ...k, name: project.name }, i, contributors, uploads, assets, project.created_by);
    const first = uploads[0];
    if (first) room.cover = await coverFor(k.project_id, first.upload_id);
    return room;
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 404) { forgetProject(k.project_id); return null; }
    // 403: not a member yet. An invitation if we hold the code and haven't declined it.
    if (e.status !== 403 || !k.invite_code || k.declinedBy?.includes(account)) return null;
    const owner = accountLabel(k.creator ?? '');
    return {
      id: k.project_id, title: k.name, scene: sceneOf(k.name, i), photos: [], phase: 'collecting', progress: 0,
      invitedBy: owner, createdAt: Date.now(), objects: [],
      members: [
        { id: 'owner', name: owner, email: k.creator ?? 'owner', status: 'joined', isOwner: true, invitedAt: Date.now() },
        { ...ME, name: accountLabel(account), email: account, status: 'invited', invitedAt: Date.now() },
      ],
    };
  }
}

let inflight: Promise<void> | null = null;
/** Refetch every room this browser knows about into the shared room store. */
export function syncRooms(): Promise<void> {
  inflight ??= (async () => {
    try {
      const rooms = await Promise.all(listKnownProjects().map(loadOne));
      useRooms.setState({ rooms: rooms.filter((r): r is Room => !!r), synced: true });
    } catch {
      useRooms.setState({ synced: true }); // backend down: show what we have rather than spin forever
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

export async function createRoom(title: string): Promise<string> {
  const account = me();
  const p = await createProject({ name: title.trim() || 'Untitled room', creator_display_name: accountLabel(account) });
  rememberProject({ project_id: p.project_id, name: p.name, invite_code: p.invite_code, creator: account });
  await syncRooms();
  return p.project_id;
}

export async function join(id: string) {
  const k = listKnownProjects().find((p) => p.project_id === id);
  await createContributor(id, { display_name: accountLabel(me()), invite_code: k?.invite_code || null });
  await syncRooms();
}

export function decline(id: string) {
  const k = listKnownProjects().find((p) => p.project_id === id);
  updateKnownProject(id, { declinedBy: [...(k?.declinedBy ?? []), me()] });
  void syncRooms();
}

/** Forget locally; the backend has no delete or leave route. */
export function remove(id: string) {
  forgetProject(id);
  useRooms.setState({ rooms: useRooms.getState().rooms.filter((r) => r.id !== id) });
}

export function startBuilding(id: string) {
  updateKnownProject(id, { forced: true });
  void syncRooms();
}

/**
 * Upload each photo, then ask for the named objects in it (note becomes each
 * object's memory text). No names given: let the backend suggest the subject.
 */
export async function addPhotos(id: string, files: File[], note: string, ownerObjects?: string[]) {
  if (ownerObjects) updateKnownProject(id, { objects: ownerObjects });
  const objects = ownerObjects ?? listKnownProjects().find((p) => p.project_id === id)?.objects ?? [];
  const memory = note.trim().slice(0, 1000) || undefined;
  await Promise.all(files.map(async (f) => {
    const up = await createUpload(id, f);
    if (objects.length) await createSelections(id, up.upload_id, objects.map((text) => ({ selection_id: newId(), prompt: { text }, memory_text: memory })));
    else await detectUploadObjects(id, up.upload_id);
  }));
  await syncRooms();
}
