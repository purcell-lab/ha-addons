import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {EventEmitter} from 'node:events';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {patch,applyEdits,sha256,main,UPSTREAM_SHA256,PATCHED_SHA256,MARKER,EDITS,TARGET} from '../rootfs/patch-reconnect.mjs';

// The exact compiled file from the pinned image (both architectures share the layer).
const FIXTURE=new URL('./fixtures/websocket-network-connection.v2.0.1.js',import.meta.url);
const upstream=fs.readFileSync(FIXTURE,'utf8');
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'citrine-patch-'));
test.after(()=>fs.rmSync(tmp,{recursive:true,force:true}));

test('fixture is the pinned upstream build',()=>{
  assert.equal(sha256(upstream),UPSTREAM_SHA256);
  assert.match(TARGET,/node_modules\/@citrineos\/ocpp\/dist\/src\/transport\/network-connection\/websocket-network-connection\.js$/);
});
test('patch is exact, idempotent and parses',()=>{
  const patched=patch(upstream);
  assert.equal(sha256(patched),PATCHED_SHA256);
  assert.equal(patch(patched),patched);
  assert.equal(patched.split(MARKER).length-1,2);
  for(const {replacement} of EDITS)assert.equal(patched.split(replacement).length-1,1);
  const file=path.join(tmp,'syntax.mjs');fs.writeFileSync(file,patched);
  assert.equal(spawnSync(process.execPath,['--check',file]).status,0);
});
test('any other upstream text fails the build',()=>{
  assert.throws(()=>patch(upstream.replace('live connections','connections')),/not the pinned/);
  // Anchors must occur exactly once.
  assert.throws(()=>applyEdits(upstream.replace(EDITS[1].anchor,'')),/found 0 times/);
  assert.throws(()=>applyEdits(upstream+EDITS[0].anchor),/found 2 times/);
  assert.throws(()=>applyEdits(applyEdits(upstream)),/already partly patched/);
});
test('build step patches once; --check passes only for a patched file',()=>{
  const file=path.join(tmp,'websocket-network-connection.js');
  fs.writeFileSync(file,upstream);
  assert.throws(()=>main(['--check',file]),/not patched/);
  main([file]);
  assert.equal(sha256(fs.readFileSync(file,'utf8')),PATCHED_SHA256);
  main([file]);
  assert.equal(sha256(fs.readFileSync(file,'utf8')),PATCHED_SHA256);
  assert.doesNotThrow(()=>main(['--check',file]));
});

// Runs the compiled upstream class with its imports replaced by small fakes.
// The fake router models CitrineOS v2.0.1: deregisterConnection reads and
// writes the database, then RabbitMqRouterReceiver.unsubscribe removes the
// identifier's bindings from its map and unbinds each one; registerConnection
// subscribes the request and response bindings concurrently. Broker calls
// on the router channel run one at a time, in order.
const STUBS=`import {performance} from 'node:perf_hooks';
const CacheNamespace={Connections:'Connections'};
const ConfigLoader={};
const createIdentifier=(t,n)=>t+':'+n;
const getTenantIdFromIdentifier=i=>Number(i.split(':')[0]);
const getStationIdFromIdentifier=i=>i.split(':').slice(1).join(':');
const TENANT_WEBSOCKET_SERVER_PATH_PATTERN=/^$/;
const http={},https={},tls={};class Duplex{}class Logger{}
const WebSocket={OPEN:1};class WebSocketServer{}
const noop=()=>{};
const initWsTransportMetrics=noop,recordWsActiveConnectionsDelta=noop,recordWsConnectionClosed=noop,
  recordWsConnectionEstablished=noop,recordWsConnectionRejected=noop,recordWsConnectionSetupDuration=noop,
  recordWsSendFailure=noop,recordWsUpgrade=noop;
const WsRejectReason={},WsSendFailureReason={},WsUpgradeResult={};
class UpgradeAuthenticationError extends Error{}class UpgradeUnknownError extends Error{}class TlsCredentialManager{}
`;
async function load(text,name) {
  const body=text.replace(/^import .*;$/gm,'');
  const file=path.join(tmp,name);fs.writeFileSync(file,STUBS+body);
  return (await import(pathToFileURL(file).href)).WebsocketNetworkConnection;
}
const delay=ms=>new Promise(r=>setTimeout(r,ms));
function harness(Connection) {
  const cache=new Map();
  const broker=new Set();
  let channel=Promise.resolve();
  const rpc=fn=>(channel=channel.then(()=>delay(3)).then(fn));
  const tracked=new Map();
  async function subscribe(identifier,state) {
    await Promise.resolve();
    const key=identifier+'/'+state;
    await rpc(()=>broker.add(key));
    tracked.set(identifier,[...(tracked.get(identifier)??[]),key]);
  }
  async function unsubscribe(identifier) {
    const keys=tracked.get(identifier);
    if(!keys?.length)return false;
    tracked.delete(identifier);
    for(const key of keys)await rpc(()=>broker.delete(key));
    return true;
  }
  const router={
    registerConnection:async(t,n)=>{const id=t+':'+n;
      const r=await Promise.all([subscribe(id,'request'),subscribe(id,'response'),delay(8)]);return r.length===3;},
    deregisterConnection:async(t,n)=>{await delay(8);await delay(8);return unsubscribe(t+':'+n);},
  };
  const logger={getSubLogger:()=>logger,debug(){},info(){},warn(){},error(){},fatal(){}};
  const conn=new Connection({config:{},logger,router,fileStorage:{},authenticator:{},connectionManager:{isConnected:()=>true},
    cache:{
      get:async k=>cache.get(k),
      setIfNotExist:async(k,v)=>cache.has(k)?false:(cache.set(k,v),true),
      remove:async k=>{const v=cache.get(k);cache.delete(k);return v;},
      updateExpiration:async()=>true,
    },
    doesChargingStationExistByOcppConnectionName:async()=>{await delay(8);return true;},
    getMaxChargingStationsForTenant:async()=>null,
  });
  return {conn,cache,broker};
}
function socket() {
  const ws=new EventEmitter();
  Object.assign(ws,{protocol:'ocpp2.1',readyState:1,pause(){},resume(){},ping(){},pong(){},send(){},
    terminate(){setImmediate(()=>ws.emit('close',1006,Buffer.from('')));},
    close(code){setImmediate(()=>ws.emit('close',code,Buffer.from('')));}});
  return ws;
}
const config={id:'citrine-plugfest',tenantId:1,allowUnknownChargingStations:true};
const req={url:'/SIM-EV-EVEREST-V2G-03',headers:{},socket:{remoteAddress:'127.0.0.1',remotePort:1}};
const ID='1:SIM-EV-EVEREST-V2G-03';
// The station drops its socket and reconnects at once, as EVerest does after
// "Pong not received from server!". ConnectedStationFilter admits it as soon
// as the old connection's cache slot is gone.
async function reconnectRace(Connection) {
  const {conn,cache,broker}=harness(Connection);
  const old=socket();
  await conn._onConnection(old,config,30,req);
  assert.deepEqual([...broker].sort(),[ID+'/request',ID+'/response']);
  old.emit('close',1000,Buffer.from(''));
  while(cache.has(ID))await Promise.resolve();
  const fresh=socket();
  await conn._onConnection(fresh,config,30,req);
  await delay(100);
  for(const timer of conn._pingTimers.values())clearTimeout(timer);
  return {conn,cache,broker,fresh};
}
test('unpatched upstream loses the reconnected station bindings (the #67 race)',async()=>{
  const {conn,broker,fresh}=await reconnectRace(await load(upstream,'upstream.mjs'));
  assert.equal(conn._identifierConnections.get(ID),fresh);
  assert.notDeepEqual([...broker].sort(),[ID+'/request',ID+'/response']);
});
test('patched: a reconnect keeps the station bindings and slot',async()=>{
  const {conn,cache,broker,fresh}=await reconnectRace(await load(patch(upstream),'patched.mjs'));
  assert.equal(conn._identifierConnections.get(ID),fresh);
  assert.deepEqual([...broker].sort(),[ID+'/request',ID+'/response']);
  assert.ok(cache.has(ID));
  assert.equal(conn._haClosing.size,0);
});
test('patched: replacing a stale socket still works',async()=>{
  const {conn,broker}=harness(await load(patch(upstream),'patched-stale.mjs'));
  const old=socket(),fresh=socket();
  await conn._onConnection(old,config,30,req);
  await conn._onConnection(fresh,config,30,req);
  await delay(50);
  for(const timer of conn._pingTimers.values())clearTimeout(timer);
  assert.equal(conn._identifierConnections.get(ID),fresh);
  assert.deepEqual([...broker].sort(),[ID+'/request',ID+'/response']);
  assert.equal(conn._haClosing.size,0);
});
