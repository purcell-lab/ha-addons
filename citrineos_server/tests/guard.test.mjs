import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {validateOptions, readOptions} from '../rootfs/guard.mjs';

test('only the exact disconnected configuration is accepted', () => {
  assert.doesNotThrow(() => validateOptions({mode: 'disconnected'}));
  for (const value of [null, [], {}, true, 'disconnected',
    {mode: 'enabled'}, {mode: 'disconnected', server: true},
    {mode: 'disconnected', password: 'SENTINEL_SECRET'}]) {
    assert.throws(() => validateOptions(value), /disconnected mode only/);
  }
});

test('missing options is safely disconnected; malformed options do not leak', () => {
  const dir = mkdtempSync(join(tmpdir(), 'citrine-options-'));
  try {
    const path = join(dir, 'options.json');
    assert.deepEqual(readOptions(path), {mode: 'disconnected'});
    writeFileSync(path, '{"password":"SENTINEL_SECRET",');
    assert.throws(() => readOptions(path), error =>
      error.message === 'Cannot read options; refusing startup.');
  } finally {
    rmSync(dir, {recursive: true});
  }
});
