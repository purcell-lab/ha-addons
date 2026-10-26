// Memory diagnostics for the upstream server (ha-addons#80): a heap snapshot
// when it nears its heap limit, and one memory line a minute, so a crash
// carries its own evidence.
import fs from 'node:fs';
import path from 'node:path';

export const HEAP_LIMIT_MB = 768;
export const HEAP_DIR = '/data/heap';
// Snapshots kept across restarts: each one is about the heap's size or more.
export const SNAPSHOTS_KEPT = 1;
export const MEMORY_LOG_MS = 60000;

export const nodeOptions = (dir = HEAP_DIR) =>
  `--max-old-space-size=${HEAP_LIMIT_MB} --heapsnapshot-near-heap-limit=1 --diagnostic-dir=${dir}`;

// Removes all but the newest `keep` snapshots in dir; returns the names removed.
export function pruneSnapshots(dir, keep = SNAPSHOTS_KEPT) {
  let names;
  try { names = fs.readdirSync(dir).filter(n => n.endsWith('.heapsnapshot')); } catch { return []; }
  const byAge = names.map(n => ({n, t: fs.statSync(path.join(dir, n)).mtimeMs})).sort((a, b) => b.t - a.t);
  const removed = byAge.slice(keep).map(({n}) => n);
  for (const n of removed) fs.rmSync(path.join(dir, n), {force: true});
  return removed;
}

// Resident set size in MB from /proc/<pid>/status, or null when unreadable.
export function rssMb(pid, read = p => fs.readFileSync(p, 'utf8')) {
  if (!Number.isInteger(pid) || pid <= 0) return null;
  try {
    const m = /^VmRSS:\s+(\d+)\s+kB$/m.exec(read(`/proc/${pid}/status`));
    return m ? Math.round(Number(m[1]) / 1024) : null;
  } catch { return null; }
}

const mb = v => v === null ? 'unavailable' : `${v} MB`;
export const memoryLine = (now, upstream, gateway) =>
  `Memory ${now.toISOString()}: CitrineOS ${mb(upstream)} RSS (heap limit ${HEAP_LIMIT_MB} MB), gateway ${mb(gateway)} RSS.`;
