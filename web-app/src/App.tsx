import { lazy, Suspense, useEffect } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import type * as React from 'react';
import { useSession } from './auth';
import { useRooms } from './data/store';
import { immersive } from './world/state';
import { Bloom } from './screens/shared';
import Landing from './screens/Landing';
import SignInPage from './screens/SignIn';
import Dashboard from './screens/Dashboard';
import CreateRoom from './screens/CreateRoom';
import RoomUpload from './screens/RoomUpload';
import RoomPage from './screens/RoomPage';

const SkyWorld = lazy(() => import('./world/SkyWorld'));

function Private({ children }: { children: React.ReactNode }) {
  const { loaded, signedIn } = useSession();
  const loc = useLocation();
  if (!loaded) return null;
  return signedIn ? <>{children}</> : <Navigate to={`/sign-in?next=${encodeURIComponent(loc.pathname)}`} replace />;
}

/** Plays the other people in each room, and '.' fast-forwards the room you're looking at. */
function useSimulator() {
  const loc = useLocation();
  // Rooms only advance on '.', no background timer, so the presenter controls every beat.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const room = loc.pathname.match(/^\/rooms\/([^/]+)/)?.[1];
      if (e.key !== '.' || !room || room === 'new' || (e.target as HTMLElement).closest('input, textarea')) return;
      useRooms.getState().fastForward(room);
    };
    addEventListener('keydown', key);
    return () => removeEventListener('keydown', key);
  }, [loc.pathname]);
}

export default function App() {
  const loc = useLocation();
  useSimulator();
  return (
    <MotionConfig reducedMotion="user">
      {immersive && <Suspense fallback={null}><SkyWorld /></Suspense>}
      <AnimatePresence mode="wait" onExitComplete={() => window.scrollTo(0, 0)}>
        <motion.div key={loc.pathname.startsWith('/sign-in') ? '/sign-in' : loc.pathname} className="app-page"
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}>
          <Routes location={loc}>
            <Route path="/" element={<Landing />} />
            <Route path="/sign-in" element={<SignInPage />} />
            <Route path="/rooms" element={<Private><Dashboard /></Private>} />
            <Route path="/rooms/new" element={<Private><CreateRoom /></Private>} />
            <Route path="/rooms/:id/add" element={<Private><RoomUpload /></Private>} />
            <Route path="/rooms/:id" element={<Private><RoomPage /></Private>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </motion.div>
      </AnimatePresence>
      <Bloom />
    </MotionConfig>
  );
}
