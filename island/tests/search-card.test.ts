import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { searchCardBody } from '../src/search-card.ts';

test('search snippets use a private route with only an opaque reference', async () => {
  const payload = { body: 'carnot.pdf', content_ref: 'a'.repeat(32), result_start: 0, result_count: 3 };
  let path = '';
  const body = await searchCardBody('semantic_search', payload, async route => { path = route; return { body: 'Private snippet' }; });
  assert.equal(path, `semantic_search/results?ref=${'a'.repeat(32)}&start=0&count=3`);
  assert.equal(body, 'Private snippet');
  assert.equal(payload.body, 'carnot.pdf');
  assert.equal(JSON.stringify(payload).includes('Private snippet'), false);
});

test('other plugins and malformed references cannot hydrate a search card', async () => {
  const request = async () => { assert.fail('Unexpected private request'); };
  const valid = { content_ref: 'a'.repeat(32), result_start: 0, result_count: 3 };
  for (const payload of [{ ...valid, content_ref: '../secrets' }, { ...valid, result_count: 10 }, { ...valid, result_start: -1 }])
    assert.equal(await searchCardBody('semantic_search', payload, request), undefined);
  assert.equal(await searchCardBody('todo', valid, request), undefined);
});
