import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { JobsPage } from './client';
import * as client from './client';
import { pollProjectJobs } from './polling';
import type { ReconstructionJob } from './types';

function job(id: string, overrides: Partial<ReconstructionJob> = {}): ReconstructionJob {
  return {
    job_id: id,
    status: 'running',
    poll_url: `/v1/reconstructions/${id}`,
    scene_url: '/v1/scene',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    original_filename: '',
    subject_hint: null,
    project_id: 'p1',
    asset_id: null,
    mask_url: null,
    artifact_url: null,
    error: null,
    kind: 'segment',
    upload_id: 'u1',
    selection_ids: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

test('reports the active set, then settled jobs once they drop out, then goes idle', async () => {
  const j1 = job('j1');
  const pages: JobsPage[] = [
    { jobs: [j1], etag: 'a', notModified: false, retryAfterMs: null },
    { jobs: [], etag: 'b', notModified: false, retryAfterMs: null },
  ];
  let call = 0;
  vi.spyOn(client, 'listProjectJobs').mockImplementation(async () => pages[Math.min(call++, pages.length - 1)]);

  const active: ReconstructionJob[][] = [];
  const settled: ReconstructionJob[][] = [];
  let idle = false;

  pollProjectJobs('p1', {
    onActive: (jobs) => active.push(jobs),
    onSettled: (jobs) => settled.push(jobs),
    onIdle: () => {
      idle = true;
    },
  });

  await vi.advanceTimersByTimeAsync(0); // first tick, scheduled immediately
  expect(active).toEqual([[j1]]);
  expect(idle).toBe(false);

  await vi.advanceTimersByTimeAsync(2_500); // >2s (with jitter) triggers the next poll
  expect(settled).toEqual([[j1]]);
  expect(idle).toBe(true);
});

test('stop() prevents any further polling', async () => {
  vi.spyOn(client, 'listProjectJobs').mockResolvedValue({ jobs: [job('j1')], etag: 'a', notModified: false, retryAfterMs: null });
  const handle = pollProjectJobs('p1', {});
  await vi.advanceTimersByTimeAsync(0);
  handle.stop();
  const callsBefore = (client.listProjectJobs as unknown as ReturnType<typeof vi.fn>).mock.calls.length;
  await vi.advanceTimersByTimeAsync(60_000);
  expect((client.listProjectJobs as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsBefore);
});
