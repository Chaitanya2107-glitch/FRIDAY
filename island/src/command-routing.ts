export function nativeCommand(text: string, integrated: boolean, fromSlash: boolean): boolean {
  const value = text.trim();
  if (!/^(?:open|proj|settings)(?:\s|$)/i.test(value)) return false;
  if (!integrated) return true;
  return fromSlash || /^proj(?:\s|$)/i.test(value) || value.toLowerCase() === 'settings';
}
