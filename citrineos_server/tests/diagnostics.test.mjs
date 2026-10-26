import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {HEAP_LIMIT_MB, memoryLine, nodeOptions, pruneSnapshots, rssMb} from '../rootfs/diagnostics.mjs';

test('the heap limit is unchanged and a snapshot is written near it', () => {
  assert.equal(nodeOptions('/data/heap'),
    `--max-old-space-size=${HEAP_LIMIT_MB} --heapsnapshot-near-heap-limit=1 --diagnostic-dir=/data/heap`);
  assert.equal(HEAP_LIMIT_MB, 768);
});

test('only the newest snapshot is kept; other files are left alone', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'heap-'));
  try {
    for (const [n, age] of [['a.heapsnapshot', 3], ['b.heapsnapshot', 1], ['c.heapsnapshot', 2], ['notes.txt', 9]]) {
      fs.writeFileSync(path.join(dir, n), '');
      const t = new Date(Date.now() - age * 60000);
      fs.utimesSync(path.join(dir, n), t, t);
    }
    assert.deepEqual(pruneSnapshots(dir, 1).sort(), ['a.heapsnapshot', 'c.heapsnapshot']);
    assert.deepEqual(fs.readdirSync(dir).sort(), ['b.heapsnapshot', 'notes.txt']);
    assert.deepEqual(pruneSnapshots(path.join(dir, 'missing')), []);
  } finally { fs.rmSync(dir, {recursive: true}); }
});

test('RSS comes from /proc status; anything unreadable is unavailable, never 0', () => {
  const status = 'Name:\tnode\nVmRSS:\t  321536 kB\nThreads:\t11\n';
  assert.equal(rssMb(47, () => status), 314);
  assert.equal(rssMb(47, () => 'Name:\tnode\n'), null);
  assert.equal(rssMb(47, () => { throw new Error('gone'); }), null);
  assert.equal(rssMb(undefined, () => status), null);
  assert.equal(rssMb(process.pid) > 0, true);
});

test('the memory line is timestamped and says unavailable for a missing value', () => {
  const now = new Date('2026-10-26T03:00:00Z');
  assert.equal(memoryLine(now, 314, 61),
    'Memory 2026-10-26T03:00:00.000Z: CitrineOS 314 MB RSS (heap limit 768 MB), gateway 61 MB RSS.');
  assert.match(memoryLine(now, null, 61), /CitrineOS unavailable RSS/);
});
