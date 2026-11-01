import { describe, expect, it } from 'vitest';
import { onLocalNetwork } from './host';

describe('onLocalNetwork', () => {
  it('treats loopback, private addresses and .local names as a local install', () => {
    for (const h of [
      'localhost',
      '127.0.0.1',
      '192.168.1.20',
      '10.0.0.5',
      '172.20.3.4',
      'pi.local',
    ]) {
      expect(onLocalNetwork(h)).toBe(true);
    }
  });

  it('treats a public host as hosted, so the phone needs no same-network hint (issue #26)', () => {
    for (const h of ['ventriloquist.fly.dev', '66.241.124.160', '172.32.0.1']) {
      expect(onLocalNetwork(h)).toBe(false);
    }
  });
});
