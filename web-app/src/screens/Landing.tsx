import { useEffect, useRef, useState } from 'react';
import type * as React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useNavigate } from 'react-router-dom';
import { Button, Eyebrow, GlassNav, PresenceStack, RoomCard } from '../ui';
import { useSession } from '../auth';
import { Stage } from '../world/Stage';
import { SCENES, type SceneKey } from '../world/scenes';
import { useWorld } from '../world/state';
import { Logo, reveal } from './shared';
import './landing.css';

// One sticky painted window; scrolling flies the camera through four paintings.
const CHAPTERS: { scene: SceneKey; title?: [string, string, string?]; body: string }[] = [
  { scene: 'meadow', body: 'Start a room, invite the people who were there, and everyone adds their photos. return rebuilds the place as a world you can stand inside together.' },
  { scene: 'painted', title: ['Start a ', 'room', ''], body: 'Name the place and the moment. Invite the people who were there by email.' },
  { scene: 'beach', title: ['Everyone adds their ', 'view', ''], body: 'Each person brings their own photos and a note. More angles build a fuller world.' },
  { scene: 'cloudsea', title: ['Step inside ', 'together', ''], body: 'When everyone is in, the room appears in each headset, and you are back.' },
];

/** The chapter-specific artwork shown to the right of the text, chapters 1 to 3. */
function ChapterVisual({ chapter }: { chapter: number }) {
  if (chapter === 1) {
    return (
      <div className="rt-hero-visual" style={{ pointerEvents: 'none' }} aria-hidden>
        <RoomCard src={SCENES.home.image} title="Grandma's porch" status="waiting" statusText="Waiting for Sam" meta="2 of 3 added photos"
          people={[{ name: 'Alice' }, { name: 'Sam' }, { name: 'Jo' }]} />
      </div>
    );
  }
  if (chapter === 2) {
    return (
      <div className="rt-hero-visual rt-landing-fan" aria-hidden>
        <span className="rt-landing-photo" style={{ backgroundImage: `url(${SCENES.beach.image})`, '--r': '-8deg', '--rh': '-14deg' } as React.CSSProperties} />
        <span className="rt-landing-photo" style={{ backgroundImage: `url(${SCENES.meadow.image})`, '--r': '0deg', '--rh': '0deg' } as React.CSSProperties} />
        <span className="rt-landing-photo" style={{ backgroundImage: `url(${SCENES.plain.image})`, '--r': '8deg', '--rh': '14deg' } as React.CSSProperties} />
      </div>
    );
  }
  if (chapter === 3) {
    return (
      <div className="rt-hero-visual" style={{ pointerEvents: 'none' }}>
        <PresenceStack people={[{ name: 'Alice', here: true }, { name: 'Sam', here: true }, { name: 'Jo', here: true }]} size="lg" showLabel onImage />
      </div>
    );
  }
  return null;
}

export default function Landing() {
  const navigate = useNavigate();
  const { signedIn } = useSession();
  const track = useRef<HTMLDivElement>(null);
  const [chapter, setChapter] = useState(0);
  // Layout (centered intro vs bottom-left chapters) follows the text on screen, not the scroll position,
  // so outgoing text finishes fading where it was instead of jumping to the next chapter's layout.
  const [shown, setShown] = useState(0);
  const latest = useRef(chapter); latest.current = chapter;

  const toChapter = (i: number) => {
    const el = track.current; if (!el) return;
    scrollTo({ top: el.offsetTop + ((el.offsetHeight - innerHeight) * (i + 0.2)) / CHAPTERS.length, behavior: 'smooth' });
  };

  useEffect(() => {
    const onScroll = () => {
      const el = track.current; if (!el) return;
      const r = el.getBoundingClientRect(), span = r.height - innerHeight;
      const p = Math.max(0, Math.min(0.999, -r.top / span)) * CHAPTERS.length;
      const next = Math.floor(p);
      setChapter((c) => (c === next ? c : next));
      useWorld.setState({ zoom: Math.round((p % 1) * 40) / 100 });   // a slow dolly into each painting; skips React entirely
    };
    onScroll();
    addEventListener('scroll', onScroll, { passive: true });
    return () => removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
      if (e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === 'j') { e.preventDefault(); toChapter(Math.min(CHAPTERS.length - 1, latest.current + 1)); }
      else if (e.key === 'ArrowUp' || e.key === 'PageUp' || e.key === 'k') { e.preventDefault(); toChapter(Math.max(0, latest.current - 1)); }
    };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, []);

  const start = () => navigate(signedIn ? '/rooms/new' : '/sign-in?next=/rooms/new');
  const c = CHAPTERS[chapter];

  return (
    <>
      <div ref={track} className="app-landing-track">
        <Stage scene={c.scene} fast scrim={shown ? 'bottom' : 'center'} className={'app-landing-stage ' + (shown ? 'rt-hero-bottom-left' : 'rt-hero-center')} label="return">
          <div className="rt-hero-top">
            <GlassNav brand={<Logo />} items={[{ label: 'How it works', onClick: () => toChapter(1) }, { label: 'Rooms', onClick: () => navigate('/rooms') }]}
              cta={<>{!signedIn && <Button variant="ghost" size="sm" onClick={() => navigate('/sign-in')}>Sign in</Button>}
                <Button variant="primary" size="sm" icon="plus" onClick={start}>Create a room</Button></>} />
          </div>
          <AnimatePresence mode="wait" onExitComplete={() => setShown(latest.current)}>
            <motion.div key={chapter} className={'rt-hero-body rt-on-image' + (chapter !== 0 ? ' rt-hero-split' : '')} exit={{ opacity: 0, y: -8, transition: { duration: 0.45, ease: [0.4, 0, 1, 1] } }}>
              {chapter === 0 ? (
                <>
                  <motion.div {...reveal(0)}><Eyebrow badge="New">Shared rooms are live on Quest 3</Eyebrow></motion.div>
                  <motion.h1 className="rt-hero-title" {...reveal(1)}>Walk back into the <em>moments</em> you miss</motion.h1>
                  <motion.p className="rt-hero-sub" {...reveal(2)}>{c.body}</motion.p>
                  <motion.div className="rt-hero-actions" {...reveal(3)}>
                    <Button variant="light" size="lg" arrow="arrowUpRight" onClick={start}>Start a room</Button>
                    <Button variant="text" icon="arrowRight" onClick={() => toChapter(1)}>See how it works</Button>
                  </motion.div>
                </>
              ) : (
                <>
                  <div className="rt-hero-text">
                    <motion.h2 className="rt-hero-title" {...reveal(1)}>{c.title![0]}<em>{c.title![1]}</em>{c.title![2]}</motion.h2>
                    <motion.p className="rt-hero-sub" {...reveal(2)}>{c.body}</motion.p>
                    {chapter === 3 && <motion.div className="rt-hero-actions" {...reveal(3)}><Button variant="light" size="lg" arrow onClick={start}>Start a room</Button></motion.div>}
                  </div>
                  <motion.div {...reveal(3)}><ChapterVisual chapter={chapter} /></motion.div>
                </>
              )}
            </motion.div>
          </AnimatePresence>
          <div className="rt-hero-foot rt-on-image" style={{ justifyContent: 'center' }}>
            <span className="app-dots" role="tablist" aria-label="Chapters">
              {CHAPTERS.map((_, i) => (
                <button key={i} type="button" role="tab" className={i === chapter ? 'on' : ''} aria-label={'Chapter ' + (i + 1)}
                  aria-current={i === chapter ? 'true' : undefined} aria-selected={i === chapter} onClick={() => toChapter(i)} />
              ))}
            </span>
          </div>
        </Stage>
      </div>
    </>
  );
}
