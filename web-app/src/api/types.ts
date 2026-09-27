// TypeScript mirrors of the backend Pydantic models this client talks to
// (backend/main.py). Keep field names and optionality in lockstep with that
// file -- these are hand-written, not generated, so a backend field rename
// silently breaks the type here instead of failing a build.

export interface ProjectRecord {
  project_id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  asset_ids: string[];
  blueprint_revisions: number[];
  published_revision: number | null;
  contributor_ids: string[];
  contribution_ids: string[];
  min_contributors: number;
  max_contributors: number;
  /** Empty for a non-member (visible_project strips it server-side). */
  invite_code: string;
  room_prompt: string | null;
  created_by?: string | null;
}

export interface Contributor {
  contributor_id: string;
  project_id: string;
  display_name: string;
  joined_at: string;
  clerk_user_id: string | null;
}

export type ContributionSourceType = 'photo' | 'sketch' | 'letter';

export interface Contribution {
  contribution_id: string;
  project_id: string;
  contributor_id: string;
  asset_id: string;
  source_type: ContributionSourceType;
  memory_text: string;
  created_at: string;
}

export type SelectionStatus = 'pending' | 'segmented' | 'failed' | 'generated';
export type SelectionOrigin = 'person' | 'suggested';

export interface SelectionPrompt {
  text: string;
}

export interface UploadSelection {
  selection_id: string;
  prompt: SelectionPrompt;
  label: string | null;
  memory_text: string;
  status: SelectionStatus;
  mask_key: string | null;
  preview_key: string | null;
  score: number | null;
  alternatives: Record<string, unknown>[];
  origin: SelectionOrigin;
  mask_preview_url: string | null;
  /** Set by /generate: the ProjectAsset this selection became. */
  asset_id?: string | null;
}

export interface UploadRecord {
  upload_id: string;
  project_id: string;
  uploader_user_id: string;
  image_key: string;
  width: number;
  height: number;
  created_at: string;
  original_filename: string;
  selections: UploadSelection[];
  /** The uploader's personal note, when the backend stores it (sent as the upload's `note` form field). */
  note?: string | null;
}

export interface UploadCreateResponse {
  upload_id: string;
  image_url: string;
  width: number;
  height: number;
}

export interface JobIdResponse {
  job_id: string | null;
}

export type JobStatus = 'queued' | 'running' | 'mask_review' | 'complete' | 'failed';
export type JobKind = 'segment' | 'reconstruct';

export interface ReconstructionJob {
  job_id: string;
  status: JobStatus;
  poll_url: string;
  scene_url: string;
  created_at: string;
  updated_at: string;
  original_filename: string;
  subject_hint: string | null;
  project_id: string | null;
  asset_id: string | null;
  mask_url: string | null;
  artifact_url: string | null;
  error: string | null;
  kind: JobKind;
  upload_id: string | null;
  selection_ids: string[];
}

export type AssetStatus = 'processing' | 'ready' | 'mask_review' | 'failed';
export type AssetKind = 'reconstruction' | 'sketch_card' | 'letter';

export interface AssetView {
  view_index: number;
  image_key: string;
  subject_hint: string | null;
  reconstruction_job_id: string;
  status: string;
  artifact_url: string | null;
  mask_url: string | null;
  preview_url: string | null;
  error: string | null;
  recorded_at: string;
}

export interface ProjectAsset {
  asset_id: string;
  project_id: string;
  label: string;
  status: AssetStatus;
  kind: AssetKind;
  reconstruction_job_id: string;
  artifact_url: string | null;
  mask_url: string | null;
  preview_url: string | null;
  bounds: [number, number, number];
  suggested_scale: [number, number, number];
  error: string | null;
  views: AssetView[];
}

export interface GenerateResponse {
  assets: ProjectAsset[];
  jobs: ReconstructionJob[];
}

export interface ProjectCreateRequest {
  name: string;
  description?: string;
  creator_display_name?: string;
}

export interface ProjectUpdateRequest {
  room_prompt?: string | null;
}

export interface ContributorCreateRequest {
  display_name: string;
  invite_code?: string | null;
}

export interface SelectionsRequestItem {
  selection_id: string;
  prompt: SelectionPrompt;
  label?: string | null;
  memory_text?: string;
}

// ---------------------------------------------------------------------------
// Letters (step 28) -- sealed/opened, recipient-only open.
// ---------------------------------------------------------------------------

export type EnvelopeStyle = 'classic';

export interface Letter {
  letter_id: string;
  project_id: string;
  author_contributor_id: string;
  recipient_contributor_ids: string[];
  asset_id: string;
  contribution_id: string;
  aspect_ratio: number;
  note_text: string;
  envelope_style: EnvelopeStyle;
  created_at: string;
}

/** What `GET /v1/projects/{id}/letters` returns: `note_text`/`image_url` are
 * only populated when the caller may see them (author, recipient, or --
 * once opened -- anyone). */
export interface LetterView {
  letter_id: string;
  author_contributor_id: string;
  recipient_contributor_ids: string[];
  envelope_style: EnvelopeStyle;
  aspect_ratio: number;
  sealed: boolean;
  opened_by: string[];
  note_text: string | null;
  image_url: string | null;
}

export interface LetterOpenResponse {
  opened: boolean;
  opened_by: string;
  opened_at: string;
}

// ---------------------------------------------------------------------------
// Room builds (docs/WEB_TO_QUEST_PIPELINE.md §1) -- "Build room in VR". Every
// field is a string, "" when unknown. `apk_path` stays "" (no APK, §6) and
// `packaging` is unused, but both are still typed so an older build reads.
// ---------------------------------------------------------------------------

export type RoomBuildStatus = 'requested' | 'claimed' | 'syncing' | 'building' | 'packaging' | 'ready' | 'failed';

export interface RoomBuild {
  build_id: string;
  project_id: string;
  requested_by: string;
  prompt: string;
  scene_id: string;
  status: RoomBuildStatus;
  message: string;
  slug: string;
  scene_path: string;
  apk_path: string;
  runner_id: string;
  created_at: string;
  updated_at: string;
}

export interface RoomBuildCreateRequest {
  prompt?: string;
  scene_id?: string;
}
