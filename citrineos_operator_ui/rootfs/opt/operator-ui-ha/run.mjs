// Launcher for the CitrineOS Operator UI App.
// Validates the options, drops root, starts the upstream Next.js server on
// loopback and the Ingress proxy on 8099. Exits non-zero if either stops.
import fs from 'node:fs';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createProxy} from './proxy.mjs';

const OPTIONS = process.env.OPERATOR_UI_OPTIONS || '/data/options.json';
// OPERATOR_UI_ROOT is for local tests; the image keeps the standalone build in /app.
const ROOT = process.env.OPERATOR_UI_ROOT || '/app';
const SERVER = `${ROOT}/apps/operator-ui/server.js`;
const PUBLIC = `${ROOT}/apps/operator-ui/public`;
const NEXT_PORT = 3000;
const INGRESS_PORT = 8099;
const UID = 1001;

export function validate(o) {
  if (!o || typeof o !== 'object') throw new Error('No options');
  if (!/^http:\/\/[a-z0-9][a-z0-9.-]{0,252}:[0-9]{2,5}$/.test(o.gateway_url || ''))
    throw new Error('gateway_url must be http://<CitrineOS server host>:8080 (the lab gateway)');
  if (!/^[a-f0-9]{64}$/.test(o.operator_token || ''))
    throw new Error('operator_token must be the server\'s 64-hex operator_token');
  if (o.commands_enabled !== undefined && typeof o.commands_enabled !== 'boolean')
    throw new Error('commands_enabled must be true or false');
  return {gatewayUrl: o.gateway_url, token: o.operator_token, commands: o.commands_enabled === true};
}

export async function main() {
  let config;
  try {
    config = validate(JSON.parse(fs.readFileSync(OPTIONS, 'utf8')));
  } catch (e) {
    console.error(`Operator UI not started: ${e.message}`);
    process.exit(1);
  }
  if (process.getuid && process.getuid() === 0) {
    process.setgid(UID);
    process.setuid(UID);
  }
  const next = spawn(process.execPath, ['--max-old-space-size=256', SERVER], {
    stdio: 'inherit',
    env: {...process.env, NODE_ENV: 'production', PORT: String(NEXT_PORT), HOSTNAME: '127.0.0.1',
      NEXT_TELEMETRY_DISABLED: '1', NEXTAUTH_SECRET: crypto.randomUUID()},
  });
  const publicNames = fs.existsSync(PUBLIC) ? fs.readdirSync(PUBLIC) : [];
  const proxy = createProxy({...config, nextPort: NEXT_PORT, publicNames,
    peer: process.env.OPERATOR_UI_TRUSTED_PEER || '172.30.32.2'});
  proxy.listen(INGRESS_PORT, '0.0.0.0', () =>
    console.log(`Operator UI ready on Ingress; read-only GraphQL; commands ${config.commands ? 'enabled' : 'disabled'}.`));
  let stopping = false;
  const stop = () => {
    stopping = true;
    proxy.close();
    next.kill('SIGTERM');
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
  next.on('exit', (code) => {
    proxy.close();
    process.exit(stopping ? 0 : code || 1);
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
