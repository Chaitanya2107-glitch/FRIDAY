/** Snippets travel through authenticated local HTTP, never through the event bus. */
export async function searchCardBody(owner: string, payload: Record<string, unknown>,
  request: (path: string) => Promise<Record<string, unknown>>): Promise<string | undefined> {
  if (owner !== 'semantic_search' || typeof payload.content_ref !== 'string'
      || !/^[a-f0-9]{32}$/.test(payload.content_ref)) return;
  const start = payload.result_start, count = payload.result_count;
  if (typeof start !== 'number' || !Number.isInteger(start) || start < 0 || start > 4
      || typeof count !== 'number' || !Number.isInteger(count) || count < 1 || count > 5) return;
  const result = await request(`${owner}/results?ref=${payload.content_ref}&start=${start}&count=${count}`);
  return typeof result.body === 'string' && result.body.length <= 4000 ? result.body : undefined;
}
