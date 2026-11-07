/** Small local state model; scene names are always rendered as literal text. */
export class SceneState {
  name = '';
  id = '';
  revision = 0;

  reset() { this.name = ''; this.id = ''; this.revision++; }

  status(value: Record<string, unknown>) {
    this.set(value.active, value.scene_id);
  }

  event(event: Record<string, unknown>) {
    if (!['scene.started', 'scene.ended', 'scene.state'].includes(String(event.topic))) return false;
    if (!event.payload || typeof event.payload !== 'object' || Array.isArray(event.payload)) return false;
    const data = event.payload as Record<string, unknown>;
    if (event.topic === 'scene.ended') {
      if (typeof data.scene_id !== 'string' || !this.id || data.scene_id === this.id) this.reset();
    } else this.set(data.name, data.scene_id);
    return true;
  }

  private set(name: unknown, id: unknown) {
    if (name === null || name === undefined) { this.reset(); return; }
    if (typeof name !== 'string' || !name.trim() || name.length > 48 || /[\x00-\x1f]/.test(name)) return;
    this.name = name; this.id = typeof id === 'string' ? id : ''; this.revision++;
  }
}
