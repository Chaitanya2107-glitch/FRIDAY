/** Display-only presence estimates. Unknown or unavailable observations never imply a location. */
export const presenceLabels = {
  at_desk: 'At desk', on_phone: 'On phone', in_class: 'In class', commuting: 'Commuting',
  at_college_free: 'College · free', at_home: 'At home', away: 'Away',
  winding_down: 'Winding down', asleep: 'Asleep',
} as const;

export interface PresenceSummary {
  state: keyof typeof presenceLabels;
  reason: string;
  confidence: number;
  since: number;
}

export function readPresence(value: unknown): PresenceSummary | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return;
  const row = value as Record<string, unknown>;
  if (row.data_available === false || typeof row.state !== 'string' || !Object.hasOwn(presenceLabels, row.state)
    || typeof row.reason !== 'string' || row.reason.length > 400
    || typeof row.confidence !== 'number' || !Number.isFinite(row.confidence) || row.confidence < 0 || row.confidence > 1
    || typeof row.since !== 'number' || !Number.isFinite(row.since) || row.since < 0) return;
  return { state: row.state as PresenceSummary['state'], reason: row.reason.replace(/[\u0000-\u001f\u007f]/g, ' ').trim(),
    confidence: row.confidence, since: row.since };
}

export function presenceText(value: unknown, stale = false) {
  const state = readPresence(value);
  if (!state) return { label: 'Presence unavailable', confidence: '', detail: 'No recent presence estimate is available.', available: false };
  const confidence = `${Math.round(state.confidence * 100)}% confidence`;
  return { label: `${stale ? 'Last known · ' : ''}${presenceLabels[state.state]}`, confidence,
    detail: `${stale ? 'Last known estimate. ' : ''}${state.reason || 'Estimated from the available signals.'}`, available: true };
}
