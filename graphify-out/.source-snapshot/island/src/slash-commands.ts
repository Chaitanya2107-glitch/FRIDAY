import type { Manifest, Suggestion, Tab } from './types.ts';

interface SlashCommand { name: string; detail: string; command: string; argument?: string; required?: boolean; view?: Tab }
export type SlashRuntime = 'full' | 'standalone' | 'offline';
const commands: SlashCommand[] = [
  { name: 'help', detail: 'Show all commands', command: '' },
  { name: 'status', detail: 'FRIDAY status and controls', command: '', view: 'friday' },
  { name: 'history', detail: 'Last three exchanges', command: '', view: 'friday' },
  { name: 'settings', detail: 'Island settings', command: '', view: 'settings' },
  { name: 'projects', detail: 'Your project folders', command: '', view: 'projects' },
  { name: 'plugins', detail: 'Live schedule, habits and todos', command: '', view: 'plugins' },
  { name: 'open', detail: 'Open an app, folder or website', command: '\\o {args}', argument: 'name or URL', required: true },
  { name: 'proj', detail: 'Open a saved project', command: 'proj {args}', argument: 'project name', required: true },
  { name: 'resume', detail: 'Resume a FRIDAY project', command: 'resume {args}', argument: 'project name', required: true },
  { name: 'next', detail: 'Next class from your timetable', command: 'next' },
  { name: 'schedule', detail: 'Today’s classes', command: 'what classes do I have today' },
  { name: 'college', detail: 'Open College schedules editor', command: 'open college schedules' },
  { name: 'habit', detail: 'List, add, check or undo a habit', command: 'habit {args}', argument: 'action and habit' },
  { name: 'todo', detail: 'List, add or complete a todo', command: 'todo {args}', argument: 'action and todo' },
  { name: 'note', detail: 'Save a note', command: 'note {args}', argument: 'text', required: true },
  { name: 'notes', detail: 'Read your notes', command: 'read my notes' },
  { name: 'remind', detail: 'Set a reminder', command: 'remind me {args}', argument: 'when and what', required: true },
  { name: 'reminders', detail: 'List your reminders', command: 'list reminders' },
  { name: 'due', detail: 'Your saved deadlines', command: "what's due" },
  { name: 'find', detail: 'Search your indexed files', command: '\\f {args}', argument: 'query', required: true },
  { name: 'open-file', detail: 'Open a numbered file search result', command: 'open {args}', argument: 'result number', required: true },
  { name: 'ask-files', detail: 'Ask a question about your files', command: '\\d {args}', argument: 'question', required: true },
  { name: 'browser', detail: 'Browser task, help, status, yes or stop', command: '\\b {args}', argument: 'task or control' },
  { name: 'research', detail: 'Research a subject', command: 'research {args}', argument: 'subject', required: true },
  { name: 'copy', detail: 'Copy text to the clipboard', command: 'copy {args} to clipboard', argument: 'text', required: true },
  { name: 'type', detail: 'Type into the original app', command: 'type {args}', argument: 'exact text', required: true },
  { name: 'press', detail: 'Press keys through FRIDAY’s confirmation flow', command: 'press {args}', argument: 'keys', required: true },
  { name: 'battery', detail: 'Battery status', command: 'battery' },
  { name: 'cpu', detail: 'CPU usage', command: 'cpu usage' },
  { name: 'ram', detail: 'Memory usage', command: "what's using my ram" },
  { name: 'time', detail: 'Current time', command: 'what time is it' },
  { name: 'date', detail: 'Today’s date', command: "what's the date today" },
  { name: 'volume', detail: 'Set volume', command: 'volume {args}', argument: '0–100', required: true },
  { name: 'brightness', detail: 'Set brightness', command: 'brightness {args}', argument: '0–100 or max', required: true },
  { name: 'mute', detail: 'Mute sound', command: 'mute' },
  { name: 'unmute', detail: 'Unmute sound', command: 'unmute' },
  { name: 'play', detail: 'Play music or a song', command: 'play {args}', argument: 'song or music' },
  { name: 'pause', detail: 'Pause playback', command: 'pause' },
  { name: 'next-song', detail: 'Next song', command: 'next song' },
  { name: 'previous-song', detail: 'Previous song', command: 'previous song' },
  { name: 'briefing', detail: 'Daily briefing', command: 'brief me' },
  { name: 'memory', detail: 'What FRIDAY remembers', command: 'what do you remember about me' },
  { name: 'remember', detail: 'Remember a fact', command: 'remember that {args}', argument: 'fact', required: true },
  { name: 'routines', detail: 'List saved routines', command: 'list my routines' },
  { name: 'modes', detail: 'List saved modes', command: 'list my modes' },
  { name: 'screen', detail: 'Screen-awareness status', command: 'screen awareness status' },
  { name: 'phone', detail: 'Phone connection status', command: 'phone status' },
  { name: 'brain', detail: 'Memory and brain status', command: 'brain status' },
  { name: 'lock', detail: 'Lock the laptop', command: 'lock the laptop' },
  { name: 'sleep', detail: 'Sleep through the normal confirmation flow', command: 'put the laptop to sleep' },
  { name: 'shutdown', detail: 'Shut down now or after a delay', command: 'shut down the laptop', argument: 'minutes (optional)' },
  { name: 'restart', detail: 'Restart through the normal confirmation flow', command: 'restart the laptop' },
  { name: 'cancel', detail: 'Cancel a scheduled shutdown', command: 'cancel the shutdown' },
];

function catalog(manifests: Manifest[] = [], runtime: SlashRuntime = 'full'): SlashCommand[] {
  const entries: SlashCommand[] = [...commands, ...manifests.flatMap(plugin => plugin.commands.filter(name => !commands.some(item => item.name === name))
    .map(name => ({ name, detail: plugin.name, command: `${name} {args}`, argument: 'command options' })))];
  return entries.filter(item => runtime === 'full' || item.view || ['help', 'open', 'proj'].includes(item.name)
    || runtime === 'standalone' && manifests.some(plugin => plugin.commands.includes(item.name)));
}

export function slashSuggestions(text: string, manifests: Manifest[] = [], runtime: SlashRuntime = 'full'): Suggestion[] {
  const match = /^\/([a-z0-9_-]*)\s*$/i.exec(text.trimStart());
  if (!match) return [];
  return catalog(manifests, runtime).filter(item => item.name.startsWith(match[1].toLowerCase()))
    .map(item => ({ text: `/${item.name}${item.argument ? ' ' : ''}`, detail: `${item.detail}${item.argument ? ` · ${item.argument}` : ''}`, fill: true }));
}

export function resolveSlash(text: string, manifests: Manifest[] = [], runtime: SlashRuntime = 'full'): { text: string; view?: Tab; palette?: boolean } {
  if (!text.trimStart().startsWith('/')) return { text };
  const value = text.trimStart();
  const head = value.split(/\s+/, 1)[0];
  if (head === '/' || head.toLowerCase() === '/help') return { text: '', palette: true };
  const item = catalog(manifests).find(item => `/${item.name}` === head.toLowerCase());
  if (!item) throw Error('Unknown slash command. Type / to see the available commands.');
  if (!catalog(manifests, runtime).some(available => available.name === item.name))
    throw Error('This command needs the full FRIDAY backend. Start FRIDAY and try again.');
  const args = value.slice(head.length).replace(/^\s/, '');
  if (item.required && !args.trim()) throw Error(`Use /${item.name} <${item.argument}>.`);
  if (!item.argument && args.trim()) throw Error(`/${item.name} does not take arguments.`);
  if (item.name === 'shutdown' && args.trim()) {
    if (!/^\d{1,5}$/.test(args.trim())) throw Error('Use /shutdown or /shutdown <minutes>.');
    return { text: `shut down in ${args.trim()} minutes` };
  }
  if (item.name === 'open-file' && !/^\d+$/.test(args.trim())) throw Error('Use /open-file <result number>.');
  const expanded = item.command.replace('{args}', () => args || (item.name === 'play' ? 'music' : ''));
  return { text: args ? expanded : expanded.trim(), view: item.view };
}

export function isFileReference(text: string): boolean {
  return /^open\s+(?:(?:file|result|number|no\.?)\s*)?(?:\d+|it|that(?: one)?|this(?: one)?|(?:the )?(?:first|second|third|fourth|fifth|last|top)(?: (?:one|file|result))?|one|two|three|four|five)$/i.test(text.trim())
    || /^open\s+(?:the\s+)?folder\s+(?:of|for)\s+\S|^open\s+.+\s+in\s+(?:the\s+)?(?:folder|explorer|file explorer)$/i.test(text.trim());
}
