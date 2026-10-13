import { useSyncExternalStore } from 'react';

// Global "live video" switch. Off = no camera stream / snapshot requests anywhere in the UI
// (saves CPU on the server and network bandwidth). Remembered per browser.
const KEY = 'lm.liveVideo';
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return localStorage.getItem(KEY) !== 'off';
  } catch {
    return true;
  }
}

let current = read();

export function setLiveVideo(on: boolean): void {
  current = on;
  try {
    localStorage.setItem(KEY, on ? 'on' : 'off');
  } catch {
    /* storage blocked: keep in memory only */
  }
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      current = read();
      cb();
    }
  };
  window.addEventListener('storage', onStorage); // other tabs
  return () => {
    listeners.delete(cb);
    window.removeEventListener('storage', onStorage);
  };
}

export function useLiveVideo(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, () => current, () => true);
  return [on, setLiveVideo];
}
