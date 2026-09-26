import { useState } from 'react';
import { motion } from 'motion/react';
import { useNavigate } from 'react-router-dom';
import { Button, Field, InviteSearch, Stepper, type Invitee } from '../ui';
import { useRooms } from '../data/store';
import { searchPeople, sceneFor } from '../data/directory';
import { Stage } from '../world/Stage';
import { AppNav, reveal } from './shared';
import { REAL_MODE } from '../config';
import * as backend from '../real/rooms';
import { ApiError } from '../api/client';
import './form.css';

export default function CreateRoom() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [q, setQ] = useState('');
  const [invited, setInvited] = useState<Invitee[]>([]);
  const [busy, setBusy] = useState(false);
  const results = searchPeople(q);
  const scene = sceneFor(name) ?? 'home';

  const create = async (withInvites: boolean) => {
    if (!name.trim()) return setError('Give the room a name, like the place or the day.');
    if (REAL_MODE) {
      setBusy(true);
      try { navigate(`/rooms/${await backend.createRoom(name)}/add`); }
      catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't reach return. Try again."); }
      finally { setBusy(false); }
      return;
    }
    const id = useRooms.getState().createRoom(name, withInvites ? invited.map((p) => p.email) : [], scene);
    navigate(`/rooms/${id}/add`);
  };

  return (
    <div className="app-shell">
      <Stage scene={scene} blur={0.6} scrim="none" className="app-full app-center" label="Start a new room">
        <div className="rt-hero-top app-hero-top"><AppNav /></div>
        <motion.div className="rt-glass-strong app-panel app-card" {...reveal(0)}>
          <form onSubmit={(e) => { e.preventDefault(); void create(true); }}>
            <Stepper current={0} />
            <h1 className="display-l" style={{ margin: 0 }}>Start a new room</h1>
            <p className="app-italic">one place, one moment, everyone who was there</p>
            <Field label="Name this room" placeholder="The lake house, summer 2019" value={name} error={error} autoFocus
              hint="Shown on the room's card and in the headset." onChange={(e) => { setName(e.target.value); setError(''); }} />
            {REAL_MODE ? (
              <p className="rt-field-hint" style={{ margin: 0 }}>The other account on this laptop gets an invitation as soon as the room exists.</p>
            ) : (
              <InviteSearch results={results} invited={invited} onQuery={setQ}
                onInvite={(p) => setInvited((v) => (v.some((x) => x.email === p.email) ? v : [...v, p]))}
                onRemove={(p) => setInvited((v) => v.filter((x) => x.email !== p.email))} />
            )}
            <p className="rt-field-hint" style={{ margin: 0 }}>
              Each person remembers the place from a different spot. {invited.length > 0 ? (
                <>With <motion.span key={invited.length} style={{ display: 'inline-block' }} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}>{invited.length + 1}</motion.span> of you, return can rebuild more of the room.</>
              ) : 'More angles let return rebuild more of the room.'}
            </p>
            <div className="app-actions app-actions-start">
              <Button variant="primary" size="lg" arrow type="submit" loading={busy}>Next: add your photos</Button>
              {invited.length === 0 && !REAL_MODE && <Button variant="ghost" size="lg" onClick={() => void create(false)}>Invite people later</Button>}
              <Button variant="ghost" icon="x" onClick={() => navigate('/rooms')}>Cancel</Button>
            </div>
          </form>
        </motion.div>
      </Stage>
    </div>
  );
}
