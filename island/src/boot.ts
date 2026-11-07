import './boot.css';
import { call, native, on } from './native';
import type { Config } from './types';

export class BootAnimation {
  private epoch = '';
  private finish?: () => void;
  constructor(private surface: HTMLElement, private config: () => Config, private reduced: () => boolean,
              private updated: (config: Config) => void) {}
  async start() { await on('boot-skip', () => this.finish?.()); }
  receive(frame: Record<string, unknown>) {
    if (frame.type !== 'runtime_state' || frame.backend !== true || typeof frame.epoch !== 'string' || frame.epoch === this.epoch) return;
    this.epoch = frame.epoch;
    void this.play(frame.epoch);
  }
  private async play(epoch: string) {
    if (!native) return;
    try {
      this.finish?.();
      const claimed = await call<boolean>('boot_claim', { epoch });
      this.updated(await call<Config>('get_config'));
      if (!claimed || this.config().island?.boot_animation === false) { await call('boot_done'); return; }
      const reduced = this.reduced() || matchMedia('(prefers-reduced-motion: reduce)').matches;
      const ring = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); ring.classList.add('boot-ring');
      ring.innerHTML = '<rect x="1" y="1" width="calc(100% - 2px)" height="calc(100% - 2px)" rx="24" pathLength="100"/>';
      const caption = document.createElement('span'); caption.className = 'boot-caption';
      caption.textContent = `Online and ready${this.config().user_name ? `, ${this.config().user_name}` : ''}`;
      caption.setAttribute('role', 'status');
      this.surface.append(ring, caption);
      this.surface.classList.add('booting'); this.surface.classList.toggle('boot-reduced', reduced);
      let timer: ReturnType<typeof setTimeout>;
      const skip = (event: Event) => { event.preventDefault(); event.stopImmediatePropagation(); finish(); };
      const finish = () => {
        if (this.finish !== finish) return;
        clearTimeout(timer); this.finish = undefined;
        document.removeEventListener('pointerdown', skip, true); document.removeEventListener('keydown', skip, true);
        this.surface.classList.remove('booting', 'boot-reduced'); ring.remove(); caption.remove();
        void call('boot_done');
      };
      this.finish = finish;
      document.addEventListener('pointerdown', skip, true); document.addEventListener('keydown', skip, true);
      timer = setTimeout(finish, 2100);
    } catch { await call('boot_done').catch(() => {}); }
  }
}
