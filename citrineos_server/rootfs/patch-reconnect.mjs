// Build-time patch to upstream CitrineOS v2.0.1 (#67): a station that
// reconnects while its old connection is still being closed lost its router
// bindings, so CitrineOS stored every station message but never answered it.
//
// WebsocketNetworkConnection runs the old socket's close handling
// (_handleWebsocketClose) without waiting for it: it removes the connection
// slot from the cache at once, then deregisters the station from the router,
// which reads and writes the database before it unbinds the station's headers
// bindings from the router's RabbitMQ queue. Upstream's ConnectedStationFilter
// admits the reconnect as soon as the slot is gone, and _onConnection only
// waits for a close it starts itself (a stale socket still in its map). So the
// new connection's registerConnection binds the same identifier while the old
// deregistration is still running, and the old unsubscribe then unbinds what
// the new connection bound (bindings are identical per identifier). The
// request binding can survive while the response binding is gone: commands
// to the station still work, but no CALLRESULT reaches it.
//
// The patch tracks each close per identifier and makes _onConnection wait
// until earlier closes of that identifier are finished before it checks for a
// stale socket, claims the slot and registers.
//
// The build fails unless the file is the exact upstream v2.0.1 build (or this
// patch's output), so a new upstream version cannot silently drop the patch.
// `--check` succeeds only for a patched file.
import crypto from 'node:crypto';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

export const TARGET='/usr/local/apps/citrineos/apps/ocpp-server/node_modules/@citrineos/ocpp/dist/src/transport/network-connection/websocket-network-connection.js';
export const UPSTREAM_SHA256='82e41b6e6381caa2c54c6cfca55dab290be6703be5f809959ea5cd96fb90d58d';
export const PATCHED_SHA256='584cdb24b41db08555acd1c19b4e3ac281fefb20d4f8f62759b2975f3cc2d841';
export const MARKER='ha-citrine patch (patch-reconnect.mjs)';

export const EDITS=[
  {
    name:'track closes',
    anchor:`    async _handleWebsocketClose(identifier, code, reason, connLogger = this._connLogger(identifier)) {
        this._closeHandlers.delete(identifier);
`,
    replacement:`    // ha-citrine patch (patch-reconnect.mjs): each close is tracked per
    // identifier until it has deregistered the connection from the router.
    _handleWebsocketClose(identifier, code, reason, connLogger) {
        const closing = this._haCloseConnection(identifier, code, reason, connLogger);
        this._haClosing ??= new Map();
        const settled = Promise.allSettled([this._haClosing.get(identifier), closing]).then(() => {
            if (this._haClosing.get(identifier) === settled)
                this._haClosing.delete(identifier);
        });
        this._haClosing.set(identifier, settled);
        return closing;
    }
    async _haCloseConnection(identifier, code, reason, connLogger = this._connLogger(identifier)) {
        this._closeHandlers.delete(identifier);
`,
  },
  {
    name:'wait before reconnect',
    anchor:`            const staleWs = this._identifierConnections.get(identifier);
            if (staleWs) {
`,
    replacement:`            // ha-citrine patch (patch-reconnect.mjs): an earlier connection of this
            // identifier that is still closing must finish deregistering first, or it
            // unbinds the router bindings this connection is about to add.
            while (this._haClosing?.has(identifier)) {
                await this._haClosing.get(identifier);
            }
            const staleWs = this._identifierConnections.get(identifier);
            if (staleWs) {
`,
  },
];

export function sha256(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}
// Exact text edits; each anchor must occur exactly once.
export function applyEdits(text) {
  if(text.includes(MARKER))throw new Error('websocket-network-connection.js is already partly patched');
  for(const {name,anchor} of EDITS) {
    const count=text.split(anchor).length-1;
    if(count!==1)throw new Error(`Anchor "${name}" found ${count} times, expected exactly once`);
  }
  return EDITS.reduce((out,{anchor,replacement})=>out.replace(anchor,()=>replacement),text);
}
// Returns the patched text; a file already patched by this version is unchanged.
export function patch(text) {
  const digest=sha256(text);
  if(digest===PATCHED_SHA256)return text;
  if(digest!==UPSTREAM_SHA256)
    throw new Error('websocket-network-connection.js is not the pinned CitrineOS v2.0.1 build');
  const patched=applyEdits(text);
  if(sha256(patched)!==PATCHED_SHA256)throw new Error('Patched file does not match the expected result');
  return patched;
}
export function main(args=process.argv.slice(2)) {
  const check=args.includes('--check');
  const path=args.find(a=>a!=='--check')??TARGET;
  const text=fs.readFileSync(path,'utf8');
  if(check) {
    if(sha256(text)!==PATCHED_SHA256)throw new Error(`${path} is not patched`);
    console.log(`${path} is patched (reconnect race, #67)`);
    return;
  }
  const patched=patch(text);
  if(patched===text){console.log(`${path} is already patched`);return;}
  fs.writeFileSync(path,patched);
  const syntax=spawnSync(process.execPath,['--check',path],{encoding:'utf8'});
  if(syntax.status!==0) {
    fs.writeFileSync(path,text);
    throw new Error(`Patched file does not parse: ${syntax.stderr.trim()}`);
  }
  console.log(`patched ${path}: a reconnect waits for the old connection's close (#67)`);
}
if(process.argv[1]===fileURLToPath(import.meta.url)) {
  try {main();}
  catch(error) {console.error(`patch-reconnect: ${error.message}`);process.exit(1);}
}
