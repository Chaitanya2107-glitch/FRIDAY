export function matchesDismiss(event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'altKey' | 'shiftKey' | 'metaKey'>, value = 'Escape') {
  const parts = value.toLowerCase().split('+').map(part => part.trim());
  const key = parts.at(-1);
  return (key === 'space' ? event.key === ' ' : event.key.toLowerCase() === key)
    && event.ctrlKey === (parts.includes('ctrl') || parts.includes('control'))
    && event.altKey === parts.includes('alt') && event.shiftKey === parts.includes('shift')
    && event.metaKey === (parts.includes('win') || parts.includes('super'));
}
