import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useAccount } from './account';
import { ApiError, createProject, getProject } from './client';

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
}

beforeEach(() => {
  useAccount.setState({ current: 'demo-alice' });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test('every request sends X-SketchScape-Dev-User from the account picker store', async () => {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    void init;
    return jsonResponse(200, { project_id: 'p1', name: 'Test' });
  });
  vi.stubGlobal('fetch', fetchMock);

  useAccount.getState().setAccount('demo-bob');
  await getProject('p1');

  expect(fetchMock).toHaveBeenCalledTimes(1);
  const init = fetchMock.mock.calls[0][1];
  const headers = init?.headers as Record<string, string>;
  expect(headers['X-SketchScape-Dev-User']).toBe('demo-bob');
});

test('401 maps to a "choose an account" message', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(401, { detail: 'nope' })));
  await expect(getProject('p1')).rejects.toMatchObject({ message: 'Choose an account to continue.', status: 401 });
});

test('409 surfaces the server detail verbatim', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(409, { detail: 'Already a contributor of this project.' })));
  await expect(getProject('p1')).rejects.toMatchObject({ message: 'Already a contributor of this project.', status: 409 });
});

test('413 maps to a file-too-large message regardless of server detail', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(413, { detail: 'Artifact exceeds the 16 MB limit.' })));
  await expect(getProject('p1')).rejects.toMatchObject({ message: 'That file is too large (16 MB max).', status: 413 });
});

test('415 surfaces the unsupported-file-type detail', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(415, { detail: 'Unsupported image type.' })));
  await expect(getProject('p1')).rejects.toMatchObject({ message: 'Unsupported image type.', status: 415 });
});

test('a successful call resolves with the parsed JSON body', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(201, { project_id: 'p2', name: 'Room' })));
  const project = await createProject({ name: 'Room' });
  expect(project).toMatchObject({ project_id: 'p2', name: 'Room' });
});

test('ApiError carries the status for callers that branch on it', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(403, { detail: "Not a member of this project." })));
  try {
    await getProject('p1');
    throw new Error('expected getProject to reject');
  } catch (err) {
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(403);
  }
});
