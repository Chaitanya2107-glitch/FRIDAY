import type { Mode, PillSnippet } from './types.ts';

export function readReminder(value: unknown, now = Date.now()): PillSnippet | null {
  if (typeof value !== 'object' || value === null) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.text !== 'string' || !v.text.trim() || v.text.length > 80
    || typeof v.show_from !== 'number' || !Number.isFinite(v.show_from)
    || typeof v.expires_at !== 'number' || !Number.isFinite(v.expires_at)
    || v.show_from > now || v.expires_at <= now || v.expires_at - v.show_from > 86400000) return null;
  return { text: v.text, show_from: v.show_from, expires_at: v.expires_at };
}

export type Event = 'hover' | 'leave' | 'expand' | 'sneak' | 'escape' | 'idle' | 'projects' | 'settings';
export function transition(mode: Mode, event: Event, hide = false): Mode {
  if (event === 'sneak') return mode === 'sneak' ? (hide ? 'hidden' : 'rest') : 'sneak';
  if (event === 'escape') return hide ? 'hidden' : 'rest';
  if (event === 'projects' || event === 'settings') return 'expanded';
  if (event === 'expand') return mode === 'peek' ? 'expanded' : mode === 'expanded' ? (hide ? 'hidden' : 'rest') : 'peek';
  if (event === 'hover' && (mode === 'rest' || mode === 'hidden')) return 'peek';
  if (event === 'leave' && mode === 'peek') return hide ? 'hidden' : 'rest';
  if (event === 'idle' && mode === 'rest' && hide) return 'hidden';
  return mode;
}

// Literal DOM text is used for all backend/user data. Never interpolate it into markup.
export function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

export function localSuggestions(text: string, names: { pins: { name: string; visible: boolean }[]; projects: { name: string }[] }): string[] {
  const [head, ...rest] = text.trim().split(/\s+/);
  const query = rest.join(' ').toLowerCase();
  const subsequence = (q: string, s: string) => {
    let i = 0;
    for (const c of s.toLowerCase()) if (c === q[i]) i++;
    return i === q.length;
  };
  if (head === 'open' || head === 'proj') {
    const rows = head === 'open' ? names.pins.filter(p => p.visible) : names.projects;
    return rows.filter(p => subsequence(query, p.name)).sort((a, b) => Number(b.name.toLowerCase().startsWith(query)) - Number(a.name.toLowerCase().startsWith(query)))
      .slice(0, 6).map(p => `${head} ${p.name}`);
  }
  return ['settings', 'open', 'proj', 'habit', 'todo', 'next', 'note', 'focus'].filter(c => subsequence(text.toLowerCase(), c)).slice(0, 6);
}
