import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { PublicConfig } from '../api/types';

let cached: PublicConfig | null = null;
let inflight: Promise<PublicConfig> | null = null;

export function loadConfig(force = false): Promise<PublicConfig> {
  if (cached && !force) return Promise.resolve(cached);
  if (!inflight || force) {
    inflight = api
      .config()
      .then((c) => {
        cached = c;
        return c;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function setCachedConfig(c: PublicConfig): void {
  cached = c;
}

export function useConfig(): {
  config: PublicConfig | null;
  error: string | null;
  reload: () => void;
} {
  const [config, setConfig] = useState<PublicConfig | null>(cached);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    loadConfig(true)
      .then((c) => {
        setConfig(c);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(() => {
    let alive = true;
    loadConfig()
      .then((c) => {
        if (alive) setConfig(c);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, []);
  return { config, error, reload };
}
