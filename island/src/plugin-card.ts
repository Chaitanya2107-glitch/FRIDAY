/** Validate literal plugin cards before putting them in a transient surface. */
export interface PluginCard {
  owner: string; title: string; text: string; ttlMs: number; swatch?: string;
  actions: { id: string; label: string; payload: Record<string, unknown> }[];
}

export function pluginCard(event: Record<string, unknown>): PluginCard | null {
  const payload = event.payload;
  if (event.topic !== 'ui.card' || typeof event.plugin_id !== 'string' || !/^[a-z][a-z0-9_-]{0,63}$/.test(event.plugin_id)
    || !payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  const value = payload as Record<string, unknown>;
  if (typeof value.title !== 'string' || value.title.length > 120 || typeof value.body !== 'string' || value.body.length > 4000) return null;
  const actions: PluginCard['actions'] = [];
  for (const action of (Array.isArray(value.actions) ? value.actions : []).slice(0, 6)) {
    if (!action || typeof action !== 'object' || typeof action.id !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(action.id)
      || typeof action.label !== 'string' || action.label.length > 40) continue;
    const data = action.payload ?? {};
    if (typeof data !== 'object' || Array.isArray(data)) continue;
    actions.push({ id: action.id, label: action.label, payload: data });
  }
  const ttl = typeof value.ttl_s === 'number' && Number.isFinite(value.ttl_s) ? Math.max(1, Math.min(3600, value.ttl_s)) : 30;
  const swatch = event.plugin_id === 'smart_clipboard' && value.title === 'Clipboard · Color'
    ? value.body.match(/^#[a-fA-F0-9]{6}(?:[a-fA-F0-9]{2})?(?=\s|$)/)?.[0] : undefined;
  return { owner: event.plugin_id, title: value.title, text: value.body, actions, ttlMs: ttl * 1000, swatch };
}

/** Briefings belong in the existing expanded FRIDAY view. */
export function briefingCard(event: Record<string, unknown>): PluginCard | null {
  const card = pluginCard(event);
  return card?.owner === 'briefings' && card.text.split(/\r?\n/).length <= 6 ? card : null;
}
