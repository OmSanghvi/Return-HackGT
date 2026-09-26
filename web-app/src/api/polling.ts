// One project-level job-polling loop (docs/DATA_ARCHITECTURE.md's polling
// contract, also stated in web-uploads-and-linking): ETag/If-None-Match,
// backoff that steps up the longer a poll runs, jitter, a pause while the
// tab is hidden, and Retry-After honored when the server sends it. Every
// upload/selection/generate screen shares this one loop instead of one
// poll per object.
//
// `GET .../jobs?active=1` only ever returns queued/running/mask_review jobs
// (durable-jobs-and-multi-object-upload), so a job's *final* status never
// shows up here -- it just drops out of the list. This loop tracks which job
// ids were active on the last poll and reports the ones that disappeared as
// "settled", carrying their last known upload_id/asset_id so the caller
// knows which record to re-fetch (GET the upload, or list project assets)
// to learn whether it succeeded or failed.
import { listProjectJobs } from './client';
import type { ReconstructionJob } from './types';

const JITTER = 0.2;

function withJitter(ms: number): number {
  const delta = ms * JITTER;
  return ms - delta + Math.random() * 2 * delta;
}

/** 2s for the first 20s of polling, then 5s, then 10s after 2 minutes. */
function intervalFor(elapsedMs: number): number {
  if (elapsedMs < 20_000) return 2_000;
  if (elapsedMs < 120_000) return 5_000;
  return 10_000;
}

export interface JobPollHandle {
  stop: () => void;
}

export interface JobPollCallbacks {
  /** Called with the current set of in-flight jobs every time it changes. */
  onActive?: (jobs: ReconstructionJob[]) => void;
  /** Called with jobs that just left the active set (their last known snapshot). */
  onSettled?: (jobs: ReconstructionJob[]) => void;
  /**
   * Called whenever the active set is empty, including on the very first
   * poll -- a job can complete (mock mode especially) before the first tick
   * ever sees it as active, so `onSettled` alone can miss it. The caller
   * should treat this as "safe to re-fetch anything you're waiting on."
   */
  onIdle?: () => void;
  onError?: (error: unknown) => void;
}

export function pollProjectJobs(projectId: string, callbacks: JobPollCallbacks): JobPollHandle {
  let stopped = false;
  let etag: string | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastById = new Map<string, ReconstructionJob>();
  const startedAt = Date.now();

  const schedule = (delayMs: number) => {
    if (stopped) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(tick, delayMs);
  };

  async function tick() {
    if (stopped) return;
    if (typeof document !== 'undefined' && document.hidden) {
      // Pause while the tab is hidden; re-check shortly instead of a network call.
      schedule(1_000);
      return;
    }
    try {
      const page = await listProjectJobs(projectId, { active: true, etag });
      if (!page.notModified) {
        etag = page.etag;
        const nextById = new Map(page.jobs.map((j) => [j.job_id, j] as const));
        const settled = [...lastById.entries()]
          .filter(([id]) => !nextById.has(id))
          .map(([, job]) => job);
        lastById = nextById;
        callbacks.onActive?.(page.jobs);
        if (settled.length) callbacks.onSettled?.(settled);
        if (nextById.size === 0) {
          callbacks.onIdle?.();
          stopped = true;
          return;
        }
      }
      const base = page.retryAfterMs ?? intervalFor(Date.now() - startedAt);
      schedule(withJitter(base));
    } catch (error) {
      callbacks.onError?.(error);
      // Back off on error too, rather than hammering a struggling backend.
      schedule(withJitter(intervalFor(Date.now() - startedAt)));
    }
  }

  const onVisibility = () => {
    if (!stopped && typeof document !== 'undefined' && !document.hidden) {
      // Coming back into view: poll right away instead of waiting out the pause.
      schedule(0);
    }
  };
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibility);

  schedule(0);

  return {
    stop: () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility);
    },
  };
}
