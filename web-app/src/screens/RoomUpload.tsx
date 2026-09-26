import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { Button, Field, InviteSearch, MemberList, PhotoDrop, Stepper, type Photo } from '../ui';
import { ME, mine, parseObjects, useRooms, agoText, type Room } from '../data/store';
import { searchPeople } from '../data/directory';
import { Stage } from '../world/Stage';
import { AppNav, reveal, shrink } from './shared';

export const memberRows = (r: Room) => r.members.map((m) => ({
  name: m.name, email: m.email, count: m.count, hasNote: !!m.note, isOwner: m.isOwner, isYou: m.id === ME.id,
  status: m.status, sentAgo: agoText(m.invitedAt),
}));

export default function RoomUpload() {
  const { id } = useParams();
  const navigate = useNavigate();
  const room = useRooms((s) => s.rooms.find((r) => r.id === id));
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [note, setNote] = useState('');
  const [objects, setObjects] = useState(room?.objects?.join(', ') || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [q, setQ] = useState('');
  const submitTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => { if (room && mine(room)?.status === 'invited') useRooms.getState().join(room.id); }, [room]);
  useEffect(() => () => clearTimeout(submitTimer.current), []);

  if (!room) return <Navigate to="/rooms" replace />;
  if (mine(room)?.status === 'done' || room.phase !== 'collecting') return <Navigate to={`/rooms/${room.id}`} replace />;

  const add = async (files: File[]) => {
    setError('');
    try {
      const next = await Promise.all(files.map(async (f) => ({ src: await shrink(f), name: f.name, id: Math.random().toString(36).slice(2) })));
      setPhotos((p) => [...p, ...next].slice(0, 12));
    } catch { setError("We couldn't read one of those photos. Try a JPEG or PNG."); }
  };
  const submit = () => {
    if (!photos.length) return setError('Add at least one photo of the place first.');
    setBusy(true);
    // A beat for the upload to feel real, then on to waiting.
    submitTimer.current = setTimeout(() => { useRooms.getState().addPhotos(room.id, photos.map((p) => p.src), note, mine(room)?.isOwner ? parseObjects(objects) : undefined); navigate(`/rooms/${room.id}`); }, 900);
  };

  return (
    <div className="app-shell">
      <div className="app-nav-row"><AppNav plain /></div>
      <div className="app-split">
        <div className="app-form">
          <motion.p className="caption app-crumb" {...reveal(0)}>
            <a href="/rooms" onClick={(e) => { e.preventDefault(); navigate('/rooms'); }}>Rooms</a> / {room.title}
          </motion.p>
          <motion.div {...reveal(0)}><Stepper current={1} /></motion.div>
          <motion.h1 className="display-l" style={{ margin: 0 }} {...reveal(1)}>Add your <em>view</em> of it</motion.h1>
          <motion.div {...reveal(2)}><PhotoDrop photos={photos} onFiles={add} onRemove={(i) => setPhotos((p) => p.filter((_, j) => j !== i))} error={error} /></motion.div>
          <AnimatePresence>
            {mine(room)?.isOwner && photos.length > 0 && (
              <motion.div style={{ overflow: 'hidden' }} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }} layout>
                <Field label="What should we rebuild? (optional)" placeholder="Everything" value={objects} maxLength={400}
                  hint="Leave blank and we rebuild everything in your photos. For a wide shot, list the things you care about, like: the porch swing, the blue vase."
                  onChange={(e) => setObjects(e.target.value)} />
              </motion.div>
            )}
          </AnimatePresence>
          <motion.div {...reveal(3)}>
            <Field multiline rows={3} label="Leave a note for this room" placeholder="What do you remember about being here?" value={note}
              maxLength={1000} onChange={(e) => setNote(e.target.value)} />
          </motion.div>
          <motion.div className="app-actions app-actions-start" {...reveal(4)}>
            <Button variant="primary" size="lg" arrow loading={busy} onClick={submit}>{busy ? 'Adding' : 'Add to the room'}</Button>
            <Button variant="ghost" size="lg" disabled={busy} onClick={() => navigate('/rooms')}>Save for later</Button>
          </motion.div>
        </div>
        <Stage scene={room.scene} scrim="none" className="app-side-stage" label={room.title} mist={photos.length ? 0 : 0.35}>
          <motion.div className="rt-glass-strong app-panel" {...reveal(2)}>
            <h2 className="title" style={{ margin: 0 }}>In this <em>room</em></h2>
            <MemberList members={memberRows(room)} onResend={(m) => { const x = room.members.find((y) => y.email === m.email); if (x) useRooms.getState().resend(room.id, x.id); }} />
            <InviteSearch label="Invite someone else" results={searchPeople(q)} invited={room.members.map((m) => ({ name: m.name, email: m.email }))}
              onQuery={setQ} onInvite={(p) => useRooms.getState().invite(room.id, p.email)} />
          </motion.div>
        </Stage>
      </div>
    </div>
  );
}
