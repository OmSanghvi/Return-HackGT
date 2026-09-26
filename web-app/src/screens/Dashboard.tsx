import { useCallback, useEffect, useRef, useState } from 'react';
import type * as React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useNavigate } from 'react-router-dom';
import { Button, Field, Icon, RoomCard, ShareSheet, type RoomStatus } from '../ui';
import { useSession } from '../auth';
import { ME, mine, pending, routeForRoom, useRooms, type Room } from '../data/store';
import { searchPeople } from '../data/directory';
import { Stage } from '../world/Stage';
import type { SceneKey } from '../world/scenes';
import { useWorld } from '../world/state';
import { AppNav, coverOf, reveal, Sheet, useStepIn } from './shared';
import './dashboard.css';

export const waitingOn = (r: Room) => {
  const p = pending(r).filter((m) => m.id !== ME.id);
  return p.length === 1 ? p[0].name.split(' ')[0] : `${p.length} people`;
};

function cardInfo(r: Room): { status?: RoomStatus; statusText?: string; meta: string; progress?: number } {
  const done = r.members.filter((m) => m.status === 'done').length;
  if (mine(r)?.status === 'invited') return { status: 'invited', meta: `${r.invitedBy || 'Someone'} invited you` };
  if (r.phase === 'collecting' && mine(r)?.status !== 'done') return { status: 'new', statusText: 'Add your photos', meta: `${done} of ${r.members.length} added photos` };
  if (r.phase === 'collecting') return { status: 'waiting', statusText: `Waiting for ${waitingOn(r)}`, meta: `${done} of ${r.members.length} added photos` };
  if (r.phase === 'building') return { status: 'developing', statusText: `Building · ${Math.round(r.progress * 100)}%`, progress: r.progress, meta: `${r.members.reduce((n, m) => n + (m.count || 0), 0)} photos` };
  return { meta: [r.place, r.date].filter(Boolean).join(' · ') || `${r.members.length} people` };
}

function summary(rooms: Room[], invites: Room[]) {
  const needsPhotos = rooms.find((r) => r.phase === 'collecting' && mine(r)?.status !== 'done');
  const waiting = rooms.find((r) => r.phase === 'collecting' && mine(r)?.status === 'done');
  const building = rooms.find((r) => r.phase === 'building');
  const note = needsPhotos ? `Add your photos to ${needsPhotos.title}`
    : waiting ? `${waitingOn(waiting)} still ${pending(waiting).length > 1 ? 'need' : 'needs'} to add photos to ${waiting.title}`
    : building ? `${building.title} is coming into focus` : 'Everything is ready to return to';
  const invitePart = invites.length ? ` · ${invites.length} invitation${invites.length === 1 ? '' : 's'}` : '';
  return `${rooms.length} room${rooms.length === 1 ? '' : 's'}${invitePart} · ${note}`;
}

/** A card that leans toward the pointer, a few degrees at most.
 * Hovering a moment flies the sky to this card's scene; leaving flies it back. */
function Tilt({ children, i, scene }: { children: React.ReactNode; i: number; scene?: SceneKey }) {
  const lean = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    e.currentTarget.style.setProperty('--tx', ((e.clientX - r.left) / r.width - 0.5).toFixed(3));
    e.currentTarget.style.setProperty('--ty', ((e.clientY - r.top) / r.height - 0.5).toFixed(3));
  };
  const rest = (e: React.PointerEvent<HTMLDivElement>) => { e.currentTarget.style.setProperty('--tx', '0'); e.currentTarget.style.setProperty('--ty', '0'); };
  const took = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => { clearTimeout(timer.current); if (took.current) useWorld.setState({ scene: 'painted', fast: true }); }, []);
  const enter = () => {
    if (!scene) return;
    timer.current = window.setTimeout(() => { useWorld.setState({ scene, fast: true }); took.current = true; }, 150);
  };
  const leave = (e: React.PointerEvent<HTMLDivElement>) => {
    rest(e);
    clearTimeout(timer.current);
    if (took.current) { useWorld.setState({ scene: 'painted', fast: true }); took.current = false; }
  };
  return (
    <motion.div className="app-tilt-wrap" layout {...reveal(i)} exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.22, ease: [0.16, 1, 0.3, 1] } }}>
      <div className="app-tilt" onPointerMove={lean} onPointerEnter={enter} onPointerLeave={leave}>{children}</div>
    </motion.div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const stepIn = useStepIn();
  const session = useSession();
  const rooms = useRooms((s) => s.rooms);
  const act = useRooms.getState();
  const [menu, setMenu] = useState<string | null>(null);
  const [sheet, setSheet] = useState<{ kind: 'rename' | 'people' | 'remove'; id: string } | null>(null);
  const [pq, setPq] = useState('');
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const invites = rooms.filter((r) => mine(r)?.status === 'invited');
  const yours = rooms.filter((r) => mine(r)?.status !== 'invited');
  const target = rooms.find((r) => r.id === sheet?.id);
  const people = (target?.members || []).map((m) => ({ name: m.name + (m.id === ME.id ? ' (you)' : ''), email: m.email, role: m.isOwner ? 'owner' as const : 'add' as const,
    note: m.status === 'done' ? `Added ${m.count} photos` : m.status === 'joined' ? 'Joined' : 'Invited' }));

  const open = (r: Room, e: React.MouseEvent) => (r.phase === 'ready' ? stepIn(e, `/rooms/${r.id}`) : navigate(routeForRoom(r)));
  const closeSheet = useCallback(() => setSheet(null), []);

  useEffect(() => {
    if (!menu) return;
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setMenu(null);
    addEventListener('keydown', key);
    return () => removeEventListener('keydown', key);
  }, [menu]);
  useEffect(() => {
    if (menu) menuRef.current?.querySelector<HTMLElement>('button')?.focus();
    else triggerRef.current?.focus();
  }, [menu]);

  return (
    <div className="app-shell" onClick={() => setMenu(null)}>
      <div className="app-nav-row"><AppNav plain active="rooms" /></div>
      <Stage scene="painted" scrim="bottom" className="rt-hero-bottom-left app-header" label="Your rooms">
        <div className="rt-hero-body rt-on-image">
          <motion.p className="rt-kicker" style={{ margin: 0 }} {...reveal(0)}>Welcome back, {session.firstName}</motion.p>
          <motion.h1 className="rt-hero-title" {...reveal(1)}>Your <em>rooms</em></motion.h1>
          <motion.p className="rt-hero-sub" {...reveal(2)}>{summary(yours, invites)}</motion.p>
        </div>
      </Stage>

      {invites.length > 0 && (
        <section className="app-section">
          <motion.h2 className="vr-h1 app-h2" {...reveal(0)}>Invitations</motion.h2>
          <div className="app-grid">
            <AnimatePresence>
              {invites.map((r, i) => (
                <Tilt key={r.id} i={i} scene={r.scene}>
                  <RoomCard src={coverOf(r)} title={r.title} {...cardInfo(r)} onOpen={() => navigate(routeForRoom(r))}
                    action={<><Button size="sm" variant="light" onClick={() => { act.join(r.id); navigate(`/rooms/${r.id}/add`); }}>Join room</Button>
                      <Button size="sm" variant="glass" onClick={() => act.decline(r.id)}>Decline</Button></>} />
                </Tilt>
              ))}
            </AnimatePresence>
          </div>
        </section>
      )}

      <section className="app-section" aria-label="Your rooms">
        {/* The hero already says "Your rooms"; only label this grid when Invitations sits above it. */}
        {invites.length > 0 && <motion.h2 className="vr-h1 app-h2" {...reveal(0)}>Your rooms</motion.h2>}
        <div className="app-grid">
            <AnimatePresence>
              {yours.map((r, i) => {
                const owner = mine(r)?.isOwner;
                return (
                  <Tilt key={r.id} i={i + 1} scene={r.scene}>
                    <RoomCard src={coverOf(r)} title={r.title} {...cardInfo(r)} people={r.members.map((m) => ({ name: m.name }))} onOpen={(e) => open(r, e)}
                      onManage={(e) => { e.stopPropagation(); triggerRef.current = e.currentTarget as HTMLButtonElement; setMenu(menu === r.id ? null : r.id); }} />
                    <AnimatePresence>
                      {menu === r.id && (
                        <motion.div ref={menuRef} className="app-menu rt-glass-strong" role="menu" onClick={(e) => e.stopPropagation()}
                          style={{ transformOrigin: 'top right' }} initial={{ opacity: 0, scale: 0.96, y: -4 }} animate={{ opacity: 1, scale: 1, y: 0 }}
                          exit={{ opacity: 0, scale: 0.96 }} transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}>
                          {owner && <button role="menuitem" onClick={() => { setSheet({ kind: 'rename', id: r.id }); setMenu(null); }}>Rename</button>}
                          <button role="menuitem" onClick={() => { setSheet({ kind: 'people', id: r.id }); setMenu(null); }}>Manage people</button>
                          <button role="menuitem" className="app-danger" onClick={() => { setSheet({ kind: 'remove', id: r.id }); setMenu(null); }}>{owner ? 'Delete room' : 'Leave room'}</button>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </Tilt>
                );
              })}
            </AnimatePresence>
            <motion.button type="button" className="app-new-tile" onClick={() => navigate('/rooms/new')} {...reveal(yours.length + 1)}>
              <span className="app-new-dot"><Icon name="plus" size={24} /></span>
              <span className="title">Create a <em>room</em></span>
              <span className="caption" style={{ color: 'var(--ink-muted)' }}>Pick a place, invite the people who were there.</span>
            </motion.button>
        </div>
      </section>

      <Sheet open={sheet?.kind === 'rename' && !!target} onClose={closeSheet} label="Rename room">
        {target && <form onSubmit={(e) => { e.preventDefault(); const v = new FormData(e.currentTarget).get('title') as string; if (v.trim()) act.rename(target.id, v.trim()); setSheet(null); }}>
          <h2 className="title" style={{ margin: '0 0 var(--space-4)' }}>Rename <em>room</em></h2>
          <Field name="title" label="Room name" defaultValue={target.title} />
          <div className="app-actions"><Button variant="ghost" onClick={() => setSheet(null)}>Cancel</Button><Button variant="primary" type="submit">Save</Button></div>
        </form>}
      </Sheet>
      <Sheet open={sheet?.kind === 'people' && !!target} onClose={closeSheet} label="Manage people">
        {target && <ShareSheet title={target.title} onClose={closeSheet} people={people}
          onInvite={(v) => act.invite(target.id, v)} results={searchPeople(pq)} onQuery={setPq}
          onRemove={mine(target)?.isOwner ? (p) => act.uninvite(target.id, target.members[people.indexOf(p as typeof people[number])].id) : undefined} />}
      </Sheet>
      <Sheet open={sheet?.kind === 'remove' && !!target} onClose={closeSheet} label="Remove room">
        {target && <>
          <h2 className="title" style={{ margin: 0 }}>{mine(target)?.isOwner ? 'Delete' : 'Leave'} <em>{target.title}</em></h2>
          <p className="body" style={{ color: 'var(--ink-muted)' }}>{mine(target)?.isOwner ? 'This removes the room for everyone in it, and it disappears from their headsets.' : "You won't see this room anymore. The others keep it."}</p>
          <div className="app-actions"><Button variant="ghost" onClick={() => setSheet(null)}>Keep it</Button>
            <Button variant="danger" onClick={() => { act.remove(target.id); setSheet(null); }}>{mine(target)?.isOwner ? 'Delete room' : 'Leave room'}</Button></div>
        </>}
      </Sheet>
    </div>
  );
}
