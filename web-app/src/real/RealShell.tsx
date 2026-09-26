// Real mode's header: the logo, and the account picker in place of a
// sign-in screen (collab-vr-accounts-and-gates: "a picker in place of a
// sign-in screen", persistent so switching is always one click away).
import { useEffect, useRef, useState } from 'react';
import type * as React from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Icon } from '../ui';
import { useAccount, accountLabel } from '../api/account';
import { DEMO_ACCOUNTS } from '../config';
import lockupWhite from '../design-system/logos/return-lockup-white.svg';

function AccountPicker() {
  const { current, setAccount } = useAccount();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    const down = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    addEventListener('keydown', key);
    addEventListener('mousedown', down);
    return () => {
      removeEventListener('keydown', key);
      removeEventListener('mousedown', down);
    };
  }, [open]);

  return (
    <div className="app-account" ref={ref}>
      <button type="button" className="app-account-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="rt-avatar app-me" aria-hidden>
          {accountLabel(current).replace('Account ', 'A')}
        </span>
        <span className="app-account-name">{accountLabel(current)}</span>
      </button>
      {open && (
        <div className="app-account-menu rt-glass-strong" role="menu">
          <p className="caption app-account-who">
            Acting as <strong>{accountLabel(current)}</strong> ({current})
          </p>
          {DEMO_ACCOUNTS.map((id) => (
            <button
              key={id}
              type="button"
              role="menuitemradio"
              aria-checked={id === current}
              onClick={() => {
                setAccount(id);
                setOpen(false);
              }}
            >
              <Icon name={id === current ? 'check' : 'people'} size={16} />
              {accountLabel(id)} ({id})
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function RealShell({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  return (
    <div className="app-shell">
      <div className="app-bar">
        <a
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate('/');
          }}
          aria-label="SketchScape, back to projects"
        >
          <img src={lockupWhite} alt="return" height={26} />
        </a>
        <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
          <Button variant="ghost" size="sm" icon="home" onClick={() => navigate('/')}>
            Projects
          </Button>
          <AccountPicker />
        </div>
      </div>
      {children}
    </div>
  );
}
