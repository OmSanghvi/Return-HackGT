import { useEffect, useRef, useState } from 'react';
import type * as React from 'react';
import { create } from 'zustand';
import { AnimatePresence, motion } from 'motion/react';
import { useNavigate } from 'react-router-dom';
import { Button, GlassNav, Icon, initials } from '../ui';
import { useSession } from '../auth';
import { SCENES } from '../world/scenes';
import type { Room } from '../data/store';
import lockupWhite from '../design-system/logos/return-lockup-white.svg';
import lockupInk from '../design-system/logos/return-lockup-ink.svg';
import { DEMO_ACCOUNTS, REAL_MODE } from '../config';
import { accountLabel, useAccount } from '../api/account';
import './pages.css';

export const coverOf = (r: Room) => r.cover || SCENES[r.scene].image;

/** Shared motion feel: same ease and durations everywhere so pages don't disagree on pace. */
export const MOTION = { ease: [0.16, 1, 0.3, 1] as const, fast: 0.16, base: 0.32, reveal: 0.7 };

/** Quick rise, fade in. Staggered by index. A full `transform` string (not `y`) so it runs on the compositor instead of repainting. */
export const reveal = (i = 0) => ({
  initial: { opacity: 0, transform: 'translateY(10px)' },
  animate: { opacity: 1, transform: 'translateY(0px)', transitionEnd: { transform: 'none' } },
  transition: { duration: MOTION.reveal, ease: MOTION.ease, delay: i * 0.1 },
});

/* display:none removes an image from the a11y tree, so both lockups can carry the same alt text;
 * only the one CSS shows for the current theme is ever announced. */
export function Logo({ plain }: { plain?: boolean } = {}) {
  return <>
    <img className="app-logo-white" src={lockupWhite} alt="return" height={26} />
    {plain && <img className="app-logo-ink" src={lockupInk} alt="return" height={26} />}
  </>;
}

/** Avatar plus first name; opens a small menu so signing out is never a surprise. */
function AccountMenu() {
  const navigate = useNavigate();
  const session = useSession();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    const down = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    addEventListener('keydown', key); addEventListener('mousedown', down);
    return () => { removeEventListener('keydown', key); removeEventListener('mousedown', down); };
  }, [open]);
  return (
    <div className="app-account" ref={ref}>
      <button type="button" className="app-account-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="rt-avatar app-me" aria-hidden>{initials(session.name)}</span>
        <span className="app-account-name">{session.name.split(' ')[0]}</span>
      </button>
      {open && (
        <div className="app-account-menu rt-glass-strong" role="menu">
          <p className="caption app-account-who">Signed in as <strong>{session.name}</strong></p>
          <button type="button" role="menuitem" onClick={() => { setOpen(false); navigate('/rooms'); }}><Icon name="home" size={16} />My rooms</button>
          {REAL_MODE && DEMO_ACCOUNTS.filter((id) => accountLabel(id) !== session.name).map((id) => (
            <button key={id} type="button" role="menuitem" onClick={() => { setOpen(false); useAccount.getState().setAccount(id); navigate('/rooms'); }}>
              <Icon name="people" size={16} />Switch to {accountLabel(id)}</button>
          ))}
          <button type="button" role="menuitem" onClick={() => { session.signOut(); navigate('/'); }}><Icon name="enter" size={16} />Sign out</button>
        </div>
      )}
    </div>
  );
}

/** The signed-in app nav: My rooms, Create a room, account menu. */
export function AppNav({ plain, active = 'none' }: { plain?: boolean; active?: 'rooms' | 'none' }) {
  const navigate = useNavigate();
  return (
    <GlassNav plain={plain} brand={<a href="/" onClick={(e) => { e.preventDefault(); navigate('/'); }} aria-label="return home"><Logo plain={plain} /></a>}
      items={[{ label: 'My rooms', active: active === 'rooms', onClick: () => navigate('/rooms') }]}
      cta={<>
        <Button variant="primary" size="sm" icon="plus" onClick={() => navigate('/rooms/new')}>Create a room</Button>
        <AccountMenu />
      </>} />
  );
}

/** Stepping in: a deep blue bloom from a point, then the next view. */
export const useBloom = create<{ at: { x: number; y: number; k: number } | null }>(() => ({ at: null }));
export function useStepIn() {
  const navigate = useNavigate();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  return (e: { clientX: number; clientY: number }, to: string) => {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return navigate(to);
    useBloom.setState({ at: { x: e.clientX, y: e.clientY, k: Date.now() } });
    timer.current = setTimeout(() => navigate(to), 700);
  };
}
export function Bloom() {
  const at = useBloom((s) => s.at);
  useEffect(() => { if (at) { const t = setTimeout(() => useBloom.setState({ at: null }), 2800); return () => clearTimeout(t); } }, [at]);
  return at ? <div key={at.k} className="app-bloom" style={{ '--bx': at.x + 'px', '--by': at.y + 'px', '--br': Math.hypot(Math.max(at.x, innerWidth - at.x), Math.max(at.y, innerHeight - at.y)) + 'px' } as React.CSSProperties} aria-hidden /> : null;
}

/** A floating sheet over a soft backdrop. Escape or backdrop click closes it. */
export function Sheet({ open, onClose, children, label }: { open: boolean; onClose(): void; children: React.ReactNode; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    addEventListener('keydown', key);
    ref.current?.querySelector<HTMLElement>('input, button')?.focus();
    return () => removeEventListener('keydown', key);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="app-sheet-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.28 }}>
          <motion.div ref={ref} className="app-sheet rt-glass-strong" role="dialog" aria-modal aria-label={label}
            initial={{ opacity: 0, transform: 'translateY(12px) scale(0.98)' }} animate={{ opacity: 1, transform: 'translateY(0px) scale(1)' }}
            exit={{ opacity: 0, transform: 'translateY(6px) scale(1)', transition: { duration: 0.2, ease: MOTION.ease } }}
            transition={{ duration: 0.35, ease: MOTION.ease }}>
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Two-step confirm inside a button slot, instead of a browser dialog. */
export function ConfirmButton({ children, confirmText, onConfirm, variant = 'secondary', arrow }: { children: React.ReactNode; confirmText: string; onConfirm(): void; variant?: 'secondary' | 'danger' | 'glass' | 'light'; arrow?: boolean }) {
  const [asking, setAsking] = useState(false);
  return asking ? (
    <span className="app-confirm">
      <span className="rt-field-hint">{confirmText}</span>
      <Button size="sm" variant="ghost" onClick={() => setAsking(false)}>Cancel</Button>
      <Button size="sm" variant={variant === 'danger' ? 'danger' : 'primary'} onClick={onConfirm}>Confirm</Button>
    </span>
  ) : <Button variant={variant} arrow={arrow} onClick={() => setAsking(true)}>{children}</Button>;
}

/** Read an image file into a small JPEG data URL, so the demo survives a refresh. */
export async function shrink(file: File, max = 900): Promise<string> {
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const c = document.createElement('canvas');
  c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
  c.getContext('2d')!.drawImage(bmp, 0, 0, c.width, c.height);
  return c.toDataURL('image/jpeg', 0.8);
}
