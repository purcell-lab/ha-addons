// Packaging is intentionally inert. Changing options cannot unlock a server.
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

export function validateOptions(value) {
  if (!value || Array.isArray(value) || typeof value !== 'object' ||
      Object.keys(value).length !== 1 || value.mode !== 'disconnected') {
    throw new Error('Invalid options; this release supports disconnected mode only.');
  }
}

export function readOptions(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') return {mode: 'disconnected'};
    // Never include options, parsing fragments or environment values in logs.
    throw new Error('Cannot read options; refusing startup.');
  }
}

export function main() {
  try {
    validateOptions(readOptions('/data/options.json'));
    const lock = JSON.parse(readFileSync(
      new URL('./compatibility-lock.json', import.meta.url), 'utf8'));
    if (lock.assessment.status !== 'blocked' ||
        lock.assessment.runtime_activation_allowed !== false) {
      throw new Error('Unexpected compatibility lock; refusing startup.');
    }
  } catch (error) {
    console.error(error.message);
    process.exitCode = 78;
    return;
  }
  console.log('CitrineOS packaging ready; DISCONNECTED. No API, OCPP listener, database migration or broker connection is running.');
  console.log('Client compatibility BLOCKED. This App running is not server readiness. See DOCS.md.');
  const timer = setInterval(() => {}, 60_000);
  const stop = () => {
    clearInterval(timer);
    console.log('Disconnected package stopped.');
  };
  process.once('SIGTERM', stop);
  process.once('SIGINT', stop);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
