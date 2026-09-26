import { useState } from 'react';
import { motion } from 'motion/react';
import { useNavigate } from 'react-router-dom';
import { Button, Field, InviteSearch, Stepper, type Invitee } from '../ui';
import { useRooms } from '../data/store';
import { searchPeople, sceneFor } from '../data/directory';
import { Stage } from '../world/Stage';
import { Logo, reveal } from './shared';

export default function CreateRoom() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [q, setQ] = useState('');
  const [invited, setInvited] = useState<Invitee[]>([]);
  const results = searchPeople(q);
  const scene = sceneFor(name) ?? 'home';

  const create = (withInvites: boolean) => {
    if (!name.trim()) return setError('Give the room a name, like the place or the day.');
    const id = useRooms.getState().createRoom(name, withInvites ? invited.map((p) => p.email) : [], scene);
    navigate(`/rooms/${id}/add`);
  };

  return (
    <div className="app-shell">
      <div className="app-bar">
        <a href="/" onClick={(e) => { e.preventDefault(); navigate('/rooms'); }} aria-label="return, back to rooms"><Logo /></a>
        <Button variant="ghost" icon="x" onClick={() => navigate('/rooms')}>Cancel</Button>
      </div>
      <div className="app-split">
        <form className="app-form" onSubmit={(e) => { e.preventDefault(); create(true); }}>
          <motion.div {...reveal(0)}><Stepper current={0} /></motion.div>
          <motion.h1 className="display-l" style={{ margin: 0 }} {...reveal(1)}>Start a new <em>room</em></motion.h1>
          <motion.p className="body-l" style={{ margin: 0, color: 'var(--ink-muted)' }} {...reveal(2)}>One place, one moment. Everyone you invite adds their own photos of it.</motion.p>
          <motion.div {...reveal(3)}>
            <Field label="Name this room" placeholder="The lake house, summer 2019" value={name} error={error} autoFocus
              hint="Shown on the room's card and in the headset." onChange={(e) => { setName(e.target.value); setError(''); }} />
          </motion.div>
          <motion.div {...reveal(4)}>
            <InviteSearch results={results} invited={invited} onQuery={setQ}
              onInvite={(p) => setInvited((v) => (v.some((x) => x.email === p.email) ? v : [...v, p]))}
              onRemove={(p) => setInvited((v) => v.filter((x) => x.email !== p.email))} />
          </motion.div>
          <motion.div className="app-actions app-actions-start" {...reveal(5)}>
            <Button variant="primary" size="lg" arrow type="submit">Next: add your photos</Button>
            {invited.length === 0 && <Button variant="ghost" size="lg" onClick={() => create(false)}>Invite people later</Button>}
          </motion.div>
        </form>
        <Stage scene={scene} fast scrim="bottom" className="app-side-stage" label="Better together">
          <motion.div className="rt-glass app-note" {...reveal(3)}>
            <p className="title" style={{ margin: '0 0 6px' }}>Better <em>together</em></p>
            <p style={{ margin: 0, fontSize: 14, lineHeight: '20px' }}>
              Each person remembers the place from a different spot. {invited.length > 0 ? (
                <>With <motion.span key={invited.length} style={{ display: 'inline-block' }} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}>{invited.length + 1}</motion.span> of you, return can rebuild more of the room.</>
              ) : 'More angles let return rebuild more of the room.'}
            </p>
          </motion.div>
        </Stage>
      </div>
    </div>
  );
}
