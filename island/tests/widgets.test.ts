import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { readWidget } from '../src/widgets.ts';

test('widgets keep metadata literal and reject unbounded or malformed actions', () => {
  const data = { title: 'Todo', text: 'One task', items: [{ id: '7', label: '<img src=x>', detail: 'Active',
    action: { label: 'Done', action: 'complete', item: '7', revision: 123.5 } }],
    input: { label: 'New todo', placeholder: 'Add', action: 'add', max_length: 160 } };
  assert.equal(readWidget(data).items![0].label, '<img src=x>');
  assert.equal(readWidget(data).items![0].action!.revision, 123.5);
  for (const action of [ { ...data.items[0].action, revision: '123' }, { ...data.items[0].action, revision: Infinity },
    { ...data.items[0].action, action: 'shell;run' }, { ...data.items[0].action, disabled: 'false' } ]) {
    assert.throws(() => readWidget({ ...data, items: [{ ...data.items[0], action }] }));
  }
  assert.throws(() => readWidget({ ...data, items: Array(7).fill(data.items[0]) }));
  assert.throws(() => readWidget({ ...data, input: { ...data.input, max_length: 4000 } }));
});
