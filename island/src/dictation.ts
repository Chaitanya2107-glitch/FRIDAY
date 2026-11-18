/** Handy pastes only into the focused Island input; typing or leaving cancels auto-send. */
export class Dictation {
  private active = false;
  private changing = false;
  private generation = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private host: { control: (action: 'toggle' | 'cancel') => Promise<unknown>;
    prepare: () => Promise<void>; value: () => string; submit: (text: string) => Promise<void>;
    message: (text: string, bad?: boolean) => void };
  constructor(host: Dictation['host']) { this.host = host; }
  async toggle() {
    if (this.changing) return;
    this.changing = true;
    const generation = this.generation;
    try {
      if (!this.active) await this.host.prepare();
      if (generation !== this.generation) return;
      await this.host.control('toggle');
      if (generation !== this.generation) {
        await this.host.control('cancel').catch(() => {});
        return;
      }
      this.active = true;
      this.host.message('Handy dictation · Ctrl+Alt+F to finish; Esc to cancel.');
    } catch (error) {
      if (generation === this.generation) this.host.message(String(error), true);
    } finally {
      this.changing = false;
    }
  }
  input(pasted: boolean) {
    if (!pasted) { this.cancel(); return; }
    clearTimeout(this.timer);
    if (this.active && this.host.value().trim()) this.timer = setTimeout(() => {
      this.active = false; void this.host.submit(this.host.value());
    }, 400);
  }
  cancel() {
    clearTimeout(this.timer);
    this.generation++;
    if (!this.active) return;
    this.active = false;
    void this.host.control('cancel').catch(() => {});
  }
  key(key: string, ctrl: boolean) {
    if (!['Control', 'Shift', 'Alt', 'Meta'].includes(key) && !(ctrl && key.toLowerCase() === 'v')) this.cancel();
  }
}
