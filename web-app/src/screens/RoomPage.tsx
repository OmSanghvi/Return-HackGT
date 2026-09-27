import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { Button, DevelopProgress, Eyebrow, Icon, MemberList, PresenceStack, Stepper } from '../ui';
import { ME, mine, pending, useRooms, type Room } from '../data/store';
import { SCENES } from '../world/scenes';
import { PortalWindow, Stage } from '../world/Stage';
import { AppNav, ConfirmButton, coverOf, reveal } from './shared';
import { waitingOn } from './Dashboard';
import { memberRows } from './RoomUpload';
import './room.css';
import { REAL_MODE } from '../config';
import * as backend from '../real/rooms';
import VrBuildPanel from '../real/VrBuildPanel';

export default function RoomPage() {
  const { id } = useParams();
  const room = useRooms((s) => s.rooms.find((r) => r.id === id));
  const synced = useRooms((s) => s.synced);
  if (!room) return synced ? <Navigate to="/rooms" replace /> : null;
  if (room.phase === 'collecting' && mine(room)?.status !== 'done') return <Navigate to={`/rooms/${room.id}/add`} replace />;
  const ready = room.phase === 'ready';
  return (
    <AnimatePresence mode="wait">
      <motion.div key={ready ? 'ready' : 'waiting'} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.4 }}>
        {ready ? <Ready room={room} /> : <Waiting room={room} />}
      </motion.div>
    </AnimatePresence>
  );
}

/** Steps 3 of 3: who's still missing, then the room resolving out of fog in place. */
function Waiting({ room }: { room: Room }) {
  const navigate = useNavigate();
  const act = useRooms.getState();
  const building = room.phase === 'building';
  const done = room.members.filter((m) => m.status === 'done').length;
  const others = pending(room).filter((m) => m.id !== ME.id);
  const who = waitingOn(room);

  // Once building starts, it runs on its own (no button, no keypress) until it hits ready.
  useEffect(() => {
    if (!building || REAL_MODE) return; // real mode: progress comes from the backend sync
    let raf = 0, last = performance.now();
    const loop = (t: number) => {
      const dt = t - last; last = t;
      useRooms.getState().step(t, dt);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [building, room.id]);

  // A small toast whenever someone's status flips to done, so an arrival reads as an event.
  const [toast, setToast] = useState<{ id: string; text: string } | null>(null);
  const prevStatus = useRef<Record<string, string>>({});
  useEffect(() => {
    const prev = prevStatus.current;
    for (const m of room.members) {
      if (m.status === 'done' && prev[m.id] && prev[m.id] !== 'done') {
        setToast({ id: m.id + '-' + Date.now(), text: `${m.name} added ${m.count || 0} photo${m.count === 1 ? '' : 's'}` });
      }
    }
    prevStatus.current = Object.fromEntries(room.members.map((m) => [m.id, m.status]));
  }, [room.members]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  return (
    <div className="app-shell">
      <Stage scene={room.scene} blur={building ? 0 : 0.5} mist={building ? Math.max(0, 1 - room.progress * 1.1) : 0} scrim="none" className="app-backdrop" label={room.title} />
      <div className="app-card-page">
        <div className="rt-hero-top app-hero-top"><AppNav /></div>
        <AnimatePresence>
          {toast && (
            <motion.div key={toast.id} className="rt-glass room-toast" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.3 }}>
              <span className="caption">{toast.text}</span>
            </motion.div>
          )}
        </AnimatePresence>
        <AnimatePresence mode="wait">
          {building ? (
            <motion.div key="build" className="rt-glass-strong app-panel app-panel-wide" {...reveal(0)} exit={{ opacity: 0, filter: 'blur(12px)' }}>
              <Stepper current={2} />
              <DevelopProgress src={coverOf(room)} title={room.title} progress={room.progress} photo={!!room.cover}
                actions={<><Button variant="ghost" icon="back" onClick={() => navigate('/rooms')}>Back to rooms</Button>
                  {REAL_MODE && <Button variant="ghost" onClick={() => navigate(`/rooms/${room.id}/studio`)}>See each object</Button>}</>} />
            </motion.div>
          ) : (
            <motion.div key="wait" className="rt-glass-strong app-panel app-panel-wide" {...reveal(0)} exit={{ opacity: 0, filter: 'blur(12px)' }}>
              <Stepper current={2} />
              <h1 className="display-m" style={{ margin: 0 }}>Waiting for {who}</h1>
              <p className="app-italic">the room fills in as each view arrives</p>
              <p className="body" style={{ margin: 0, color: 'var(--ink-muted)' }}>
                {done} of {room.members.length} have added their photos. We start building the moment everyone is in{REAL_MODE ? '.' : ', and email you when the room is ready.'}
              </p>
              <div className="rt-bar app-sun-bar" role="progressbar" aria-valuemin={0} aria-valuemax={room.members.length} aria-valuenow={done} aria-label="People who have added photos">
                <i style={{ width: (done / room.members.length) * 100 + '%' }} />
              </div>
              <MemberList members={memberRows(room)} onResend={REAL_MODE ? undefined : (m) => { const x = room.members.find((y) => y.email === m.email); if (x) act.resend(room.id, x.id); }} />
              <div className="app-actions">
                <Button variant="text" icon="back" onClick={() => navigate('/rooms')}>Back to rooms</Button>
                {mine(room)?.isOwner && others.length > 0 && (
                  <ConfirmButton arrow confirmText={`Build with ${done} ${done === 1 ? 'person' : 'people'}'s photos?`} onConfirm={() => (REAL_MODE ? backend.startBuilding : act.startBuilding)(room.id)}>
                    Start without {who}
                  </ConfirmButton>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

/** Built and waiting in everyone's headset. Viewing is VR only; the portal is a glimpse. */
function Ready({ room }: { room: Room }) {
  const navigate = useNavigate();
  const [entering, setEntering] = useState(false);
  const photos = room.members.reduce((n, m) => n + (m.count || 0), 0);
  const peekTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(peekTimer.current), []);
  const peek = () => { setEntering(true); clearTimeout(peekTimer.current); peekTimer.current = setTimeout(() => setEntering(false), 2600); };

  return (
    <div className="app-shell">
      <Stage scene={room.scene} blur={0.7} petals scrim="bottom" className="app-full rt-hero-bottom-left" label={room.title}>
        <div className="rt-hero-top app-hero-top"><AppNav /></div>
        <div className="app-ready">
          <div className="rt-hero-body rt-on-image app-ready-copy">
            <motion.div {...reveal(0)}><Eyebrow badge="Ready">Built from {photos} photos by {room.members.length} {room.members.length === 1 ? 'person' : 'people'}</Eyebrow></motion.div>
            <motion.h1 className="rt-hero-title" {...reveal(1)}><span className="app-ready-name">{room.title}</span><span className="app-ready-is">is ready</span></motion.h1>
            <motion.p className="app-italic" {...reveal(2)}>waiting in your headset</motion.p>
            <motion.p className="rt-hero-sub" {...reveal(3)}>It's waiting in your headset now. Everyone who added photos can step in, together or on their own.</motion.p>
            <motion.div {...reveal(4)}><PresenceStack people={room.members.map((m) => ({ name: m.name }))} size="lg" onImage /></motion.div>
            <motion.div className="rt-hero-actions" {...reveal(5)}><Button variant="light" size="lg" icon="back" onClick={() => navigate('/rooms')}>Back to rooms</Button>
              {REAL_MODE && <Button variant="glass" size="lg" onClick={() => navigate(`/rooms/${room.id}/studio`)}>Objects and letters</Button>}</motion.div>
          </div>
          <div className="app-ready-side">
            <motion.div className="app-portal-wrap" {...reveal(2)}>
              <PortalWindow src={coverOf(room)} depth={room.cover ? undefined : SCENES[room.scene].depth} entering={entering} onClick={peek} label={`Look into ${room.title}`} />
              <p className="app-portal-hint rt-on-image"><Icon name="headset" size={18} />Put on your headset to step inside</p>
            </motion.div>
            <motion.div className="rt-glass-strong app-panel app-headset vr-host" {...reveal(4)}>
              <VrBuildPanel projectId={room.id} title={room.title} />
            </motion.div>
          </div>
        </div>
      </Stage>
    </div>
  );
}
