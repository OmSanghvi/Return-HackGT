import { describe, expect, it } from 'vitest';
import type { RoomBuild } from '../api/types';
import { BUILD_STEPS, MOCK_TIMELINE, SLOW_PICKUP_MS, buildStatusLine, buildStep, isActiveBuild, mockBuildAt, slugify, type MockBuildSeed } from './vrBuild';

const seed: MockBuildSeed = { build_id: 'b1', project_id: 'p1', title: "Grandma's Porch", prompt: 'warm light', requested_by: 'me', started_at: 1_000_000 };

describe('room build helpers', () => {
  it('maps every contract status onto a step, unknown ones to the first', () => {
    expect(buildStep('requested')).toBe(0);
    expect(buildStep('claimed')).toBe(0);
    expect(buildStep('syncing')).toBe(1);
    expect(buildStep('building')).toBe(2);
    expect(buildStep('packaging')).toBe(2);
    expect(buildStep('ready')).toBe(BUILD_STEPS.length - 1);
    expect(buildStep('something-new')).toBe(0);
  });

  it('treats only ready and failed as terminal', () => {
    const at = (status: RoomBuild['status']) => ({ ...mockBuildAt(seed, seed.started_at), status });
    for (const s of ['requested', 'claimed', 'syncing', 'building', 'packaging'] as const) expect(isActiveBuild(at(s))).toBe(true);
    expect(isActiveBuild(at('ready'))).toBe(false);
    expect(isActiveBuild(at('failed'))).toBe(false);
    expect(isActiveBuild(null)).toBe(false);
  });

  it('says when the builder seems slow to pick a build up, and shows the failure message', () => {
    const b = mockBuildAt(seed, seed.started_at);
    expect(buildStatusLine(b, 0)).toMatch(/Waiting for the room builder/);
    expect(buildStatusLine(b, SLOW_PICKUP_MS + 1)).toMatch(/Still queued/);
    expect(buildStatusLine({ ...b, status: 'failed', message: 'Unity MCP is not reachable.' })).toBe('Unity MCP is not reachable.');
    expect(buildStatusLine({ ...b, status: 'failed', message: '' })).toMatch(/went wrong/);
    expect(buildStatusLine({ ...b, status: 'failed', message: 'Cancelled by demo-bob.' })).toBe('Stopped by Bob.');
  });

  it('slugifies room titles the way a room name reads', () => {
    expect(slugify("Grandma's Porch")).toBe('grandma-s-porch');
    expect(slugify('  Café  Lumière ')).toBe('cafe-lumiere');
    expect(slugify('!!!')).toBe('room');
  });

  it('walks the mock build through the timeline and ends ready with a room name, never an APK', () => {
    const seen = MOCK_TIMELINE.map(([status, at]) => [status, mockBuildAt(seed, seed.started_at + at).status]);
    for (const [want, got] of seen) expect(got).toBe(want);
    const done = mockBuildAt(seed, seed.started_at + 60_000);
    expect(done.status).toBe('ready');
    expect(done.slug).toBe('grandma-s-porch');
    expect(done.scene_path).toBe('Assets/SketchScape/AgentRooms/grandma-s-porch.unity');
    expect(done.apk_path).toBe('');
    expect(mockBuildAt(seed, seed.started_at + 1000)).toMatchObject({ status: 'requested', slug: '', runner_id: '' });
  });
});
