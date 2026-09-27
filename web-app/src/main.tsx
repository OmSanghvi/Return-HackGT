import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import './design-system/tokens.css';
import './design-system/bundle.css';
import './app.css';
import App from './App';
import { useRooms } from './data/store';
import { useMockBuilds } from './real/vrBuild';

// /?reset puts the demo back to its seeded rooms (and forgets simulated VR builds).
if (new URLSearchParams(location.search).has('reset')) { useRooms.getState().reset(); useMockBuilds.setState({ builds: {} }); history.replaceState(null, '', location.pathname); }

createRoot(document.getElementById('root')!).render(
  <StrictMode><BrowserRouter><App /></BrowserRouter></StrictMode>,
);
