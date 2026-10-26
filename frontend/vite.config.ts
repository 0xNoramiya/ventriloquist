import { networkInterfaces } from 'node:os';
import basicSsl from '@vitejs/plugin-basic-ssl';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The backend (FastAPI) runs on plain HTTP. The phone only ever talks HTTPS to this dev server,
// which proxies /api and /ws, so there is no mixed content and the camera is allowed.
const backend = process.env.VENTRILOQUIST_API ?? 'http://127.0.0.1:8000';

// LAN addresses, so the caregiver screen can print a QR code the phone can actually open.
// Virtual bridges (Docker, VPN, libvirt) are skipped; home and office ranges come first.
function lanHosts(): string[] {
  const skip = /^(lo|docker|br-|veth|virbr|wg|tun|tap|utun|zt)/;
  const out: string[] = [];
  for (const [name, list] of Object.entries(networkInterfaces())) {
    if (skip.test(name)) continue;
    for (const addr of list ?? []) {
      if (addr.family === 'IPv4' && !addr.internal) out.push(addr.address);
    }
  }
  const rank = (ip: string) => (ip.startsWith('192.168.') ? 0 : ip.startsWith('10.') ? 1 : 2);
  return out.sort((a, b) => rank(a) - rank(b));
}

export default defineConfig({
  plugins: [react(), tailwindcss(), basicSsl({ name: 'ventriloquist' })],
  define: {
    __LAN_HOSTS__: JSON.stringify(lanHosts()),
  },
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    // IP addresses are always allowed; these cover `cloudflared` quick tunnels and mDNS names.
    allowedHosts: ['.trycloudflare.com', '.local'],
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true, changeOrigin: true },
    },
  },
  preview: {
    host: true,
    port: 4173,
    allowedHosts: ['.trycloudflare.com', '.local'],
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true, changeOrigin: true },
    },
  },
  build: {
    target: 'es2022',
    sourcemap: true,
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
