import '@fontsource-variable/atkinson-hyperlegible-next';
import './index.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';

// Static hosting (GitHub Pages) serves deep links through its 404 page, so the hosted demo opens
// them as ?r=<path>; restore the path before the router reads it.
const deepLink = new URLSearchParams(window.location.search).get('r');
if (deepLink) {
  window.history.replaceState(null, '', import.meta.env.BASE_URL + deepLink.replace(/^\/+/, ''));
}

const root = document.getElementById('root');
if (!root) throw new Error('#root missing');
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
