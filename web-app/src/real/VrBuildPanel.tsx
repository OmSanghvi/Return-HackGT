// "Build room in VR" (docs/WEB_TO_QUEST_PIPELINE.md §1): ask the Unity
// machine's room builder (NemoClaw, through Unity MCP) to turn this project's
// photos into a VR room, then follow it live.
//
// Real mode: POST /room-builds, then poll the build every 4 s while it isn't
// ready/failed (and the list every 12 s otherwise, so a build the other
// account starts shows up here too). Mock mode: a timed stand-in (vrBuild.ts)
// that ends on "Ready in VR", so the offline demo still works.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Field, Icon, StatusTag } from '../ui';
import { ApiError, cancelRoomBuild, createRoomBuild, getRoomBuild, listRoomBuilds } from '../api/client';
import type { RoomBuild } from '../api/types';
import { accountLabel, useAccount } from '../api/account';
import { REAL_MODE } from '../config';
import { ME, agoText } from '../data/store';
import { BUILD_STEPS, buildStatusLine, buildStep, isActiveBuild, mockBuildAt, slugify, useMockBuilds } from './vrBuild';
import './vrBuild.css';

const POLL_MS = 4000; // an active build
const WATCH_MS = 12000; // nothing running: notice a build someone else starts
const RECHECK_MS = 30000; // a server without room builds yet

const NO_SCENE_HINT =
  "The room's 3D scene isn't ready yet. It's made from your photos once they finish processing, so give it a minute and try again.";

interface VrBuildState {
  build: RoomBuild | null;
  loaded: boolean;
  /** The server has no room-build routes (404): say so instead of offering a button that can't work. */
  unavailable: boolean;
  /** The last poll couldn't reach the server (API restarting, network blip); the loop keeps trying. */
  offline: boolean;
  starting: boolean;
  hint: string;
  hintDetail: string;
  error: string;
  /** Resolves true when a build was created (or an already-running one adopted). */
  start(prompt: string): Promise<boolean>;
  /** Give up on the active build (real mode only; null hides the control). */
  stop: (() => Promise<void>) | null;
}

function useRealBuild(projectId: string): VrBuildState {
  const account = useAccount((s) => s.current);
  const [build, setBuild] = useState<RoomBuild | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [offline, setOffline] = useState(false);
  const [starting, setStarting] = useState(false);
  const [hint, setHint] = useState('');
  const [hintDetail, setHintDetail] = useState('');
  const [error, setError] = useState('');
  const alive = useRef(true);
  // Set on every mount: StrictMode's dev-only unmount/remount would otherwise leave it false for good.
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const refreshList = useCallback(async (): Promise<RoomBuild | null> => {
    try {
      const latest = (await listRoomBuilds(projectId))[0] ?? null;
      if (!alive.current) return latest;
      setBuild(latest);
      setUnavailable(false);
      setOffline(false);
      setLoaded(true);
      return latest;
    } catch (e) {
      if (!alive.current) return null;
      if (e instanceof ApiError && e.status === 404) {
        setUnavailable(true);
        setLoaded(true);
      } else if (e instanceof ApiError && e.status === 403) {
        setError('Join this room to build it in VR.');
        setLoaded(true);
      } else if (e instanceof ApiError && e.status === 401) {
        setError(e.message);
        setLoaded(true);
      } else {
        setOffline(true);
      }
      return null;
    }
  }, [projectId]);

  // First look, and again whenever the account switches (membership decides what we may see).
  useEffect(() => {
    setLoaded(false);
    setError('');
    setHint('');
    setHintDetail('');
    void refreshList();
  }, [refreshList, account]);

  const active = isActiveBuild(build);
  const buildId = build?.build_id;
  useEffect(() => {
    const every = unavailable ? RECHECK_MS : active ? POLL_MS : WATCH_MS;
    const timer = setInterval(async () => {
      if (document.hidden) return;
      if (!active || !buildId) {
        void refreshList();
        return;
      }
      try {
        const next = await getRoomBuild(projectId, buildId);
        if (!alive.current) return;
        setBuild(next);
        setOffline(false);
      } catch (e) {
        if (!alive.current) return;
        if (e instanceof ApiError && e.status === 404) void refreshList();
        else if (!(e instanceof ApiError) || e.status === 0 || e.status >= 500) setOffline(true);
      }
    }, every);
    return () => clearInterval(timer);
  }, [projectId, active, buildId, unavailable, refreshList]);

  const start = useCallback(
    async (prompt: string) => {
      setStarting(true);
      setHint('');
      setHintDetail('');
      setError('');
      try {
        const text = prompt.trim().slice(0, 1000);
        const created = await createRoomBuild(projectId, text ? { prompt: text } : {});
        if (alive.current) {
          setBuild(created);
          setUnavailable(false);
          setOffline(false);
        }
        return true;
      } catch (e) {
        if (!alive.current) return false;
        if (e instanceof ApiError && e.status === 409) {
          // Either a build is already running (show it) or there's no stored scene yet.
          const latest = await refreshList();
          if (isActiveBuild(latest)) {
            setHint('A build was already on its way, so here is how it is going.');
            return true;
          }
          setHint(NO_SCENE_HINT);
          // The standard "no stored scene" detail says the same thing; only show something unexpected.
          if (!/scene/i.test(e.detail)) setHintDetail(e.detail);
        } else if (e instanceof ApiError && e.status === 404) {
          setUnavailable(true);
        } else if (e instanceof ApiError && e.status === 403) {
          setError('Only people in this room can build it in VR.');
        } else if (e instanceof ApiError && e.status !== 0) {
          setError(e.message);
        } else {
          setError("Couldn't reach the server. Check the connection and try again.");
        }
        return false;
      } finally {
        if (alive.current) setStarting(false);
      }
    },
    [projectId, refreshList],
  );

  const stop = useCallback(async () => {
    if (!buildId) return;
    setError('');
    try {
      const stopped = await cancelRoomBuild(projectId, buildId);
      if (alive.current) setBuild(stopped);
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && e.status === 409) void refreshList(); // it finished meanwhile: show how
      else setError(e instanceof ApiError && e.status !== 0 ? e.message : "Couldn't reach the server to stop the build.");
    }
  }, [projectId, buildId, refreshList]);

  return { build, loaded, unavailable, offline, starting, hint, hintDetail, error, start, stop };
}

function useMockBuild(projectId: string, title: string): VrBuildState {
  const seed = useMockBuilds((s) => s.builds[projectId]);
  const [now, setNow] = useState(() => Date.now());
  const build = seed ? mockBuildAt(seed, now) : null;
  const active = isActiveBuild(build);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [active]);
  const start = useCallback(
    async (prompt: string) => {
      useMockBuilds.getState().start(projectId, title, prompt.trim().slice(0, 1000), ME.id);
      setNow(Date.now());
      return true;
    },
    [projectId, title],
  );
  return { build, loaded: true, unavailable: false, offline: false, starting: false, hint: '', hintDetail: '', error: '', start, stop: null };
}

// REAL_MODE is fixed at build time, so each page always calls the same hook.
const useVrBuild = REAL_MODE ? useRealBuild : useMockBuild;

function Steps({ build }: { build: RoomBuild }) {
  const current = buildStep(build.status);
  return (
    <ol className="vr-steps" aria-label="Build progress">
      {BUILD_STEPS.map((step, i) => {
        const state = build.status === 'ready' || i < current ? 'done' : i === current ? 'now' : 'todo';
        return (
          <li key={step.label} data-state={state} aria-current={state === 'now' ? 'step' : undefined}>
            <span className="vr-step-dot">
              {state === 'done' ? <Icon name="check" size={12} strokeWidth={2.5} /> : state === 'now' ? <Icon name="spinner" size={14} strokeWidth={2} /> : i + 1}
            </span>
            {step.label}
          </li>
        );
      })}
    </ol>
  );
}

export default function VrBuildPanel({
  projectId,
  title,
  defaultPrompt = '',
  variant = 'side',
}: {
  projectId: string;
  title: string;
  /** Prefills the prompt (e.g. the project's room prompt) until the person types their own. */
  defaultPrompt?: string;
  /** `side`: the narrow glass panel on the Ready page. `wide`: a section on the project page. */
  variant?: 'side' | 'wide';
}) {
  const s = useVrBuild(projectId, title);
  const account = useAccount((st) => st.current);
  const [prompt, setPrompt] = useState(defaultPrompt);
  const typed = useRef(false);
  useEffect(() => {
    if (!typed.current) setPrompt(defaultPrompt);
  }, [defaultPrompt]);
  const [again, setAgain] = useState(false); // "Build it again" reopened the form under a finished build
  const [confirmStop, setConfirmStop] = useState(false);
  const [, setTick] = useState(0);
  const b = s.build;
  const active = isActiveBuild(b);
  // A build started meanwhile (maybe by the other account) replaces a half-typed "build again".
  useEffect(() => {
    if (active) setAgain(false);
  }, [active]);
  // Re-render every 15 s so "2 minutes ago" and the slow-pickup note stay true while nothing else changes.
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setTick((n) => n + 1), 15000);
    return () => clearInterval(timer);
  }, [active]);

  const go = async (text: string) => {
    if (await s.start(text)) setAgain(false);
  };
  const who = (id: string) => (id === account || id === ME.id ? 'you' : accountLabel(id));
  const since = (iso: string) => (iso ? agoText(Date.parse(iso)) : '');
  const waited = b?.created_at ? Date.now() - Date.parse(b.created_at) : 0;
  const showForm = s.loaded && !s.unavailable && !active && (!b || again);

  return (
    <section className={`vr-build vr-build-${variant}`} aria-label="Build room in VR">
      <div className="vr-build-head">
        <h2 className="title" style={{ margin: 0 }}>
          Build it in <em>VR</em>
        </h2>
        {b && !again && (active ? <StatusTag status="developing">{buildStep(b.status) === 0 ? 'Queued' : 'Building'}</StatusTag> : b.status === 'ready' ? <StatusTag status="ready">Ready in VR</StatusTag> : <StatusTag status="failed" />)}
      </div>

      {!s.loaded && <p className="rt-field-hint vr-quiet">Checking for an earlier build…</p>}

      {s.unavailable && (
        <p className="rt-field-hint vr-quiet">Building in VR isn't switched on for this server yet. This panel lights up on its own once it is.</p>
      )}

      {showForm && (
        <div className="vr-form">
          <p className="rt-field-hint" style={{ margin: 0 }}>
            NemoClaw turns everyone's photos, objects, notes and letters into a room you can step inside with the headset.
          </p>
          <Field
            label="Anything it should know? (optional)"
            placeholder="Warm evening light, the quilt folded on the bed"
            multiline
            rows={2}
            maxLength={1000}
            value={prompt}
            onChange={(e) => {
              typed.current = true;
              setPrompt(e.target.value);
            }}
          />
          <div className="vr-actions">
            <Button variant="primary" icon="headset" loading={s.starting} onClick={() => void go(prompt)}>
              Build room in VR
            </Button>
            {again && (
              <Button variant="ghost" onClick={() => setAgain(false)}>
                Cancel
              </Button>
            )}
          </div>
        </div>
      )}

      {b && active && (
        <div className="vr-progress">
          <Steps build={b} />
          <p className="body vr-line" role="status" aria-live="polite">
            {buildStatusLine(b, waited)}
          </p>
          {b.message && <p className="rt-field-hint vr-quiet">{b.message}</p>}
          <p className="rt-field-hint vr-quiet">
            Asked for by {who(b.requested_by)}
            {since(b.created_at) && <> · {since(b.created_at)}</>}. It keeps building if you leave this page.
          </p>
          {b.prompt && <p className="vr-quote">&ldquo;{b.prompt}&rdquo;</p>}
          {s.stop && (
            <div className="vr-actions">
              {confirmStop ? (
                <>
                  <span className="rt-field-hint">Stop building this room?</span>
                  <Button variant="ghost" size="sm" onClick={() => setConfirmStop(false)}>
                    Keep building
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => {
                      setConfirmStop(false);
                      void s.stop?.();
                    }}
                  >
                    Stop it
                  </Button>
                </>
              ) : (
                <Button variant="ghost" size="sm" onClick={() => setConfirmStop(true)}>
                  Stop this build
                </Button>
              )}
            </div>
          )}
        </div>
      )}

      {b && !active && !again && b.status === 'ready' && (
        <div className="vr-ready">
          <p className="rt-field-hint" style={{ margin: 0 }}>
            Room name
          </p>
          <code className="vr-slug">{b.slug || slugify(title)}</code>
          <p className="body" style={{ margin: 0 }}>
            It's open in Unity on the VR machine. Put on the headset to step inside, then use the Account 1 / Account 2 switcher to see each
            person's notes and letters.
          </p>
          {b.scene_path && <p className="rt-field-hint vr-path">{b.scene_path}</p>}
          <p className="rt-field-hint vr-quiet">
            Built for {who(b.requested_by)}
            {since(b.updated_at) && <> · {since(b.updated_at)}</>}
          </p>
          <div className="vr-actions">
            <Button
              variant="ghost"
              size="sm"
              icon="refresh"
              onClick={() => {
                typed.current = true;
                setPrompt(b.prompt);
                setAgain(true);
              }}
            >
              Build it again
            </Button>
          </div>
        </div>
      )}

      {b && !active && !again && b.status === 'failed' && (
        <div className="vr-failed">
          <div className="rt-field-error" role="alert">
            <Icon name="alert" size={16} />
            {buildStatusLine(b)}
          </div>
          <p className="rt-field-hint vr-quiet">Nothing is lost: your photos and objects are safe. Try again, or change what you asked for.</p>
          <div className="vr-actions">
            <Button variant="primary" size="sm" icon="refresh" loading={s.starting} onClick={() => void go(b.prompt)}>
              Try again
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                typed.current = true;
                setPrompt(b.prompt);
                setAgain(true);
              }}
            >
              Change the prompt
            </Button>
          </div>
        </div>
      )}

      {s.hint && (
        <div className="vr-hint" role="status">
          <Icon name="clock" size={16} />
          <span>
            {s.hint}
            {s.hintDetail && <span className="vr-hint-detail">{s.hintDetail}</span>}
          </span>
        </div>
      )}
      {s.error && (
        <div className="rt-field-error" role="alert">
          <Icon name="alert" size={16} />
          {s.error}
        </div>
      )}
      {s.offline && <p className="rt-field-hint vr-quiet">Reconnecting to the server…</p>}
    </section>
  );
}
