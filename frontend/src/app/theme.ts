export type ThemeMode = 'auto' | 'light' | 'dark';
const key = 'revocompute-theme';

export function applyTheme(mode: ThemeMode): void {
  const dark = mode === 'dark' || (mode === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  document.documentElement.dataset.themeMode = mode;
}
export function storedTheme(): ThemeMode {
  const value = localStorage.getItem(key); return value === 'light' || value === 'dark' ? value : 'auto';
}
export function cycleTheme(): ThemeMode {
  const next: ThemeMode = storedTheme() === 'auto' ? 'dark' : storedTheme() === 'dark' ? 'light' : 'auto';
  localStorage.setItem(key, next); applyTheme(next); return next;
}

