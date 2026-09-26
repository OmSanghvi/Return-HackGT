import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { Button, Field, InviteSearch, MemberList, PhotoDrop, PresenceStack, Stepper, type Photo } from '../ui';
import { ME, mine, parseObjects, useRooms, agoText, type Room } from '../data/store';
import { searchPeople } from '../data/directory';
import { Stage } from '../world/Stage';
import { AppNav, Sheet, reveal, shrink } from './shared';
import { REAL_MODE } from '../config';
import * as backend from '../real/rooms';
import { ApiError } from '../api/client';
import './form.css';

export const memberRows = (r: Room) => r.members.map((m) => ({
  name: m.name, email: m.email, count: m.count, hasNote: !!m.note, isOwner: m.isOwner, isYou: m.id === ME.id,
  status: m.status, sentAgo: agoText(m.invitedAt),
}));

export default function RoomUpload() {
  const { id } = useParams();
  const navigate = useNavigate();
  const room = useRooms((s) => s.rooms.find((r) => r.id === id));
  const synced = useRooms((s) => s.synced);
  const files = useRef(new Map<string, File>()); // real mode uploads the originals, not the previews
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [note, setNote] = useState('');
  const [objects, setObjects] = useState(room?.objects?.join(', ') || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [q, setQ] = useState('');
  const [people, setPeople] = useState(false);
  const submitTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const invited = room && mine(room)?.status === 'invited';
  useEffect(() => { if (room && invited) void (REAL_MODE ? backend.join(room.id) : useRooms.getState().join(room.id)); }, [room?.id, invited]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => clearTimeout(submitTimer.current), []);

  if (!room) return synced ? <Navigate to="/rooms" replace /> : null;
  if (mine(room)?.status === 'done' || room.phase !== 'collecting') return <Navigate to={`/rooms/${room.id}`} replace />;

  const add = async (picked: File[]) => {
    setError('');
    try {
      const next = await Promise.all(picked.map(async (f) => {
        const id = Math.random().toString(36).slice(2);
        files.current.set(id, f);
        return { src: await shrink(f), name: f.name, id };
      }));
      setPhotos((p) => [...p, ...next].slice(0, 12));
    } catch { setError("We couldn't read one of those photos. Try a JPEG or PNG."); }
  };
  const submit = () => {
    if (!photos.length) return setError('Add at least one photo of the place first.');
    setBusy(true);
    const objectList = mine(room)?.isOwner ? parseObjects(objects) : undefined;
    if (REAL_MODE) {
      backend.addPhotos(room.id, photos.map((p) => files.current.get(p.id!)!), note, objectList)
        .then(() => navigate(`/rooms/${room.id}`))
        .catch((e) => { setBusy(false); setError(e instanceof ApiError ? e.message : "Couldn't upload those photos. Try again."); });
      return;
    }
    // A beat for the upload to feel real, then on to waiting.
    submitTimer.current = setTimeout(() => { useRooms.getState().addPhotos(room.id, photos.map((p) => p.src), note, objectList); navigate(`/rooms/${room.id}`); }, 900);
  };

  return (
    <div className="app-shell">
      <Stage scene={room.scene} blur={0.6} scrim="none" className="app-full app-center" label={room.title}>
        <div className="rt-hero-top app-hero-top"><AppNav /></div>
        <motion.div className="rt-glass-strong app-panel app-card" {...reveal(0)}>
          <div className="app-card-head">
            <div>
              <p className="caption app-crumb">
                <a href="/rooms" onClick={(e) => { e.preventDefault(); navigate('/rooms'); }}>Rooms</a> / {room.title}
              </p>
              <Stepper current={1} />
              <h1 className="display-l" style={{ margin: 0 }}>Add your view of it</h1>
              <p className="app-italic">the way you remember it</p>
            </div>
            <div className="app-card-people">
              <PresenceStack people={room.members.map((m) => ({ name: m.name }))} size="sm" />
              <Button variant="ghost" size="sm" icon="people" onClick={() => setPeople(true)}>People</Button>
            </div>
          </div>
          <div className="app-card-body">
            <PhotoDrop photos={photos} onFiles={add} onRemove={(i) => setPhotos((p) => p.filter((_, j) => j !== i))} error={error} />
            <div>
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
              <Field multiline rows={3} label="Leave a note for this room" placeholder="What do you remember about being here?" value={note}
                maxLength={1000} onChange={(e) => setNote(e.target.value)} />
            </div>
          </div>
          <div className="app-actions app-actions-start">
            <Button variant="primary" size="lg" arrow loading={busy} onClick={submit}>{busy ? 'Adding' : 'Add to the room'}</Button>
            <Button variant="ghost" size="lg" disabled={busy} onClick={() => navigate('/rooms')}>Save for later</Button>
          </div>
        </motion.div>
      </Stage>
      <Sheet open={people} onClose={() => setPeople(false)} label={'People in ' + room.title}>
        <h2 className="title" style={{ margin: 0 }}>In this room</h2>
        <MemberList members={memberRows(room)} onResend={REAL_MODE ? undefined : (m) => { const x = room.members.find((y) => y.email === m.email); if (x) useRooms.getState().resend(room.id, x.id); }} />
        {REAL_MODE ? <p className="rt-field-hint" style={{ margin: 0 }}>Switch accounts from your avatar to add the other person's photos.</p> : <InviteSearch label="Invite someone else" results={searchPeople(q)} invited={room.members.map((m) => ({ name: m.name, email: m.email }))}
          onQuery={setQ} onInvite={(p) => useRooms.getState().invite(room.id, p.email)} />}
      </Sheet>
    </div>
  );
}
