declare const __LAN_HOSTS__: string[];
declare const __PHONE_PORT__: string;

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

/** A local install (loopback, a private IPv4 address or a .local name), which a phone reaches only
 * on the same network and through a self-signed certificate. A hosted app is open from anywhere. */
export function onLocalNetwork(hostname: string = window.location.hostname): boolean {
  return (
    isLoopback(hostname) ||
    /^(10|192\.168|172\.(1[6-9]|2\d|3[01]))\./.test(hostname) ||
    hostname.endsWith('.local')
  );
}

/** Host (with port) the phone should open. Loopback is useless to a phone, so prefer a LAN IP. */
export function defaultPhoneHost(): string {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved) return saved;
  } catch {
    // storage blocked: work the host out from the page
  }
  const { hostname, host, port, protocol } = window.location;
  if (!isLoopback(hostname)) return host;
  const lan = lanHosts()[0];
  // The laptop may be on the plain-HTTP server; the phone needs the HTTPS one.
  const phonePort = protocol === 'http:' ? phonePortOr(port) : port;
  return lan ? `${lan}${phonePort ? `:${phonePort}` : ''}` : host;
}

function phonePortOr(fallback: string): string {
  try {
    return __PHONE_PORT__;
  } catch {
    return fallback;
  }
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
