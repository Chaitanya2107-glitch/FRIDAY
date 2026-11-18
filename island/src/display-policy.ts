import type { Mode } from './types';

export function displayMode(requested: Mode, suppressed: boolean): Mode {
  return suppressed ? 'hidden' : requested;
}

export function restoredMode(idle: string, sneak: boolean): Mode {
  return sneak || idle === 'hover' ? 'hidden' : 'rest';
}
