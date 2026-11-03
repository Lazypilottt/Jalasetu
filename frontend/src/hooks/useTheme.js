import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'jalasetu.theme';
const MODES = ['system', 'light', 'dark'];

function readStored() {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return MODES.includes(value) ? value : 'system';
  } catch {
    return 'system';
  }
}

function systemPrefersDark() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
}

/**
 * Theme preference: 'system' follows the OS, 'light'/'dark' pin it.
 * The resolved theme is written to <html data-theme>, which the CSS tokens
 * read; index.html applies the stored value before React mounts.
 *
 * @returns {{ mode: string, resolved: 'light'|'dark', setMode: (m: string) => void, cycle: () => void }}
 */
export default function useTheme() {
  const [mode, setModeState] = useState(readStored);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!media) return undefined;
    const onChange = (event) => setSystemDark(event.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  const resolved = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolved === 'dark' ? '#070b14' : '#f8fafc');
  }, [resolved]);

  const setMode = useCallback((next) => {
    setModeState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Preference persistence is a convenience only.
    }
  }, []);

  const cycle = useCallback(() => setMode(MODES[(MODES.indexOf(mode) + 1) % MODES.length]), [mode, setMode]);

  return { mode, resolved, setMode, cycle };
}
