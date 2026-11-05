const paths: Record<string, string> = {
  pin: '<path d="m8 3 8 0-1 6 4 4v2H5v-2l4-4ZM12 15v7"/>',
  projects: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  settings: '<path d="m9 3-1 3-3 1v4l-2 1 2 2v4l3 1 1 2h6l1-2 3-1v-4l2-2-2-1V7l-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  folder: '<path d="M3 8V5a1 1 0 0 1 1-1h6l2 3h8a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/>',
  arrow: '<path d="M7 17 17 7M7 7h10v10"/>',
  app: '<rect x="3" y="3" width="18" height="18" rx="5"/><path d="M8 9h8M8 15h4"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6"/>',
  edit: '<path d="m4 16 12-12 4 4L8 20l-5 1ZM13 7l4 4"/>',
  up: '<path d="m6 14 6-6 6 6"/>',
  down: '<path d="m6 10 6 6 6-6"/>',
  grip: '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
  back: '<path d="m14 6-6 6 6 6"/>',
  power: '<path d="M12 3v9M6 6a9 9 0 1 0 12 0"/>',
  refresh: '<path d="M20 10a8 8 0 1 0-1 7M20 4v6h-6"/>',
  battery: '<rect x="2" y="6" width="18" height="12" rx="3"/><path d="M22 10v4"/>',
  music: '<path d="M9 18V5l11-2v13M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="3"/><ellipse cx="17" cy="16" rx="3" ry="3"/>',
  play: '<path d="m9 5 11 7-11 7Z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M9 5v14M16 5v14" stroke-width="3"/>',
  previous: '<path d="m18 5-10 7 10 7Z" fill="currentColor" stroke="none"/><path d="M5 5v14"/>',
  next: '<path d="m6 5 10 7-10 7Z" fill="currentColor" stroke="none"/><path d="M19 5v14"/>',
};
export function icon(name: string): SVGElement {
  const holder = document.createElement('span');
  // Markup comes exclusively from the fixed original icon dictionary above.
  holder.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] ?? paths.app}</svg>`;
  return holder.firstElementChild as SVGElement;
}

export function character(): HTMLElement {
  const orb = document.createElement('div');
  orb.className = 'character';
  orb.setAttribute('role', 'img');
  orb.setAttribute('aria-label', 'FRIDAY, an amber orb');
  orb.innerHTML = `<svg viewBox="0 0 64 64" aria-hidden="true">
    <defs><radialGradient id="orb-light" cx="38%" cy="28%" r="78%"><stop stop-color="var(--orb-highlight)"/><stop offset=".5" stop-color="var(--accent)"/><stop offset="1" stop-color="var(--orb-edge)"/></radialGradient></defs>
    <g class="orb-body"><path d="M8 36C6 20 15 9 30 8c16-2 28 9 27 25-1 16-11 23-25 23C18 57 9 51 8 36Z" fill="url(#orb-light)"/>
    <ellipse cx="23" cy="17" rx="8" ry="3" transform="rotate(-20 23 17)" fill="white" opacity=".24"/>
    <g class="eyes"><ellipse cx="25" cy="32" rx="2.4" ry="3.4"/><ellipse cx="41" cy="32" rx="2.4" ry="3.4"/></g>
    <ellipse cx="19" cy="38" rx="3.5" ry="1.5" fill="var(--orb-cheek)" opacity=".3"/><ellipse cx="47" cy="38" rx="3.5" ry="1.5" fill="var(--orb-cheek)" opacity=".3"/>
    </g></svg>`;
  return orb;
}
