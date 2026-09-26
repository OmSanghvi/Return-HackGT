// Real mode's whole route tree. Mounted by App.tsx only when
// VITE_SKETCHSCAPE_API_URL is set; mock mode never imports this module's
// screens, only the tiny REAL_MODE check in config.ts.
import { Navigate, Route, Routes } from 'react-router-dom';
import RealProjectsPage from './RealProjectsPage';
import RealProjectPage from './RealProjectPage';

export default function RealApp() {
  return (
    <Routes>
      <Route path="/" element={<RealProjectsPage />} />
      <Route path="/projects/:id" element={<RealProjectPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
