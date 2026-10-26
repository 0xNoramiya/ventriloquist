// Prepares public/ for the hosted demo: the Python sources for Pyodide and the simulation results.
import { execFileSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..', '..');
const pub = resolve(here, '..', 'public');

execFileSync('python3', [resolve(root, 'scripts', 'build_pyodide_bundle.py')], { stdio: 'inherit' });
mkdirSync(resolve(pub, 'demo'), { recursive: true });
for (const name of ['sim_results.json', 'learning_curve.json']) {
  const src = resolve(root, 'docs', name);
  if (existsSync(src)) copyFileSync(src, resolve(pub, 'demo', name));
}
console.log('demo assets ready in public/');
