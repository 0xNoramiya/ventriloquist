import { lazy, Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Landing } from './routes/Landing';

const Setup = lazy(() => import('./routes/Setup'));
const Calibrate = lazy(() => import('./routes/Calibrate'));
const Patient = lazy(() => import('./routes/Patient'));
const Caregiver = lazy(() => import('./routes/Caregiver'));
const Memory = lazy(() => import('./routes/Memory'));
const Eval = lazy(() => import('./routes/Eval'));
const Settings = lazy(() => import('./routes/Settings'));
const NotFound = lazy(() => import('./routes/NotFound'));
const Demo = lazy(() => import('./routes/Demo'));

export function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')}>
      <Suspense fallback={<div className="min-h-dvh" aria-busy="true" />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/calibrate/:pid" element={<Calibrate />} />
          <Route path="/patient/:sid" element={<Patient />} />
          <Route path="/caregiver/:sid" element={<Caregiver />} />
          <Route path="/demo/:sid" element={<Demo />} />
          <Route path="/memory/:pid" element={<Memory />} />
          <Route path="/eval" element={<Eval />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
