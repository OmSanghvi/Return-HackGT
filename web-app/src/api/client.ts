// Typed client for SketchScape's real backend (Build Plan steps 19/20/26).
// Every request carries X-SketchScape-Dev-User from the account picker's
// stored value -- no bearer token, no getToken() call (there is no Clerk in
// this plan). See web-app-foundation and durable-jobs-and-multi-object-upload.
import { API_BASE_URL } from '../config';
import { useAccount } from './account';
import type {
  Contributor,
  ContributorCreateRequest,
  GenerateResponse,
  JobIdResponse,
  Letter,
  LetterOpenResponse,
  LetterView,
  ProjectAsset,
  ProjectCreateRequest,
  ProjectRecord,
  ProjectUpdateRequest,
  ReconstructionJob,
  RoomBuild,
  RoomBuildCreateRequest,
  SelectionsRequestItem,
  UploadCreateResponse,
  UploadRecord,
} from './types';

/** Raised for every non-2xx response, with a message a screen can show as-is. */
export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** Maps a status code to the reader-friendly message the web-app-foundation skill specifies. */
function messageFor(status: number, detail: string): string {
  switch (status) {
    case 401:
      return 'Choose an account to continue.';
    case 403:
      return detail || "You're not a member of this project.";
    case 409:
      return detail || 'That change conflicts with something that already happened. Refresh and try again.';
    case 413:
      return 'That file is too large (16 MB max).';
    case 415:
      return detail || 'Unsupported file type. Use JPEG, PNG, or WebP.';
    case 422:
      return detail || 'That input is not valid.';
    case 404:
      return detail || "That couldn't be found.";
    default:
      return detail || `Something went wrong (${status}).`;
  }
}

async function readDetail(res: Response): Promise<string> {
  try {
    const body = await res.clone().json();
    if (typeof body?.detail === 'string') return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((d: { msg?: string }) => d.msg).join('; ');
  } catch {
    // Not JSON (or already consumed) -- fall through to an empty detail.
  }
  return '';
}

async function throwIfError(res: Response): Promise<void> {
  if (res.ok) return;
  const detail = await readDetail(res);
  throw new ApiError(res.status, detail, messageFor(res.status, detail));
}

function url(path: string): string {
  return `${API_BASE_URL}${path}`;
}

function authHeaders(): Record<string, string> {
  return { 'X-SketchScape-Dev-User': useAccount.getState().current };
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(url(path), { headers: authHeaders() });
  await throwIfError(res);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(url(path), {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  await throwIfError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(url(path), {
    method: 'PATCH',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  await throwIfError(res);
  return (await res.json()) as T;
}

async function del(path: string): Promise<void> {
  const res = await fetch(url(path), { method: 'DELETE', headers: authHeaders() });
  await throwIfError(res);
}

/**
 * A GET carrying its own image/binary payload, returned as an object URL the
 * caller must revoke. Needed because upload/mask/asset image routes require
 * the X-SketchScape-Dev-User header, and a plain `<img src>` can't send one.
 */
export async function fetchImageObjectUrl(path: string): Promise<string> {
  const res = await fetch(url(path), { headers: authHeaders() });
  await throwIfError(res);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/**
 * Multipart upload with progress, via XMLHttpRequest (fetch has no upload
 * progress event -- web-app-foundation skill).
 */
export function uploadFileWithProgress<T>(
  path: string,
  fieldName: string,
  file: File | Blob,
  filename: string,
  extraFields: Record<string, string> = {},
  onProgress?: (fraction: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url(path));
    xhr.setRequestHeader('X-SketchScape-Dev-User', useAccount.getState().current);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new ApiError(0, '', 'Network error during upload.'));
    xhr.onload = () => {
      const ok = xhr.status >= 200 && xhr.status < 300;
      let detail = '';
      let parsed: unknown = undefined;
      try {
        parsed = JSON.parse(xhr.responseText);
        detail = typeof (parsed as { detail?: string })?.detail === 'string' ? (parsed as { detail: string }).detail : '';
      } catch {
        // Non-JSON response body (rare, e.g. a proxy error page).
      }
      if (!ok) {
        reject(new ApiError(xhr.status, detail, messageFor(xhr.status, detail)));
        return;
      }
      resolve(parsed as T);
    };
    const form = new FormData();
    form.append(fieldName, file, filename);
    for (const [key, value] of Object.entries(extraFields)) form.append(key, value);
    xhr.send(form);
  });
}

// ---------------------------------------------------------------------------
// Projects, membership, room prompt (steps 17/19)
// ---------------------------------------------------------------------------

export function createProject(body: ProjectCreateRequest): Promise<ProjectRecord> {
  return postJson('/v1/projects', body);
}

export function getProject(projectId: string): Promise<ProjectRecord> {
  return getJson(`/v1/projects/${projectId}`);
}

export function updateProject(projectId: string, body: ProjectUpdateRequest): Promise<ProjectRecord> {
  return patchJson(`/v1/projects/${projectId}`, body);
}

export function rotateInvite(projectId: string): Promise<ProjectRecord> {
  return postJson(`/v1/projects/${projectId}/invite/rotate`);
}

export function createContributor(projectId: string, body: ContributorCreateRequest): Promise<Contributor> {
  return postJson(`/v1/projects/${projectId}/contributors`, body);
}

export function listContributors(projectId: string): Promise<Contributor[]> {
  return getJson(`/v1/projects/${projectId}/contributors`);
}

export function listProjectAssets(projectId: string): Promise<ProjectAsset[]> {
  return getJson(`/v1/projects/${projectId}/assets`);
}

// ---------------------------------------------------------------------------
// Uploads -> selections -> refine -> generate (step 20/26)
// ---------------------------------------------------------------------------

/**
 * `note` is the uploader's personal note for this photo (≤ 1000 chars). It
 * rides along as a `note` form field so it survives an image-only upload
 * (no typed names, so no selection carries it as memory text); a backend
 * that doesn't read the field yet simply ignores it.
 */
export function createUpload(
  projectId: string,
  file: File,
  onProgress?: (fraction: number) => void,
  note?: string,
): Promise<UploadCreateResponse> {
  const extra: Record<string, string> = {};
  const trimmed = note?.trim().slice(0, 1000);
  if (trimmed) extra.note = trimmed;
  return uploadFileWithProgress(`/v1/projects/${projectId}/uploads`, 'image', file, file.name, extra, onProgress);
}

export function listUploads(projectId: string): Promise<UploadRecord[]> {
  return getJson(`/v1/projects/${projectId}/uploads`);
}

export function getUpload(projectId: string, uploadId: string): Promise<UploadRecord> {
  return getJson(`/v1/projects/${projectId}/uploads/${uploadId}`);
}

/** The uploader sets or edits their photo's personal note (≤ 1000 chars; uploader only, 403 otherwise). */
export function updateUploadNote(projectId: string, uploadId: string, note: string): Promise<UploadRecord> {
  return patchJson(`/v1/projects/${projectId}/uploads/${uploadId}`, { note: note.trim().slice(0, 1000) });
}

export function createSelections(
  projectId: string,
  uploadId: string,
  selections: SelectionsRequestItem[],
): Promise<JobIdResponse> {
  return postJson(`/v1/projects/${projectId}/uploads/${uploadId}/selections`, { selections });
}

export function refineSelection(
  projectId: string,
  uploadId: string,
  selectionId: string,
  text: string,
): Promise<JobIdResponse> {
  return postJson(`/v1/projects/${projectId}/uploads/${uploadId}/selections/${selectionId}/refine`, { text });
}

export function deleteSelection(projectId: string, uploadId: string, selectionId: string): Promise<void> {
  return del(`/v1/projects/${projectId}/uploads/${uploadId}/selections/${selectionId}`);
}

export function detectUploadObjects(projectId: string, uploadId: string): Promise<JobIdResponse> {
  return postJson(`/v1/projects/${projectId}/uploads/${uploadId}/detect`);
}

export function generateSelectedObjects(
  projectId: string,
  uploadId: string,
  selectionIds: string[],
): Promise<GenerateResponse> {
  return postJson(`/v1/projects/${projectId}/uploads/${uploadId}/generate`, { selection_ids: selectionIds });
}

// ---------------------------------------------------------------------------
// Notability sketches (step 7/20) -- flat card only from the web app for now.
// ---------------------------------------------------------------------------

export function createSketchCard(
  projectId: string,
  file: File,
  label: string,
  onProgress?: (fraction: number) => void,
): Promise<ProjectAsset> {
  return uploadFileWithProgress(
    `/v1/projects/${projectId}/sketch-assets`,
    'image',
    file,
    file.name,
    { label, display: 'card' },
    onProgress,
  );
}

// ---------------------------------------------------------------------------
// Batch job polling (step 26) -- see api/polling.ts for the ETag/backoff loop.
// ---------------------------------------------------------------------------

export interface JobsPage {
  jobs: ReconstructionJob[];
  etag: string | null;
  notModified: boolean;
  retryAfterMs: number | null;
}

// ---------------------------------------------------------------------------
// Letters (step 28) -- sealed/opened, recipient-only open.
// ---------------------------------------------------------------------------

/**
 * Multipart create with a repeated `recipient_contributor_ids` field --
 * `uploadFileWithProgress`'s `extraFields` only sends one value per key, so
 * this builds its own `FormData` (no upload-progress bar; the page is small).
 */
export async function createLetter(
  projectId: string,
  page: File,
  authorContributorId: string,
  recipientContributorIds: string[],
  noteText: string,
): Promise<Letter> {
  const form = new FormData();
  form.append('page', page, page.name);
  form.append('author_contributor_id', authorContributorId);
  for (const id of recipientContributorIds) form.append('recipient_contributor_ids', id);
  if (noteText.trim()) form.append('note_text', noteText.trim());
  const res = await fetch(url(`/v1/projects/${projectId}/letters`), {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  });
  await throwIfError(res);
  return (await res.json()) as Letter;
}

export function listLetters(projectId: string): Promise<LetterView[]> {
  return getJson(`/v1/projects/${projectId}/letters`);
}

export function openLetter(projectId: string, letterId: string): Promise<LetterOpenResponse> {
  return postJson(`/v1/rooms/${projectId}/letters/${letterId}/open`);
}

// ---------------------------------------------------------------------------
// Room builds (docs/WEB_TO_QUEST_PIPELINE.md §1) -- "Build room in VR".
// 409 on create: no stored scene yet, or a build is already running.
// ---------------------------------------------------------------------------

export function createRoomBuild(projectId: string, body: RoomBuildCreateRequest = {}): Promise<RoomBuild> {
  return postJson(`/v1/projects/${projectId}/room-builds`, body);
}

/** Newest first, at most 20. */
export function listRoomBuilds(projectId: string): Promise<RoomBuild[]> {
  return getJson(`/v1/projects/${projectId}/room-builds`);
}

export function getRoomBuild(projectId: string, buildId: string): Promise<RoomBuild> {
  return getJson(`/v1/projects/${projectId}/room-builds/${buildId}`);
}

/** A member gives up on an active build (it becomes `failed`, "Cancelled by ..."); 409 once it's already finished. */
export function cancelRoomBuild(projectId: string, buildId: string): Promise<RoomBuild> {
  return postJson(`/v1/projects/${projectId}/room-builds/${buildId}/cancel`);
}

export async function listProjectJobs(
  projectId: string,
  opts: { active?: boolean; etag?: string | null } = {},
): Promise<JobsPage> {
  const params = new URLSearchParams();
  if (opts.active) params.set('active', '1');
  const headers = authHeaders();
  if (opts.etag) headers['If-None-Match'] = opts.etag;
  const res = await fetch(url(`/v1/projects/${projectId}/jobs?${params.toString()}`), { headers });
  const retryAfterHeader = res.headers.get('Retry-After');
  const retryAfterMs = retryAfterHeader ? Number(retryAfterHeader) * 1000 : null;
  if (res.status === 304) {
    return { jobs: [], etag: opts.etag ?? null, notModified: true, retryAfterMs };
  }
  await throwIfError(res);
  const jobs = (await res.json()) as ReconstructionJob[];
  return { jobs, etag: res.headers.get('ETag'), notModified: false, retryAfterMs };
}
