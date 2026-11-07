export interface CapsuleReply {
  text: string;
  kind: 'reply' | 'reminder' | 'question' | 'work';
  title?: string;
  private?: boolean;
  bad?: boolean;
  awaiting?: boolean;
  pending?: boolean;
  buttons?: [string, string][];
  pluginId?: string;
  ttlMs?: number;
  swatch?: string;
  pluginActions?: { label: string; run: () => Promise<{ ok: boolean; text: string }> }[];
}

export function replyDuration(reply: CapsuleReply): number {
  if (reply.ttlMs !== undefined) return reply.ttlMs;
  if (reply.awaiting || reply.pending) return 0;
  return reply.kind === 'reminder' || reply.kind === 'work' || reply.bad
    || reply.text.length > 160 || reply.text.includes('\n') ? 30000 : 5000;
}
