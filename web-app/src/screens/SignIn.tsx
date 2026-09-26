import { motion } from 'motion/react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Field } from '../ui';
import { useSession } from '../auth';
import { ME, useRooms } from '../data/store';
import { Stage } from '../world/Stage';
import { Logo, reveal } from './shared';
import { useEffect } from 'react';
import { REAL_MODE, DEMO_ACCOUNTS } from '../config';
import { accountLabel, useAccount } from '../api/account';

export default function SignInPage() {
  const navigate = useNavigate();
  const next = useSearchParams()[0].get('next') || '/rooms';
  const { signedIn } = useSession();
  useEffect(() => { if (signedIn) navigate(next, { replace: true }); }, [signedIn, next, navigate]);

  return (
    <div className="app-shell">
    <Stage scene="clouds" scrim="none" className="app-full app-center" label="Sign in">
      <a className="app-corner-logo" href="/" onClick={(e) => { e.preventDefault(); navigate('/'); }}><Logo /></a>
      <motion.form className="app-signin rt-glass-strong" {...reveal(1)} onSubmit={(e) => { e.preventDefault(); useRooms.getState().signIn(); }}>
        <p className="rt-kicker app-kicker-ink">Sign in</p>
        <h1 className="display-m" style={{ margin: 0 }}>Welcome back</h1>
        <p className="app-italic">your rooms are where you left them</p>
        {REAL_MODE ? DEMO_ACCOUNTS.map((id, i) => (
          <Button key={id} variant={i ? 'secondary' : 'primary'} size="lg" arrow fullWidth
            onClick={() => { useAccount.getState().setAccount(id); useRooms.getState().signIn(); }}>Continue as {accountLabel(id)}</Button>
        )) : <>
          <Field label="Email" type="email" autoComplete="email" defaultValue={ME.email} required />
          <Field label="Password" type="password" autoComplete="current-password" defaultValue="returnhome" required />
          <Button type="submit" variant="primary" size="lg" arrow fullWidth>Continue</Button>
        </>}
      </motion.form>
    </Stage>
    </div>
  );
}
