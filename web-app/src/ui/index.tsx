// TSX port of return-branding-v3/components/bundle.js. Markup, rt- classes, ARIA and props match index.d.ts.
import { useEffect, useId, useRef, useState } from 'react';
import type * as React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import './invite.css';

const cx = (...a: unknown[]) => a.filter(Boolean).join(' ');
export const initials = (n?: string) => (n || '?').split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();

/* ---------- Icon ---------- */
const P = {
  upload: ['M12 16V4', 'M7 9l5-5 5 5', 'M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3'],
  photos: ['M4 7h12v12H4z', 'M8 7V4h12v12h-4', 'M4 16l4-4 3 3 2-2 3 3'],
  check: ['M5 12.5l4.5 4.5L19 7.5'],
  x: ['M6 6l12 12', 'M18 6L6 18'],
  alert: ['M12 3.5l9.5 16.5h-19z', 'M12 10v4.5', 'M12 17.3v.2'],
  clock: ['M12 3.5a8.5 8.5 0 1 0 0 17a8.5 8.5 0 1 0 0-17z', 'M12 7.5V12l3 2'],
  lock: ['M6 11h12v9H6z', 'M8.5 11V8a3.5 3.5 0 0 1 7 0v3'],
  people: ['M9 11a3 3 0 1 0 0-6a3 3 0 1 0 0 6z', 'M3.5 19a5.5 5.5 0 0 1 11 0', 'M16 5.3a3 3 0 0 1 0 5.4', 'M17.5 14a5.5 5.5 0 0 1 3 5'],
  link: ['M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1', 'M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1'],
  copy: ['M9 9h11v11H9z', 'M15 9V4H4v11h5'],
  headset: ['M3 9.5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-4l-1.5-2h-3L9 16.5H5a2 2 0 0 1-2-2z'],
  enter: ['M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4', 'M10 16l4-4-4-4', 'M4 12h10'],
  home: ['M4 11l8-6.5 8 6.5', 'M6 9.5V20h12V9.5'],
  plus: ['M12 5v14', 'M5 12h14'],
  pinch: ['M7 13V6.5a1.5 1.5 0 0 1 3 0V11', 'M10 10.5V5a1.5 1.5 0 0 1 3 0v6', 'M13 10.5a1.5 1.5 0 0 1 3 0V14a6 6 0 0 1-6 6h-.5A5.5 5.5 0 0 1 4 14.5V12a1.5 1.5 0 0 1 3 0'],
  back: ['M9 7l-5 5 5 5', 'M4 12h11a5 5 0 0 1 0 10h-2'],
  arrowRight: ['M5 12h14', 'M13 6l6 6-6 6'],
  arrowUpRight: ['M7 17L17 7', 'M8 7h9v9'],
  play: ['M8 5.5v13l10.5-6.5z'],
  menu: ['M4 8h16', 'M4 16h16'],
  sun: ['M6 14a6 6 0 0 1 12 0z', 'M4 17h16', 'M7 20h10'],
  moon: ['M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z'],
  search: ['M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14z', 'M20 20l-4-4'],
  more: ['M12 6v.01', 'M12 12v.01', 'M12 18v.01'],
  mail: ['M4 6h16v12H4z', 'M4 7l8 6 8-6'],
  refresh: ['M20 11a8 8 0 0 0-14.3-4.9L4 8', 'M4 4v4h4', 'M4 13a8 8 0 0 0 14.3 4.9L20 16', 'M20 20v-4h-4'],
  spinner: ['M12 3.5a8.5 8.5 0 1 0 8.5 8.5'],
};
export type IconName = keyof typeof P;

export function Icon({ name, size = 20, strokeWidth = 1.5, label, className }: { name: IconName; size?: number; strokeWidth?: number; label?: string; className?: string }) {
  return (
    <svg className={cx('rt-icon', name === 'spinner' && 'rt-spin', className)} width={size} height={size} viewBox="0 0 24 24" fill={name === 'play' ? 'currentColor' : 'none'}
      stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden={label ? undefined : true} role={label ? 'img' : undefined} aria-label={label}>
      {P[name].map((d, i) => <path key={i} d={d} />)}
    </svg>
  );
}

/* ---------- Button ---------- */
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'light' | 'glass' | 'text';
  size?: 'sm' | 'md' | 'lg'; icon?: IconName; iconAfter?: IconName; arrow?: boolean | IconName; loading?: boolean; fullWidth?: boolean;
};
export function Button({ variant = 'secondary', size = 'md', icon, iconAfter, arrow, loading, fullWidth, className, children, type = 'button', disabled, ...rest }: ButtonProps) {
  const is = size === 'sm' ? 14 : 18;
  return (
    <button {...rest} type={type} disabled={disabled || loading} aria-busy={loading || undefined}
      className={cx('rt-btn', 'rt-btn-' + variant, size !== 'md' && 'rt-btn-' + size, arrow && 'rt-btn-arrow', fullWidth && 'rt-btn-full', className)}>
      {loading ? <Icon name="spinner" size={is} /> : icon ? <Icon name={icon} size={is} /> : null}
      {children}
      {iconAfter && <Icon name={iconAfter} size={is} />}
      {arrow && <span className="rt-btn-dot" aria-hidden><Icon name={arrow === true ? 'arrowRight' : arrow} size={size === 'sm' ? 12 : 16} strokeWidth={2} /></span>}
    </button>
  );
}

/* ---------- Field ---------- */
type FieldProps = Omit<React.InputHTMLAttributes<HTMLInputElement & HTMLTextAreaElement>, 'onSubmit'> & {
  label?: React.ReactNode; hint?: React.ReactNode; error?: React.ReactNode; multiline?: boolean; rows?: number; onImage?: boolean; onSubmit?: (v: string) => void; submitLabel?: string;
};
export function Field({ label, hint, error, multiline, onImage, onSubmit, submitLabel, className, onKeyDown, ...rest }: FieldProps) {
  const id = useId();
  const describedBy = ((hint && !error) ? id + '-h ' : '') + (error ? id + '-e' : '');
  const Tag = multiline ? 'textarea' : 'input';
  const control = (
    <Tag {...rest} id={id} className={cx('rt-input', onImage && 'rt-input-glass')} aria-invalid={error ? true : undefined} aria-describedby={describedBy.trim() || undefined}
      onKeyDown={(e: React.KeyboardEvent<HTMLInputElement & HTMLTextAreaElement>) => { if (onSubmit && e.key === 'Enter' && !multiline) onSubmit(e.currentTarget.value); onKeyDown?.(e); }} />
  );
  return (
    <div className={cx('rt-field', className)}>
      {label && <label className={cx('rt-field-label', onImage && 'rt-on-image')} htmlFor={id}>{label}</label>}
      {onSubmit ? (
        <div className="rt-inputwrap">{control}
          <button type="button" className={cx('rt-iconbtn', onImage && 'rt-iconbtn-light')} aria-label={submitLabel || 'Submit'}
            onClick={() => onSubmit((document.getElementById(id) as HTMLInputElement | null)?.value ?? '')}><Icon name="arrowRight" size={16} strokeWidth={2} /></button>
        </div>
      ) : control}
      {hint && !error && <div className="rt-field-hint" id={id + '-h'} style={onImage ? { color: 'var(--on-image)' } : undefined}>{hint}</div>}
      {error && <div className="rt-field-error" id={id + '-e'}><Icon name="alert" size={16} />{error}</div>}
    </div>
  );
}

/* ---------- GlassNav ---------- */
export interface NavItem { label: string; active?: boolean; onClick?: () => void }
export function GlassNav({ items = [], brand, cta, plain, label, className }: { items?: NavItem[]; brand?: React.ReactNode; cta?: React.ReactNode; plain?: boolean; label?: string; className?: string }) {
  return (
    <nav className={cx('rt-nav', plain ? 'rt-nav-plain' : 'rt-glass', className)} aria-label={label || 'Main'}>
      {brand && <span className="rt-nav-brand">{brand}</span>}
      <span className="rt-nav-items">
        {items.map((it, i) => <a key={i} href="#" aria-current={it.active ? 'page' : undefined} onClick={(e) => { e.preventDefault(); it.onClick?.(); }}>{it.label}</a>)}
      </span>
      {cta}
    </nav>
  );
}

export function Eyebrow({ badge, children }: { badge?: React.ReactNode; children?: React.ReactNode }) {
  return <span className="rt-eyebrow rt-glass">{badge && <b>{badge}</b>}{children}</span>;
}

/* ---------- StatusTag ---------- */
export type RoomStatus = 'new' | 'invited' | 'waiting' | 'developing' | 'ready' | 'shared' | 'private' | 'failed';
const STATUS: Record<RoomStatus, { icon: IconName; word: string }> = {
  developing: { icon: 'spinner', word: 'Building' }, waiting: { icon: 'people', word: 'Waiting' }, invited: { icon: 'mail', word: 'Invitation' },
  ready: { icon: 'check', word: 'Ready' }, shared: { icon: 'people', word: 'Shared' }, private: { icon: 'lock', word: 'Private' },
  failed: { icon: 'alert', word: "Couldn't build" }, new: { icon: 'sun', word: 'New' },
};
export function StatusTag({ status, onImage, children, className }: { status: RoomStatus; onImage?: boolean; children?: React.ReactNode; className?: string }) {
  const s = STATUS[status];
  return <span className={cx('rt-tag', 'rt-tag-' + status, onImage && 'rt-glass', className)}><Icon name={s.icon} size={14} strokeWidth={2} />{children || s.word}</span>;
}

/* ---------- PresenceStack ---------- */
export interface Person { name: string; here?: boolean; role?: 'owner' | 'visit' | 'add'; note?: string; email?: string }
export function PresenceStack({ people, max = 4, size, showLabel, onImage, className }: { people: Person[]; max?: number; size?: 'sm' | 'md' | 'lg'; showLabel?: boolean; onImage?: boolean; className?: string }) {
  const shown = people.slice(0, max), extra = people.length - shown.length, here = people.filter((p) => p.here);
  const sz = size === 'sm' ? 'rt-avatar-sm' : size === 'lg' ? 'rt-avatar-lg' : null;
  return (
    <span className={cx('rt-stack', onImage && 'rt-stack-onimage', className)} role="group" aria-label={people.length + ' people' + (here.length ? ', ' + here.length + ' here now' : '')}>
      {shown.map((p, i) => <span key={i} className={cx('rt-avatar', sz, p.here && 'rt-avatar-here')} title={p.name + (p.here ? ' (here now)' : '')}>{initials(p.name)}</span>)}
      {extra > 0 && <span className={cx('rt-avatar', 'rt-avatar-more', sz)}>+{extra}</span>}
      {showLabel && here.length > 0 && <span className="rt-stack-label">{here.length} here now</span>}
    </span>
  );
}

/* ---------- RoomCard ---------- */
export function RoomCard(props: { src?: string; title?: string; meta?: string; status?: RoomStatus; statusText?: string; progress?: number; people?: Person[]; onOpen?: (e: React.MouseEvent) => void; onManage?: (e: React.MouseEvent) => void; action?: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  const st = props.status || null;
  return (
    <div className={cx('rt-card', props.status === 'developing' && 'rt-card-developing', props.className)} style={props.style}>
      {props.src ? <img className="rt-img" src={props.src} alt="" loading="lazy" decoding="async" /> : <span className="rt-img rt-sky" />}
      <span className="rt-scrim-bottom" />
      <button type="button" className="rt-card-hit" onClick={props.onOpen} aria-label={'Open ' + (props.title || 'room') + (st ? ', ' + (props.statusText || STATUS[st].word) : '')} />
      <span className="rt-card-top">
        {st ? <StatusTag status={st} onImage>{props.statusText}</StatusTag> : <span />}
        {props.onManage && <button type="button" className="rt-iconbtn rt-card-menu" aria-label={'Manage ' + (props.title || 'room')} onClick={props.onManage}><Icon name="more" size={16} strokeWidth={2.5} /></button>}
      </span>
      <span className="rt-card-foot">
        <span><span className="rt-card-title">{props.title || 'Untitled room'}</span>{props.meta && <span className="rt-card-meta">{props.meta}</span>}</span>
        {props.people?.length ? <PresenceStack people={props.people} max={3} size="sm" onImage /> : null}
      </span>
      {props.status === 'developing' && typeof props.progress === 'number' && (
        <span className="rt-card-progress"><i style={{ width: props.progress * 100 + '%' }} /></span>
      )}
      {props.action && <span className="rt-card-action">{props.action}</span>}
    </div>
  );
}

/* ---------- PhotoDrop ---------- */
export interface Photo { src: string; name?: string; id?: string }
export function PhotoDrop({ photos = [], max = 12, onFiles, onRemove, error, className }: { photos?: Photo[]; max?: number; onFiles?: (f: File[]) => void; onRemove?: (i: number) => void; onImage?: boolean; error?: React.ReactNode; className?: string }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const full = photos.length >= max;
  const take = (list: FileList | null) => {
    const files = Array.from(list || []).filter((f) => f.type.startsWith('image/'));
    if (files.length) onFiles?.(files.slice(0, Math.max(0, max - photos.length)));
  };
  const open = () => input.current?.click();
  return (
    <div className={className}>
      <div className={cx('rt-arch', over && 'rt-arch-active')} role="button" tabIndex={0} aria-label="Add photos. Drop images here or press Enter to choose files."
        onClick={open} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } }}
        onDragOver={(e) => { e.preventDefault(); if (!over) setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files); }}>
        <div className="rt-arch-tiles" role="list" aria-label="Selected photos">
          {photos.map((p, i) => (
            <div key={p.id || i} role="listitem" className={cx('rt-arch-tile', 'app-focus-in', 'app-photo', i === 0 && 'rt-thumb-cover')}>
              <img className="rt-img" src={p.src} alt={p.name || 'Photo ' + (i + 1)} />
              {onRemove && <button type="button" className="rt-iconbtn" aria-label={'Remove ' + (p.name || 'photo ' + (i + 1))} onClick={(e) => { e.stopPropagation(); onRemove(i); }}><Icon name="x" size={14} strokeWidth={2} /></button>}
            </div>
          ))}
        </div>
        {!full && (
          <div className={cx('rt-arch-prompt', photos.length > 0 && 'rt-arch-prompt-small')} aria-hidden>
            {photos.length === 0 ? (
              <>
                <span className="rt-drop-icon"><Icon name={over ? 'photos' : 'upload'} size={24} /></span>
                <span className="rt-drop-title">{over ? <>Let <em>go</em></> : <>Bring a <em>moment</em> back</>}</span>
                <span className="rt-drop-hint">Drop 1 to {max} photos of the same place.</span>
              </>
            ) : <span className="rt-arch-addmore">{over ? 'Let go' : 'Add more'}</span>}
          </div>
        )}
        <input ref={input} type="file" accept="image/*" multiple hidden onChange={(e) => { take(e.target.files); e.target.value = ''; }} />
      </div>
      {photos.length > 0 && <div className="rt-drop-count"><span>{photos.length} of {max} photos</span><span>The first photo is the cover</span></div>}
      {error && <div className="rt-field-error"><Icon name="alert" size={16} />{error}</div>}
    </div>
  );
}

/* ---------- DevelopProgress ---------- */
export const DEVELOP_STEPS = ['Reading your photos', 'Estimating depth', 'Building the world', 'Setting the light'];
export function DevelopProgress({ src, title, steps = DEVELOP_STEPS, progress = 0, actions, photo, className }: { src?: string; title?: string; steps?: string[]; progress?: number; actions?: React.ReactNode; photo?: boolean; className?: string }) {
  const pct = Math.max(0, Math.min(1, progress)), cur = Math.min(steps.length - 1, Math.floor(pct * steps.length));
  const f = `blur(${(18 - 18 * pct).toFixed(1)}px) saturate(${(0.35 + 0.65 * pct).toFixed(2)}) brightness(${(1.25 - 0.25 * pct).toFixed(2)})`;
  return (
    <section className={cx('rt-develop', className)} aria-live="polite">
      <div className={cx('rt-develop-photo', photo && 'app-photo')}>
        {src && <img className="rt-img" src={src} alt="" style={{ filter: f }} />}
        <div className="rt-develop-mist" style={{ opacity: (1 - pct) * 0.85 }} />
      </div>
      <div>
        <h3 className="rt-develop-title">{pct >= 1 ? <>Ready to <em>return</em></> : <>Coming into <em>focus</em></>}</h3>
        <p className="rt-develop-sub app-italic">{pct >= 1 ? "Put on your headset. It's waiting in your rooms." : (title ? title + ' · ' : '') + 'About ten seconds. Watch it come into focus.'}</p>
        <div className="rt-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct * 100)} aria-label="Building the world">
          <i style={{ width: pct * 100 + '%' }} />
        </div>
        <ol className="rt-steps">
          {steps.map((s, i) => {
            const state = i < cur || pct >= 1 ? 'done' : i === cur ? 'now' : 'todo';
            return <li key={i} className={cx('rt-step', 'rt-step-' + state)}><Icon name={state === 'done' ? 'check' : state === 'now' ? 'spinner' : 'clock'} size={16} strokeWidth={2} />{s}</li>;
          })}
        </ol>
        {actions && <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-5)', flexWrap: 'wrap' }}>{actions}</div>}
      </div>
    </section>
  );
}

/* ---------- ShareSheet ---------- */
export function ShareSheet({ title, people = [], onInvite, onRemove, onClose, results, onQuery, className }: { title?: string; people?: Person[]; onInvite?: (v: string) => void; onRemove?: (p: Person) => void; onClose?: () => void; results?: Invitee[]; onQuery?: (q: string) => void; className?: string }) {
  const withEmail = people.filter((p): p is Person & { email: string } => !!p.email);
  const invited: Invitee[] = withEmail.map((p) => ({ name: p.name, email: p.email }));
  const byEmail = (email: string) => withEmail.find((p) => p.email === email);
  return (
    <section className={cx('rt-share', className)} role="dialog" aria-label={'Share ' + (title || 'room')}>
      <div className="rt-share-head">
        <div><h2 className="rt-share-title">Who can <em>return</em> here</h2>{title && <p className="rt-share-sub">{title}</p>}</div>
        {onClose && <button type="button" className="rt-iconbtn rt-iconbtn-quiet" aria-label="Close" onClick={onClose}><Icon name="x" size={16} strokeWidth={2} /></button>}
      </div>
      {results || onQuery ? (
        <InviteSearch label="Invite by email" results={results} invited={withEmail.length ? invited : []}
          onQuery={onQuery} onInvite={(p) => onInvite?.(p.email)} onRemove={onRemove ? (p) => { const m = byEmail(p.email); if (m) onRemove(m); } : undefined} />
      ) : (
        <Field label="Invite by email" placeholder="sam@school.edu" onSubmit={(v) => { if (v) onInvite?.(v); }} submitLabel="Invite" />
      )}
      {people.length > 0 && (
        <div><p className="rt-section-label">People with access</p>
          <ul className="rt-people">
            <AnimatePresence>
              {people.map((p, i) => (
                <motion.li key={p.email || i} layout className="rt-person" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.26, ease: EASE }}>
                  <span className={cx('rt-avatar', p.here && 'rt-avatar-here')}>{initials(p.name)}</span>
                  <span className="rt-person-name">{p.name}<small>{p.role === 'owner' ? 'Made this room' : p.note || 'Invited'}</small></span>
                  {p.role === 'owner' ? <span className="rt-field-hint">Owner</span> : onRemove && <Button size="sm" variant="ghost" onClick={() => onRemove(p)}>Remove</Button>}
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        </div>
      )}
    </section>
  );
}

/* ---------- Stepper ---------- */
export const ROOM_STEPS = ['Name and invite', 'Add your photos', 'Wait for everyone'];
export function Stepper({ steps = ROOM_STEPS, current = 0, onImage, className }: { steps?: string[]; current?: number; onImage?: boolean; className?: string }) {
  return (
    <ol className={cx('rt-stepper', onImage && 'rt-on-image', className)} aria-label="Progress">
      {steps.map((s, i) => (
        <li key={i} className={cx('rt-stepper-item', i < current && 'rt-stepper-done', i === current && 'rt-stepper-now')} aria-current={i === current ? 'step' : undefined}>
          <span className="rt-stepper-dot">{i < current ? <Icon name="check" size={12} strokeWidth={2.5} /> : i + 1}</span>{s}
        </li>
      ))}
    </ol>
  );
}

/* ---------- InviteSearch ---------- */
export interface Invitee { name?: string; email: string }
export const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const EASE = [0.16, 1, 0.3, 1] as const;
export function InviteSearch({ results = [], invited = [], onQuery, onInvite, onRemove, label, className }: { results?: Invitee[]; invited?: Invitee[]; onQuery?: (q: string) => void; onInvite?: (p: Invitee) => void; onRemove?: (p: Invitee) => void; label?: string; className?: string }) {
  const [q, setQ] = useState('');
  const [settled, setSettled] = useState(true);
  const id = useId();
  const isInvited = (email: string) => invited.some((p) => p.email === email);
  const raw = q.trim(), showRaw = EMAIL.test(raw) && !results.some((r) => r.email === raw) && !isInvited(raw);
  const partialEmail = raw.includes('@') && !EMAIL.test(raw);

  // A brief "searching" beat before results settle in, so the list never just snaps into place.
  useEffect(() => {
    if (!raw) { setSettled(true); return; }
    setSettled(false);
    const t = setTimeout(() => setSettled(true), 220);
    return () => clearTimeout(t);
  }, [raw]);

  const invite = (p: Invitee) => { onInvite?.(p); setQ(''); onQuery?.(''); };
  const row = (p: Invitee, isNew: boolean, i: number) => (
    <motion.li key={p.email} className="rt-result" role="option" aria-selected={false}
      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.26, delay: i * 0.06, ease: EASE }}>
      <span className="rt-avatar">{isNew ? <Icon name="mail" size={14} /> : initials(p.name || p.email)}</span>
      <span className="rt-person-name">{isNew ? 'Invite ' + p.email : p.name}<small>{isNew ? "Not on return yet. We'll email them an invite." : p.email}</small></span>
      {isInvited(p.email) ? <span className="rt-result-done"><Icon name="check" size={14} strokeWidth={2.5} />Invited</span>
        : <Button size="sm" variant="secondary" icon="plus" onClick={() => invite(p)}>Invite</Button>}
    </motion.li>
  );
  const rows = [...results.map((p, i) => row(p, false, i)), ...(showRaw ? [row({ email: raw }, true, results.length)] : [])];

  return (
    <div className={cx('rt-invite', className)}>
      <div className="rt-field">
        <label className="rt-field-label" htmlFor={id}>{label || 'Invite people by email'}</label>
        <div className="rt-inputwrap rt-inputwrap-lead">
          <span className="rt-input-lead" aria-hidden><Icon name="search" size={18} /></span>
          <input id={id} className="rt-input" type="search" value={q} placeholder="Search by name or email" autoComplete="off"
            onChange={(e) => { setQ(e.target.value); onQuery?.(e.target.value); }}
            onKeyDown={(e) => {
              if (e.key !== 'Enter') return;
              e.preventDefault();
              if (results[0]) invite(results[0]);
              else if (EMAIL.test(raw)) invite({ email: raw });
            }} />
        </div>
      </div>
      {raw && !settled ? (
        <ul className="rt-results" role="listbox" aria-label="Search results">
          <li className="rt-result rt-result-loading" role="option" aria-selected={false} aria-label="Searching">
            <span className="rt-avatar rt-shimmer" aria-hidden />
            <span className="rt-person-name"><span className="rt-bar rt-shimmer" /><small><span className="rt-bar rt-bar-sm rt-shimmer" /></small></span>
          </li>
        </ul>
      ) : raw && rows.length ? (
        <ul className="rt-results" role="listbox" aria-label="Search results">
          <AnimatePresence mode="popLayout">{rows}</AnimatePresence>
        </ul>
      ) : raw && settled && !partialEmail ? (
        <p className="rt-field-hint" style={{ margin: 0 }}>No one found. Type their full email to invite them.</p>
      ) : null}
      {invited.length > 0 && (
        <div><p className="rt-section-label">Invited ({invited.length})</p>
          <ul className="rt-chips">
            <AnimatePresence>
              {invited.map((p) => (
                <motion.li key={p.email} layout className="rt-chip"
                  initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1, transition: { duration: 0.22, ease: EASE } }} exit={{ opacity: 0, scale: 0.9, transition: { duration: 0.16, ease: EASE } }}>
                  <span className="rt-avatar rt-avatar-sm">{initials(p.name || p.email)}</span>{p.name || p.email}
                  {onRemove && <button type="button" className="rt-chip-x" aria-label={'Remove ' + (p.name || p.email)} onClick={() => onRemove(p)}><Icon name="x" size={12} strokeWidth={2.5} /></button>}
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        </div>
      )}
    </div>
  );
}

/* ---------- MemberList ---------- */
export interface MemberRow { name?: string; email?: string; status: 'done' | 'uploading' | 'joined' | 'invited'; count?: number; hasNote?: boolean; sentAgo?: string; isYou?: boolean; isOwner?: boolean; here?: boolean }
const MEMBER: Record<MemberRow['status'], { icon: IconName; cls: string }> = {
  done: { icon: 'check', cls: 'rt-m-done' }, uploading: { icon: 'spinner', cls: 'rt-m-uploading' }, joined: { icon: 'clock', cls: 'rt-m-joined' }, invited: { icon: 'mail', cls: 'rt-m-invited' },
};
function memberLine(m: MemberRow) {
  if (m.status === 'done') return `Added ${m.count || 0} photo${m.count === 1 ? '' : 's'}${m.hasNote ? ' and a note' : ''}`;
  if (m.status === 'uploading') return 'Adding photos';
  if (m.status === 'joined') return "Joined, hasn't added photos yet";
  return 'Invite sent' + (m.sentAgo ? ' ' + m.sentAgo : '');
}
export function MemberList({ members, onResend, className }: { members: MemberRow[]; onResend?: (m: MemberRow) => void; className?: string }) {
  return (
    <ul className={cx('rt-members', className)} aria-label="People in this room">
      {members.map((m, i) => {
        const s = MEMBER[m.status];
        return (
          <motion.li layout key={m.email || i} className={cx('rt-member', s.cls)} style={{ position: 'relative', overflow: 'hidden' }}>
            {m.status === 'done' && (
              <motion.span key={m.status} aria-hidden style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
                animate={{ backgroundColor: ['var(--blossom-soft)', 'rgba(0,0,0,0)'] }} transition={{ duration: 0.9, ease: 'easeOut' }} />
            )}
            <span className={cx('rt-avatar', m.here && 'rt-avatar-here')}>{initials(m.name || m.email)}</span>
            <span className="rt-person-name">{(m.name || m.email) + (m.isYou ? ' (you)' : '')}<small><Icon name={s.icon} size={13} strokeWidth={2.25} />{memberLine(m)}</small></span>
            {m.status === 'invited' && onResend ? <Button size="sm" variant="ghost" icon="refresh" onClick={() => onResend(m)}>Resend</Button>
              : m.isOwner ? <span className="rt-field-hint">Owner</span> : null}
          </motion.li>
        );
      })}
    </ul>
  );
}

