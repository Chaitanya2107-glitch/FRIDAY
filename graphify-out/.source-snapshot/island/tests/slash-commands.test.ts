import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { isFileReference, resolveSlash, slashSuggestions } from '../src/slash-commands.ts';

test('slash lists the complete catalog and selecting entries only fills the bar', () => {
  const all = slashSuggestions('/');
  assert.ok(all.length > 40);
  assert.ok(all.every(row => row.fill));
  assert.ok(all.some(row => row.text === '/next'));
  assert.ok(all.some(row => row.text === '/type '));
  assert.ok(all.every(row => !row.text.startsWith('/!') && !row.text.startsWith('/cc')));
  assert.deepEqual(slashSuggestions('/no'), [all.find(row => row.text === '/note '), all.find(row => row.text === '/notes')]);
  assert.deepEqual(slashSuggestions('/note hello'), []);
});

test('slash aliases reuse existing routes, preserve exact text and validate arguments', () => {
  assert.deepEqual(resolveSlash('/help'), { text: '', palette: true });
  assert.equal(resolveSlash('/type hello  world\nnext line').text, 'type hello  world\nnext line');
  const literal = " price $& $' $` $$  \n";
  assert.equal(resolveSlash('/type ' + literal).text, 'type ' + literal);
  assert.equal(resolveSlash('/find budget').text, '\\f budget');
  assert.equal(resolveSlash('/copy Keep CAPS').text, 'copy Keep CAPS to clipboard');
  assert.ok(!slashSuggestions('/computer').length);
  assert.equal(resolveSlash('/next').text, 'next');
  assert.equal(resolveSlash('/shutdown 30').text, 'shut down in 30 minutes');
  assert.equal(resolveSlash('/settings').view, 'settings');
  for (const text of ['/open', '/open-file chrome', '/shutdown nope', '/cc ctrl+s', '/unknown']) assert.throws(() => resolveSlash(text));
  assert.ok(isFileReference('open 1'));
  assert.ok(isFileReference('open the second one'));
  assert.ok(isFileReference('open it'));
  assert.ok(isFileReference('open folder of 1'));
  assert.ok(isFileReference('open 2 in folder'));
  assert.equal(isFileReference('open Calculator'), false);
});

test('slash suggestions and execution respect the connected runtime', () => {
  const manifests = [{ id: 'college', name: 'College', version: 1, widget: true, commands: ['next'] }];
  const offline = slashSuggestions('/', manifests, 'offline');
  assert.ok(offline.some(row => row.text === '/open '));
  assert.ok(offline.some(row => row.text === '/settings'));
  assert.ok(!offline.some(row => row.text === '/next' || row.text === '/shutdown '));
  const standalone = slashSuggestions('/', manifests, 'standalone');
  assert.ok(standalone.some(row => row.text === '/next'));
  assert.ok(!standalone.some(row => row.text === '/note '));
  assert.deepEqual(slashSuggestions('  /NO', [], 'full').map(row => row.text), ['/note ', '/notes']);
  assert.equal(resolveSlash('/open Calculator', [], 'offline').text, '\\o Calculator');
  assert.equal(resolveSlash('/next', manifests, 'standalone').text, 'next');
  assert.throws(() => resolveSlash('/note hello', [], 'standalone'), /Start FRIDAY/);
  assert.throws(() => resolveSlash('/shutdown', [], 'offline'), /Start FRIDAY/);
});
