import { icon } from './icons';
import { presenceText } from './presence';

/** A small passive companion label; it cannot start scenes or change Mochi's mood. */
export class PresenceDisplay {
  readonly node = document.createElement('span');
  private label = document.createElement('span');
  constructor(private surface: HTMLElement, private changed: () => void) {
    this.node.className = 'presence-chip'; this.node.hidden = true;
    this.node.setAttribute('role', 'status');
    this.node.append(icon('phone'), this.label);
  }
  update(raw?: unknown) {
    const view = presenceText(raw);
    this.node.hidden = !view.available;
    this.label.textContent = view.label;
    this.node.title = `${view.confidence}. ${view.detail}`;
    this.node.setAttribute('aria-label', `Presence estimate: ${view.label}. ${view.confidence}. ${view.detail}`);
    this.surface.dataset.presence = String(view.available);
    this.changed();
  }
}
