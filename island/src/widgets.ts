import { icon } from './icons.ts';
import { element as el } from './state.ts';
import type { Connection } from './connection';
import type { CommandResult, Manifest, PluginAction, Widget, WidgetAction } from './types';

const record = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const text = (v: unknown, max: number): v is string => typeof v === 'string' && v.length <= max;
const actionName = (v: unknown): v is string => text(v, 32) && /^[a-z_]+$/.test(v);

/** Read only bounded, literal data. Widget markup/code is never accepted. */
export function readWidget(value: unknown): Widget {
  if (!record(value) || !text(value.title, 80) || !text(value.text, 500)) throw new Error('Invalid widget');
  const result: Widget = { title: value.title, text: value.text };
  if (value.items !== undefined) {
    if (!Array.isArray(value.items) || value.items.length > 6) throw new Error('Invalid widget rows');
    result.items = value.items.map(row => {
      if (!record(row) || !text(row.id, 64) || !text(row.label, 160) || !text(row.detail, 200)) throw new Error('Invalid widget row');
      let action: WidgetAction | undefined;
      if (row.action !== undefined) {
        const a = row.action;
        if (!record(a) || !text(a.label, 40) || !actionName(a.action)
          || (a.item !== undefined && !text(a.item, 64)) || (a.value !== undefined && !text(a.value, 160))
          || (a.revision !== undefined && a.revision !== null && (typeof a.revision !== 'number' || !Number.isFinite(a.revision) || a.revision < 0))
          || (a.disabled !== undefined && typeof a.disabled !== 'boolean')) throw new Error('Invalid widget action');
        action = { label: a.label, action: a.action, item: a.item as string | undefined, value: a.value as string | undefined,
          revision: a.revision as number | null | undefined, disabled: a.disabled === true };
      }
      return { id: row.id, label: row.label, detail: row.detail, action };
    });
  }
  if (value.input !== undefined) {
    const input = value.input;
    if (!record(input) || !text(input.label, 80) || !text(input.placeholder, 160) || !actionName(input.action)
      || typeof input.max_length !== 'number' || !Number.isInteger(input.max_length) || input.max_length < 1 || input.max_length > 160) throw new Error('Invalid widget input');
    result.input = { label: input.label, placeholder: input.placeholder, action: input.action, max_length: input.max_length };
  }
  return result;
}

interface Card { id: string; node: HTMLElement; summary: HTMLElement; rows: HTMLElement; form: HTMLFormElement; input: HTMLInputElement; submit: HTMLButtonElement; inputAction?: string; busy: boolean; serial: number }

export class PluginWidgets {
  private cards: Card[] = [];
  private drafts = new Map<string, string>();
  private timer?: ReturnType<typeof setInterval>;
  private host: HTMLElement;
  private connection: () => Connection;
  private report: (result: CommandResult) => void;
  constructor(host: HTMLElement, connection: () => Connection, report: (result: CommandResult) => void) {
    this.host = host; this.connection = connection; this.report = report;
  }

  hide() {
    clearInterval(this.timer);
    for (const card of this.cards) { this.drafts.set(card.id, card.input.value); card.serial++; }
    this.cards = [];
  }

  show(manifests: Manifest[]) {
    for (const manifest of manifests.filter(m => m.widget)) {
      const node = el('article', 'widget'); node.dataset.plugin = manifest.id;
      const heading = el('div', 'widget-heading');
      const refresh = el('button', 'icon-button widget-refresh'); refresh.append(icon('refresh'));
      refresh.title = `Refresh ${manifest.name}`; refresh.setAttribute('aria-label', refresh.title);
      refresh.onpointerdown = event => event.preventDefault();
      heading.append(el('strong', '', manifest.name), refresh);
      const summary = el('p', 'muted', 'Loading…'); const rows = el('div', 'widget-rows');
      const form = el('form', 'widget-add'); form.hidden = true;
      const input = el('input'); input.autocomplete = 'off'; input.maxLength = 160;
      input.value = this.drafts.get(manifest.id) ?? '';
      const submit = el('button', 'widget-submit', 'Add'); submit.type = 'submit';
      form.append(input, submit); node.append(heading, summary, rows, form); this.host.append(node);
      const card: Card = { id: manifest.id, node, summary, rows, form, input, submit, busy: false, serial: 0 };
      this.cards.push(card);
      refresh.onclick = () => { if (!card.busy) void this.refreshCard(card); };
      form.onsubmit = event => {
        event.preventDefault();
        if (!card.inputAction || !input.value.trim() || card.busy) return;
        void this.act(card, { action: card.inputAction, value: input.value }, true);
      };
    }
    void this.refresh();
    this.timer = setInterval(() => void this.refresh(), 15000);
  }

  async refresh() { await Promise.all(this.cards.filter(c => !c.busy).map(c => this.refreshCard(c))); }

  private async refreshCard(card: Card) {
    const serial = ++card.serial;
    try {
      const data = await this.connection().widget(card.id);
      if (!card.node.isConnected || serial !== card.serial) return;
      card.summary.textContent = data.text;
      card.rows.replaceChildren();
      for (const item of data.items ?? []) {
        const row = el('div', 'widget-row');
        const label = el('div', 'widget-label'); label.append(el('span', '', item.label), el('small', 'muted', item.detail));
        row.append(label);
        if (item.action) {
          const action = item.action;
          const button = el('button', 'widget-action', action.label);
          button.title = `${action.label} ${item.label}`; button.setAttribute('aria-label', button.title);
          button.disabled = action.disabled === true || card.busy;
          button.onpointerdown = event => event.preventDefault();
          button.onclick = () => void this.act(card, action);
          row.append(button);
        }
        card.rows.append(row);
      }
      card.form.hidden = !data.input;
      card.inputAction = data.input?.action;
      if (data.input) {
        card.input.setAttribute('aria-label', data.input.label);
        card.input.placeholder = data.input.placeholder; card.input.maxLength = data.input.max_length;
        card.submit.setAttribute('aria-label', `Add to ${data.title}`);
      }
    } catch {
      if (card.node.isConnected && serial === card.serial) card.summary.textContent = 'Widget unavailable. Refresh to try again.';
    }
  }

  private async act(card: Card, action: PluginAction, clearDraft = false) {
    if (card.busy) return;
    card.busy = true; card.serial++; card.input.readOnly = true; card.submit.disabled = true;
    card.rows.querySelectorAll('button').forEach(button => button.disabled = true);
    try {
      const result = await this.connection().pluginAction(card.id, action);
      if (result.ok && clearDraft) { card.input.value = ''; this.drafts.delete(card.id); }
      this.report(result);
    } catch (error) { this.report({ ok: false, text: String(error) }); }
    finally {
      card.busy = false; card.input.readOnly = false; card.submit.disabled = false;
      if (this.cards.includes(card)) await this.refreshCard(card);
    }
  }
}
