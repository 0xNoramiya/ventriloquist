declare const __LAN_HOSTS__: string[];

const STORAGE_KEY = 'ventriloquist.phoneHost';

export function lanHosts(): string[] {
  try {
    return __LAN_HOSTS__;
  } catch {
    return [];
  }
}

function isLoopback(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
}

/** Host (with port) the phone should open. Loopback is useless to a phone, so prefer a LAN IP. */
export function defaultPhoneHost(): string {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved) return saved;
  } catch {
    // ignore
  }
  const { hostname, host, port } = window.location;
  if (!isLoopback(hostname)) return host;
  const lan = lanHosts()[0];
  return lan ? `${lan}${port ? `:${port}` : ''}` : host;
}

export function savePhoneHost(host: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, host);
  } catch {
    // not persisted
  }
}

export function patientUrl(host: string, sid: string): string {
  return `https://${host}/patient/${sid}`;
}
