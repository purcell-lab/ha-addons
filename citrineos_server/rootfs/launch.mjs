import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {STATION_PATTERN,PROTOCOL,PROTOCOLS,COMMANDS_BY_PROTOCOL,ALL_ROUTES,MAX_IMPORT_W,MAX_EXPORT_W,ROUTES,rolesSeed,routeProtocol,
  validateCommand,TARGET_QUERY,targetAllows,commandStation,stationAllowed,
  OPERATOR_COMMANDS,METERING_COMMAND,meteringVariables,operatorCommand,OPERATOR_TARGET_QUERY,operatorTargetAllows,
  CONFIG_ROUTE,CONFIG_UPSTREAM,CONFIG_KEYS,validateConfigRequest,configTargetAllows,configResult,
  PRICE_ROUTES,DEFAULT_TARIFF_ROUTE,priceOptions,pricePolicy,tariffStations,hasPriceSchedule,
  validateCostUpdated,costTargetAllows,tariffTarget,validateTariff,tariffTargetAllows,
  startRoute,RECONCILE_ROUTE,RECONCILE_EVERY_MS,reconcileTarget,reconcileDue,
  REPORT_ROLE,REPORT_STATIONS_QUERY,deviceModelReports,reportState,reportsDue,reportDone,
  DER_ROUTES,DER_EVENTS_ROUTE,DER_EVENT_ACTIONS,DER_EVENT_LIMIT,DER_REPORT_WAIT_MS,DER_EVENTS_QUERY,
  derEnabled,derRoute,derPolicy,validateDer,derTargetAllows,derStationId,derEvents,derReports} from './control-policy.mjs';

export const APP = '/usr/local/apps/citrineos/apps/ocpp-server';
const DATA = '/data';
const here = fileURLToPath(new URL('.', import.meta.url));
export function validate(o) {
  if (!['isolated', 'disconnected'].includes(o.mode)) throw new Error('Invalid mode');
  if (o.mode === 'disconnected') return;
  for (const key of ['database_password','broker_password','hasura_secret','api_token']) {
    if (!/^[a-f0-9]{64}$/.test(o[key] || '')) throw new Error('Missing generated credential');
  }
  if (new Set([o.database_password,o.broker_password,o.hasura_secret,o.api_token]).size !== 4)
    throw new Error('Credentials must be distinct');
  for (const key of ['database_host','broker_host','hasura_host']) {
    if (!/^[a-z0-9][a-z0-9.-]*$/.test(o[key] || '')) throw new Error('Invalid private dependency hostname');
  }
  if(o.simulator_enabled===true && (!/^[a-f0-9]{40}$/.test(o.simulator_password||'')
      || [o.database_password,o.broker_password,o.hasura_secret,o.api_token].includes(o.simulator_password)))
    throw new Error('A distinct simulator credential is required');
  if(o.simulator_enabled!==undefined && typeof o.simulator_enabled!=='boolean') throw new Error('Invalid simulator flag');
  for(const flag of ['profile_simulator_enabled','command_control_enabled','open_admission_enabled','command_real_stations_enabled','device_model_reports'])
    if(o[flag]!==undefined&&typeof o[flag]!=='boolean')throw new Error('Invalid control flag');
  if(o.profile_simulator_enabled&&!/^[a-f0-9]{32}$/.test(o.profile_simulator_password||''))throw new Error('Missing profile simulator credential');
  if(o.command_station_id!==undefined&&!stationAllowed(o.command_station_id,o.command_real_stations_enabled))
    throw new Error(o.command_real_stations_enabled?'Invalid command station identity':'Command station must be a SIM-EV- identity');
  // A physical command station connects on the Plugfest listener, the only port the
  // App can publish. The profile simulator would provision the same identity with
  // the lab simulator credential on port 8081, so the two do not combine.
  if(!STATION_PATTERN.test(commandStation(o))) {
    if(!o.plugfest_enabled)throw new Error('A physical command station needs plugfest_enabled');
    if(o.profile_simulator_enabled)throw new Error('A physical command station cannot use profile_simulator_enabled');
  }
  if(o.command_control_enabled&&(!(o.profile_simulator_enabled||o.open_admission_enabled)||!/^[a-f0-9]{64}$/.test(o.command_token||'')
    ||[o.api_token,o.database_password,o.broker_password,o.hasura_secret].includes(o.command_token)))throw new Error('Distinct command credential required');
  validateOperator(o);
  validatePlugfest(o);
  validatePrice(o);
  validateDerOption(o);
}
// Dynamic pricing (B/C/D) uses the command credential, so it needs scoped commands.
export function validatePrice(o) {
  if(o.price_commands_enabled!==undefined&&typeof o.price_commands_enabled!=='boolean')throw new Error('Invalid price flag');
  if(o.price_currency!==undefined&&!/^[A-Z]{3}$/.test(o.price_currency))throw new Error('price_currency must be an ISO 4217 code such as AUD');
  if(o.price_commands_enabled&&!o.command_control_enabled)throw new Error('price_commands_enabled needs command_control_enabled');
}
// DER control uses the command credential, so it needs scoped commands.
export function validateDerOption(o) {
  if(o.der_commands_enabled!==undefined&&typeof o.der_commands_enabled!=='boolean')throw new Error('Invalid DER flag');
  if(o.der_commands_enabled&&!o.command_control_enabled)throw new Error('der_commands_enabled needs command_control_enabled');
}
// CitrineOS sends its own CostUpdated (from its Tariffs table, zero for the
// lab tariff) every costUpdatedInterval seconds of a transaction; that would
// replace the price the gateway's CostUpdated shows. Upstream requires either
// an interval or sendCostUpdatedOnMeterValue (which instead fills totalCost in
// every TransactionEventResponse Updated), so with price commands the interval
// is the largest Node setInterval accepts (2^31-1 ms, about 24.8 days; a longer
// one would fire every millisecond).
export const COST_UPDATED_INTERVAL_OFF=2147483;
export const upstreamTransactions=o=>o.price_commands_enabled===true
  ?{TRANSACTIONS:{costUpdatedInterval:COST_UPDATED_INTERVAL_OFF}}:{};
// Operator UI App: a separate token for read-only Hasura access as
// "operator_ro" and, optionally, the fixed operator command set.
export function validateOperator(o) {
  for(const flag of ['operator_ui_enabled','operator_commands_enabled'])
    if(o[flag]!==undefined&&typeof o[flag]!=='boolean')throw new Error('Invalid operator flag');
  if(o.operator_commands_enabled&&!o.operator_ui_enabled)throw new Error('Operator commands need operator_ui_enabled');
  if(!o.operator_ui_enabled)return;
  if(!/^[a-f0-9]{64}$/.test(o.operator_token||'')||[o.api_token,o.command_token,o.database_password,
    o.broker_password,o.hasura_secret].includes(o.operator_token))throw new Error('Distinct operator credential required');
}
// OCPP identity used as the Basic Auth user name: no ':' or '/'.
export const PLUGFEST_ID=/^[A-Za-z0-9._~*+-]{1,48}$/;
// OCPP 2.0.1/2.1 BasicAuthPassword: 16 to 40 printable characters.
export const PLUGFEST_PASSWORD=/^[\x21-\x7e]{16,40}$/;
export function validatePlugfest(o) {
  for(const flag of ['plugfest_enabled','plugfest_open_admission'])
    if(o[flag]!==undefined&&typeof o[flag]!=='boolean')throw new Error('Invalid Plugfest flag');
  if(o.plugfest_open_admission&&!o.plugfest_enabled)throw new Error('plugfest_open_admission needs plugfest_enabled');
  const stations=o.plugfest_stations??[];
  if(!Array.isArray(stations))throw new Error('plugfest_stations must be a list');
  if(!o.plugfest_enabled)return;
  // Open admission accepts any identity, so the list may be empty there.
  if(!stations.length&&!o.plugfest_open_admission)throw new Error('Plugfest listener needs at least one provisioned station');
  // Identities a simulator option already provisions with its own password.
  const reserved=new Set([...(o.simulator_enabled?['SIM-CITRINE-LAB-01']:[]),
    ...(o.profile_simulator_enabled?[commandStation(o)]:[])]);
  const secrets=[o.database_password,o.broker_password,o.hasura_secret,o.api_token,o.command_token,
    o.simulator_password,o.profile_simulator_password].filter(Boolean);
  const ids=new Set(), passwords=new Set();
  for(const st of stations) {
    if(!st||typeof st!=='object'||!PLUGFEST_ID.test(st.id||''))throw new Error('Invalid Plugfest station identity');
    if(reserved.has(st.id))throw new Error('Plugfest identity is already provisioned by a simulator option');
    if(!PLUGFEST_PASSWORD.test(st.password||''))throw new Error('Plugfest password must be 16-40 printable characters');
    if(ids.has(st.id)||passwords.has(st.password)||secrets.includes(st.password))
      throw new Error('Plugfest identities and passwords must be unique and distinct from other credentials');
    ids.add(st.id);passwords.add(st.password);
  }
}
// Port 8081 authenticates provisioned stations. Optional port 8082 admits
// any identity without credentials: an explicit, lab-only decision.
// Optional port 8083 is the Plugfest listener for external charging stations:
// Security Profile 1 with per-station provisioned passwords, unknown stations
// rejected; or, with plugfest_open_admission, Security Profile 0 admitting any
// identity without credentials. With 8100-8105 below, these are the only
// ports the App can publish on the host. Upstream picks the first of these protocols the station offers,
// so 2.1 is preferred and 1.6 is the last fallback.
export const PLUGFEST_PROTOCOLS=['ocpp2.1','ocpp2.0.1','ocpp1.6'];
// Ports 8100-8105 are identical Plugfest listeners, so each station under test
// can be given its own endpoint (ws://host:8100 ... ws://host:8105). Admission
// is the same as on 8083: a port does not restrict which identity connects.
export const PLUGFEST_STATION_PORTS=[8100,8101,8102,8103,8104,8105];
// Ports the App uses itself: upstream API (loopback), JWKS, callbacks and the
// gateway. No listener may use them.
export const UPSTREAM_API_PORT=8088;
const UPSTREAM=`http://127.0.0.1:${UPSTREAM_API_PORT}`;
export const INTERNAL_PORTS=[8080,8091,8092,UPSTREAM_API_PORT];
export function buildListeners(o) {
  const listeners=[];
  if(o.simulator_enabled||o.profile_simulator_enabled) listeners.push({
    id:'citrine-lab-2x',host:'0.0.0.0',port:8081,
    protocols:o.profile_simulator_enabled?['ocpp2.1','ocpp2.0.1']:['ocpp2.0.1'],
    securityProfile:1,allowUnknownChargingStations:false,ignoreAuthenticationHeaders:false,
    tenantId:1,dynamicTenantResolution:false,pingInterval:30,
  });
  if(o.open_admission_enabled) listeners.push({
    id:'citrine-lab-open',host:'0.0.0.0',port:8082,protocols:['ocpp2.1','ocpp2.0.1'],
    securityProfile:0,allowUnknownChargingStations:true,ignoreAuthenticationHeaders:true,
    tenantId:1,dynamicTenantResolution:false,pingInterval:30,
  });
  const open=o.plugfest_open_admission===true;
  if(o.plugfest_enabled) for(const port of [8083,...PLUGFEST_STATION_PORTS]) listeners.push({
    id:port===8083?'citrine-plugfest':`citrine-plugfest-${port}`,host:'0.0.0.0',port,
    protocols:[...PLUGFEST_PROTOCOLS],
    securityProfile:open?0:1,allowUnknownChargingStations:open,ignoreAuthenticationHeaders:open,
    tenantId:1,dynamicTenantResolution:false,pingInterval:30,
  });
  return listeners;
}
// A deliberate stop exits 0 whatever code upstream ends with on SIGTERM;
// otherwise Supervisor reports the stopped App as "error" (#30). An upstream
// exit the gateway did not ask for is always a failure.
export function upstreamExitCode(shutting) { return shutting ? 0 : 1; }
// Why the gateway refuses a scoped command: a price schedule is the likely cause when present.
export function commandRejection(url,parsed,price) {
  if(!hasPriceSchedule(parsed))return 'Command outside lab bounds';
  if(price?.enabled!==true)return 'Price schedules need price_commands_enabled';
  if(routeProtocol(url.pathname)!=='ocpp2.1')return 'Price schedules need OCPP 2.1';
  return 'Command or price schedule outside lab bounds';
}
// The gateway's checks on a price route (C/D) before it reads station state:
// {status,error} to refuse, or {target}, the station to observe and address.
export function priceRequest(o,url,controller,parsed) {
  const price=priceOptions(o);
  if(!price.enabled)return {status:403,error:'Price commands are off (price_commands_enabled)'};
  if(controller!==true)return {status:403,error:'Command credential required'};
  if(url.pathname===DEFAULT_TARIFF_ROUTE) {
    const target=tariffTarget(url,tariffStations(o),price);
    if(!target)return {status:403,error:'SetDefaultTariff needs identifier=<a tariff_stations entry>&tenantId=1'};
    if(!validateTariff(parsed,price))return {status:400,error:'Tariff outside lab bounds'};
    return {target};
  }
  const station=commandStation(o);
  if(!validateCostUpdated(url,parsed,station,o.command_real_stations_enabled===true,price))
    return {status:400,error:'CostUpdated outside lab bounds'};
  return {target:station};
}
export function permitted(method, path) {
  return (method === 'GET' && ['/health/ready','/commands/tariff','/lab/status','/lab/control-policy'].includes(path))
    || (method === 'POST' && path === '/v1/graphql');
}
export function equalToken(actual, expected) {
  const a=Buffer.from(actual || ''), b=Buffer.from(expected);
  return a.length === b.length && crypto.timingSafeEqual(a,b);
}
function delay(ms) { return new Promise(r=>setTimeout(r,ms)); }
async function tcpReady(host,port) {
  return new Promise(resolve=>{
    const s=net.createConnection({host,port});
    s.setTimeout(1500);
    const done=ok=>{s.destroy();resolve(ok);};
    s.once('connect',()=>done(true)); s.once('error',()=>done(false)); s.once('timeout',()=>done(false));
  });
}
async function waitFor(label,check) {
  for(let i=0;i<90;i++) { if(await check()) return; await delay(2000); }
  throw new Error(`${label} readiness timed out`);
}
async function jsonFetch(url, options={}, timeoutMs=10000) {
  const r=await fetch(url,{...options,signal:AbortSignal.timeout(timeoutMs),redirect:'error'});
  const data=await r.json();
  if(!r.ok || data.errors || data.error) throw new Error(`Dependency response rejected (${r.status})`);
  return data;
}
function makeSigner() {
  // Keys stay in memory. Restart invalidates internal short-lived JWTs.
  const {privateKey,publicKey}=crypto.generateKeyPairSync('rsa',{modulusLength:2048});
  const jwk={...publicKey.export({format:'jwk'}),kid:'lab',use:'sig',alg:'RS256'};
  const b64=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
  // role: false = lab-reader, true = lab-controller, or an explicit role name.
  return {jwk,token(control=false) {
    const now=Math.floor(Date.now()/1000);
    const unsigned=b64({alg:'RS256',kid:'lab',typ:'JWT'})+'.'+b64({
      iss:JWT_ISSUER,aud:JWT_AUDIENCE,sub:'ha-lab-reader',tenant_id:'1',
      roles:[typeof control==='string'?control:control?'lab-controller':'lab-reader'],iat:now,exp:now+60,
    });
    return unsigned+'.'+crypto.sign('RSA-SHA256',Buffer.from(unsigned),privateKey).toString('base64url');
  }};
}
// The pinned upstream release (compatibility-lock.json).
export const RELEASE='v2.1.0';
// Roles seed file CitrineOS reads (control-policy.mjs rolesSeed), written by
// the launcher as root at each start.
export const ROLES_SEED=`${APP}/roles-seed.json`;
// The gateway's internal tokens (makeSigner): RS256 with kid "lab", served on
// the loopback JWKS endpoint.
export const JWT_ISSUER='citrine-ha-lab';
export const JWT_AUDIENCE='citrine-api';
// Upstream configuration (CITRINEOS_<KEY> variables). auth.mode is set to jwt
// explicitly: v2.1.0 defaults to localDev, which mounts a token-minting
// /dev/token route (and refuses to start with env production).
export function upstreamConfig(o) {
  return {
    ENV:'production',HOST:'127.0.0.1',PORT:UPSTREAM_API_PORT,
    DATABASE_HOST:o.database_host,DATABASE_USERNAME:'citrine',DATABASE_PASSWORD:o.database_password,
    DATABASE_DATABASE:'citrine',DATABASE_POOL:{max:10,min:0},DATABASE_SYNC:false,DATABASE_ALTER:false,DATABASE_FORCE:false,
    MESSAGEBROKER_AMQP_URL:`amqp://citrine:${o.broker_password}@${o.broker_host}:5672`,
    FILEACCESS_LOCAL_DEFAULTFILEPATH:`${DATA}/assets`,
    AUTH:{mode:'jwt',jwt:{jwksUri:'http://127.0.0.1:8091/jwks',issuer:JWT_ISSUER,audience:JWT_AUDIENCE,
      rolesClaim:'roles',tenantClaim:'tenant_id'}},
    ROLES:{seedFile:ROLES_SEED},
    SWAGGER:{enabled:true,exposeMessage:true,exposeData:true,logoPath:`${APP}/dist/assets/logo.png`},
    LOGLEVEL:4,INTEGRATIONS:{},...upstreamTransactions(o),
  };
}
export async function main() {
  process.umask(0o077);
  const o=fs.existsSync(`${DATA}/options.json`) ? JSON.parse(fs.readFileSync(`${DATA}/options.json`)) : {mode:'disconnected'};
  validate(o);
  if(process.getuid()===0) {
    if(o.mode==='isolated') {
      fs.chownSync(DATA,1000,1000);
      // CitrineOS reads its roles seed at start (and every 60 s); write it from the
      // gateway's route lists while still root (the app folder is root-owned), so
      // the upstream process (uid 1000) can read it but not change it.
      fs.writeFileSync(ROLES_SEED,JSON.stringify(rolesSeed(o.command_control_enabled===true,o.price_commands_enabled===true,
        deviceModelReports(o),derEnabled(o))));
      fs.chmodSync(ROLES_SEED,0o644);
    }
    process.setgid(1000);process.setuid(1000);
  }
  if(o.mode==='disconnected') {
    console.log('CitrineOS disconnected: no database, broker or server activity.');
    const timer=setInterval(()=>{},3600000);
    for(const s of ['SIGTERM','SIGINT']) process.on(s,()=>{clearInterval(timer);process.exit(0);});
    return;
  }
  fs.mkdirSync(`${DATA}/assets`,{recursive:true});
  const listeners=buildListeners(o);
  const station=commandStation(o);
  const price=priceOptions(o), real=o.command_real_stations_enabled===true;
  fs.writeFileSync(`${DATA}/assets/websocket-servers.json`,JSON.stringify(listeners),{mode:0o600});
  const env={...process.env,APP_NAME:'all',NODE_OPTIONS:'--max-old-space-size=768'};
  // JSON encoding prevents upstream config-loader debug output exposing string secrets.
  for(const [k,v] of Object.entries(upstreamConfig(o))) env['CITRINEOS_'+k]=JSON.stringify(v);
  const secrets=[o.database_password,o.broker_password,o.hasura_secret,o.api_token,o.simulator_password,o.profile_simulator_password,o.command_token,o.operator_token,
    ...(o.plugfest_enabled?(o.plugfest_stations||[]).map(st=>st.password):[])].filter(Boolean);
  let child, shutting=false;
  const streams=[];
  function logPipe(stream) {
    let pending='';
    stream.on('data',chunk=>{
      pending+=chunk.toString();
      let newline;
      while((newline=pending.indexOf('\n'))>=0) {
        let line=pending.slice(0,newline); pending=pending.slice(newline+1);
        for(const secret of secrets) line=line.split(secret).join('[redacted]');
        console.log(line);
      }
      if(pending.length>65536) pending='[oversize log omitted]';
    });
  }
  function run(args,command='node') {
    return new Promise((resolve,reject)=>{
      child=spawn(command,args,{cwd:APP,env,stdio:['ignore','pipe','pipe']});
      logPipe(child.stdout); logPipe(child.stderr);
      child.once('error',()=>reject(new Error('Upstream process failed')));
      child.once('exit',code=>code===0?resolve():reject(new Error(`Upstream process exited (${code})`)));
    });
  }
  const stop=()=>{
    if(shutting)return; shutting=true;
    for(const s of streams)s.close();
    child?.kill('SIGTERM');
    setTimeout(()=>{child?.kill('SIGKILL');process.exit(0);},35000).unref();
  };
  process.on('SIGTERM',stop);process.on('SIGINT',stop);
  await waitFor('Database',()=>tcpReady(o.database_host,5432));
  await waitFor('Broker',()=>tcpReady(o.broker_host,5672));
  console.log('Applying pinned migrations to the dedicated laboratory database.');
  await run(['db:migrate'],`${APP}/node_modules/.bin/sequelize-cli`);
  await run([`${APP}/dist/scripts/provision-partitions.js`]);
  if(o.simulator_enabled||o.profile_simulator_enabled||o.open_admission_enabled||o.plugfest_enabled) {
    const {seedSimulator}=await import('./seed-simulator.mjs');
    await seedSimulator(o);
  }
  const signer=makeSigner();
  const jwks=http.createServer((req,res)=>{
    res.setHeader('Content-Type','application/json');
    res.end(JSON.stringify({keys:[signer.jwk]}));
  });
  await new Promise(r=>jwks.listen(8091,'127.0.0.1',r)); streams.push(jwks);
  // CitrineOS posts a station's reply to the callbackUrl given with a request.
  // Each configuration read registers a one-time random path here (loopback only).
  const replies=new Map();
  const callbacks=http.createServer(async(req,res)=>{
    const m=req.method==='POST'?/^\/callback\/([0-9a-f-]{36})$/.exec(req.url):null;
    const resolve=m?replies.get(m[1]):undefined;
    let size=0;const chunks=[];
    for await(const c of req) {size+=c.length;if(size>65536){res.writeHead(413);res.end();return;}chunks.push(c);}
    if(resolve) {try{resolve(JSON.parse(Buffer.concat(chunks).toString()));}catch{resolve({});}}
    res.writeHead(resolve?200:404);res.end();
  });
  await new Promise(r=>callbacks.listen(8092,'127.0.0.1',r)); streams.push(callbacks);
  const upstream=run([`${APP}/dist/index.js`]);
  upstream.then(()=>process.exit(upstreamExitCode(shutting))).catch(()=>{
    if(shutting){process.exit(upstreamExitCode(shutting));return;}
    console.error('Upstream server exited; gateway closing.');stop();process.exitCode=1;
  });
  await waitFor('CitrineOS',async()=> {
    try { const r=await fetch(UPSTREAM+'/health/ready',{signal:AbortSignal.timeout(1500)});return r.ok; } catch{return false;}
  });
  await waitFor('Hasura',async()=> {
    try {const r=await fetch(`http://${o.hasura_host}:8080/healthz`,{signal:AbortSignal.timeout(1500)});return r.ok;}catch{return false;}
  });
  // The Operator UI needs upstream's full schema; metadata-operator.json adds it
  // read-only (role operator_ro) and keeps ha_reader exactly as metadata.json.
  const metadata=JSON.parse(fs.readFileSync(`${here}/${o.operator_ui_enabled?'metadata-operator.json':'metadata.json'}`));
  await jsonFetch(`http://${o.hasura_host}:8080/v1/metadata`,{
    method:'POST',headers:{'Content-Type':'application/json','x-hasura-admin-secret':o.hasura_secret},
    body:JSON.stringify({type:'replace_metadata',args:{allow_inconsistent_metadata:false,metadata}}),
  // The full Operator UI schema took 10 s to apply on a busy Green and the
  // 10 s request timeout failed startup although Hasura stored it.
  },120000);
  // Operator UI requests: GraphQL as operator_ro (Hasura refuses any
  // mutation: the role has no insert, update or delete permission), and the
  // fixed operator command set when enabled. Nothing else is reachable.
  async function operatorRequest(req,res,url) {
    let size=0;const chunks=[];
    if(req.method!=='POST'){res.writeHead(405);res.end('{"error":"Operator route denied"}');return;}
    for await(const c of req) {size+=c.length;if(size>262144){res.writeHead(413);res.end('{}');return;}chunks.push(c);}
    const body=Buffer.concat(chunks).toString();
    let parsed;
    try{parsed=JSON.parse(body);}catch{res.writeHead(400);res.end('{"error":"Invalid JSON"}');return;}
    if(url.pathname==='/v1/graphql') {
      if(!parsed||Array.isArray(parsed)||typeof parsed.query!=='string'){res.writeHead(400);res.end('{}');return;}
      const r=await fetch(`http://${o.hasura_host}:8080/v1/graphql`,{method:'POST',body,redirect:'error',
        signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json',
          'x-hasura-admin-secret':o.hasura_secret,'x-hasura-role':'operator_ro','x-hasura-tenant-id':'1'}});
      res.writeHead(r.status);res.end(await r.text());return;
    }
    const cmd=o.operator_commands_enabled===true?operatorCommand(url):null;
    if(!cmd||!parsed||typeof parsed!=='object'||Array.isArray(parsed)){res.writeHead(403);res.end('{"error":"Operator route denied"}');return;}
    if(cmd.action===METERING_COMMAND&&!meteringVariables(parsed)){
      res.writeHead(403);res.end('{"error":"Only SampledDataCtrlr and AlignedDataCtrlr metering variables can be set"}');return;
    }
    const state=await jsonFetch(`http://${o.hasura_host}:8080/v1/graphql`,{
      method:'POST',headers:{'Content-Type':'application/json',
        'x-hasura-admin-secret':o.hasura_secret,'x-hasura-role':'operator_ro','x-hasura-tenant-id':'1'},
      body:JSON.stringify({query:OPERATOR_TARGET_QUERY,variables:{name:cmd.identifier}}),
    });
    if(!operatorTargetAllows(cmd,state)){
      res.writeHead(409);res.end('{"error":"Station is unknown, offline or uses another OCPP version"}');return;
    }
    console.log(`Operator command ${cmd.action} to ${cmd.identifier} (${cmd.protocol}).`);
    const r=await fetch(UPSTREAM+url.pathname+url.search,{method:'POST',body,redirect:'error',
      signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json',Authorization:`Bearer ${signer.token('lab-operator')}`}});
    res.writeHead(r.status);res.end(await r.text());
  }
  // Read-only OCPP 1.6 configuration of the command station (CONFIG_KEYS only).
  async function stationConfiguration(req,res,controller) {
    if(req.method!=='POST'){res.writeHead(405);res.end('{"error":"POST required"}');return;}
    if(!controller){res.writeHead(403);res.end('{"error":"Command credential required"}');return;}
    let size=0;const chunks=[];
    for await(const c of req) {size+=c.length;if(size>4096){res.writeHead(413);res.end('{}');return;}chunks.push(c);}
    let parsed;
    try{parsed=JSON.parse(Buffer.concat(chunks).toString());}catch{res.writeHead(400);res.end('{"error":"Invalid JSON"}');return;}
    if(!validateConfigRequest(parsed)){res.writeHead(400);res.end('{"error":"Only the listed configuration keys can be read"}');return;}
    if(!configTargetAllows(await observe(station),station)){
      res.writeHead(409);res.end('{"error":"The command station must be online on OCPP 1.6"}');return;
    }
    const payload=await callAndWait(res,CONFIG_UPSTREAM,station,{key:parsed.key});
    if(payload)res.end(JSON.stringify({station_id:station,protocol:'ocpp1.6',...configResult(payload,parsed.key)}));
  }
  // Observed station protocol and active transactions, read as ha_reader.
  function observe(name) {
    return jsonFetch(`http://${o.hasura_host}:8080/v1/graphql`,{
      method:'POST',headers:{'Content-Type':'application/json',
        'x-hasura-admin-secret':o.hasura_secret,'x-hasura-role':'ha_reader','x-hasura-tenant-id':'1'},
      body:JSON.stringify({query:TARGET_QUERY,variables:{name}}),
    });
  }
  // Sends one request with a one-time loopback callback. Returns {payload}, the
  // station's reply (a CALLRESULT payload or CitrineOS's CALLERROR object), or
  // {status,error}: 502 not sent, 504 no reply in 8 s. role: the internal JWT
  // role (signer.token), the command role by default.
  async function call(upstream,identifier,body,role=true) {
    const nonce=crypto.randomUUID();
    const reply=new Promise(resolve=>replies.set(nonce,resolve));
    try {
      const q=new URLSearchParams({identifier,tenantId:'1',callbackUrl:`http://127.0.0.1:8092/callback/${nonce}`});
      const r=await fetch(`${UPSTREAM}${upstream}?${q}`,{method:'POST',redirect:'error',
        body:JSON.stringify(body),signal:AbortSignal.timeout(4000),
        headers:{'Content-Type':'application/json',Authorization:`Bearer ${signer.token(role)}`}});
      const sent=await r.json().catch(()=>null);
      if(!r.ok||!Array.isArray(sent)||!sent.every(x=>x?.success===true))
        return {status:502,error:'CitrineOS did not send the request'};
      const payload=await Promise.race([reply,delay(8000).then(()=>null)]);
      return payload?{payload}:{status:504,error:'Station did not answer within 8 s'};
    } finally {replies.delete(nonce);}
  }
  // As call(), but answers the caller itself on failure and returns null.
  async function callAndWait(res,upstream,identifier,body) {
    const r=await call(upstream,identifier,body);
    if(r.error){res.writeHead(r.status);res.end(JSON.stringify({error:r.error}));return null;}
    return r.payload;
  }
  // Stale transactions (control-policy.mjs): asks the command station about
  // each transaction CitrineOS holds active for it (all of them, or only those
  // due), then reads the rows again. Upstream closes those the station no
  // longer has. One check runs at a time; a request during a check shares it.
  const checked=new Map();
  let checking=null;
  function reconcile(reason,cameOnline=true) {
    checking??=(async()=>{
      try {
        const target=reconcileTarget(await observe(station),station);
        if(!target)return null;
        for(const id of checked.keys()) if(!target.transactions.includes(id))checked.delete(id);
        const results=[];
        for(const id of reconcileDue(target,Date.now(),checked,cameOnline)) {
          checked.set(id,Date.now());
          const r=await call(target.route,station,{transactionId:id});
          results.push(r.payload?{transactionId:id,ongoingIndicator:r.payload.ongoingIndicator??null,
            messagesInQueue:r.payload.messagesInQueue??null}:{transactionId:id,error:r.error});
        }
        // The callback and upstream's row update come from the same reply;
        // allow the update a moment before reading the rows again.
        if(results.length)await delay(1500);
        const after=results.length?reconcileTarget(await observe(station),station):target;
        const active=after?after.transactions:null;
        for(const x of results)x.active=active?active.includes(x.transactionId):null;
        if(results.length)console.log(`Transaction status check (${reason}) on ${station}: `
          +results.map(x=>`${x.transactionId} ${x.active===false?'closed (not ongoing at the station)':x.active?'still active':'unknown'}`).join(', ')+'.');
        return {station_id:station,protocol:target.protocol,checked:results,active_after:active};
      } finally {checking=null;}
    })();
    return checking;
  }
  async function reconcileRequest(req,res,controller) {
    if(req.method!=='POST'){res.writeHead(405);res.end('{"error":"POST required"}');return;}
    if(!controller){res.writeHead(403);res.end('{"error":"Command credential required"}');return;}
    const result=await reconcile('requested');
    if(!result){res.writeHead(409);res.end('{"error":"The command station must be online on OCPP 2.1 or 2.0.1"}');return;}
    res.end(JSON.stringify(result));
  }
  // Dynamic pricing (price_commands_enabled): C CostUpdated to the command
  // station, D SetDefaultTariff to a listed station. B rides on setChargingProfile.
  async function priceCommand(req,res,url,controller) {
    let size=0;const chunks=[];
    for await(const c of req) {size+=c.length;if(size>65536){res.writeHead(413);res.end('{}');return;}chunks.push(c);}
    const body=Buffer.concat(chunks).toString();
    let parsed;
    try{parsed=JSON.parse(body);}catch{parsed=undefined;}
    const check=priceRequest(o,url,controller,parsed);
    if(check.error){res.writeHead(check.status);res.end(JSON.stringify({error:check.error}));return;}
    const target=check.target;
    if(url.pathname===DEFAULT_TARIFF_ROUTE) {
      if(!tariffTargetAllows(await observe(target),target)){
        res.writeHead(409);res.end('{"error":"The station must be online on OCPP 2.1"}');return;
      }
      console.log(`SetDefaultTariff ${parsed.tariff.tariffId} to ${target}.`);
      // The station's SetDefaultTariffResponse, or the CALLERROR (for example
      // NotImplemented) as CitrineOS reports it, unchanged.
      const payload=await callAndWait(res,DEFAULT_TARIFF_ROUTE,target,parsed);
      if(payload)res.end(JSON.stringify(payload));
      return;
    }
    if(!costTargetAllows(url,parsed,await observe(target),target)){
      res.writeHead(409);res.end('{"error":"The command station must be online on this OCPP version with this active transaction"}');return;
    }
    const r=await fetch(UPSTREAM+url.pathname+url.search,{method:'POST',body,redirect:'error',
      signal:AbortSignal.timeout(10000),headers:{'Content-Type':'application/json',Authorization:`Bearer ${signer.token(true)}`}});
    res.writeHead(r.status);res.end(await r.text());
  }
  // DER control (der_commands_enabled): OCPP 2.1 Set, Get and ClearDERControl
  // to the command station. A Get also returns the station's ReportDERControl
  // messages for its requestId, read back from OCPPMessages.
  // {events} or {error}: Hasura's own message (no secret in it), so a refused
  // read says why.
  async function derMessages(stationId) {
    const r=await fetch(`http://${o.hasura_host}:8080/v1/graphql`,{
      method:'POST',redirect:'error',signal:AbortSignal.timeout(10000),headers:{'Content-Type':'application/json',
        'x-hasura-admin-secret':o.hasura_secret,'x-hasura-role':'ha_reader','x-hasura-tenant-id':'1'},
      body:JSON.stringify({query:DER_EVENTS_QUERY,variables:{stationId,actions:DER_EVENT_ACTIONS,limit:DER_EVENT_LIMIT}}),
    });
    const data=await r.json().catch(()=>null);
    const refused=data?.errors?.[0]?.message;
    if(!r.ok||refused)return {error:`DER events read refused (${r.status}): ${String(refused??'no reply').slice(0,300)}`};
    const events=derEvents(data);
    return events?{events}:{error:'DER events read returned unexpected rows'};
  }
  async function derCommand(req,res,url,controller) {
    if(!derEnabled(o)){res.writeHead(403);res.end('{"error":"DER commands are off (der_commands_enabled)"}');return;}
    if(!controller){res.writeHead(403);res.end('{"error":"Command credential required"}');return;}
    let size=0;const chunks=[];
    for await(const c of req) {size+=c.length;if(size>65536){res.writeHead(413);res.end('{}');return;}chunks.push(c);}
    let parsed;
    try{parsed=JSON.parse(Buffer.concat(chunks).toString());}catch{parsed=undefined;}
    if(!validateDer(url,parsed,station,real)){res.writeHead(400);res.end('{"error":"DER control outside lab bounds"}');return;}
    const state=await observe(station);
    if(!derTargetAllows(state,station)){res.writeHead(409);res.end('{"error":"The command station must be online on OCPP 2.1"}');return;}
    const name=Object.keys(DER_ROUTES).find(k=>DER_ROUTES[k]===url.pathname);
    console.log(`DER ${name} (${parsed.controlType??'any type'}${parsed.controlId?` ${parsed.controlId}`:''}) to ${station}.`);
    // The station's reply, or the CALLERROR as CitrineOS reports it, unchanged.
    const payload=await callAndWait(res,url.pathname,station,parsed);
    if(!payload)return;
    if(url.pathname!==DER_ROUTES.get||payload.status!=='Accepted'){res.end(JSON.stringify(payload));return;}
    let found={reports:[],complete:false};
    for(const until=Date.now()+DER_REPORT_WAIT_MS;!found.complete&&Date.now()<until;) {
      await delay(500);
      const read=await derMessages(derStationId(state)).catch(()=>({error:'DER events read failed'}));
      if(read.events)found=derReports(read.events,parsed.requestId);
      else console.log(`${read.error}.`);
    }
    res.end(JSON.stringify({...payload,reports:found.reports}));
  }
  async function derEventsRequest(req,res) {
    if(req.method!=='GET'){res.writeHead(405);res.end('{"error":"GET required"}');return;}
    if(!derEnabled(o)){res.writeHead(403);res.end('{"error":"DER commands are off (der_commands_enabled)"}');return;}
    const s=(await observe(station))?.data?.ChargingStations;
    if(!Array.isArray(s)||s.length!==1||s[0].ocppConnectionName!==station||s[0].tenantId!==1){
      res.writeHead(409);res.end('{"error":"The command station is not known"}');return;
    }
    const read=await derMessages(s[0].id);
    if(read.error){console.log(`${read.error}.`);res.writeHead(502);res.end(JSON.stringify({error:read.error}));return;}
    res.end(JSON.stringify({station_id:station,events:read.events}));
  }
  const gateway=http.createServer(async(req,res)=>{
    res.setHeader('Cache-Control','no-store');res.setHeader('Content-Type','application/json');
    try {
      const url=new URL(req.url,'http://lab');
      if(o.operator_ui_enabled===true&&equalToken(req.headers.authorization,`Bearer ${o.operator_token}`)) {
        await operatorRequest(req,res,url);return;
      }
      const publicHealth=req.method==='GET' && url.pathname==='/health/ready';
      const controller=o.command_control_enabled===true&&equalToken(req.headers.authorization,`Bearer ${o.command_token}`);
      if(!publicHealth && !controller && !equalToken(req.headers.authorization,`Bearer ${o.api_token}`)) {
        res.writeHead(401);res.end('{"error":"Authentication required"}');return;
      }
      if(url.pathname===CONFIG_ROUTE) {await stationConfiguration(req,res,controller);return;}
      if(url.pathname===RECONCILE_ROUTE) {await reconcileRequest(req,res,controller);return;}
      if(req.method==='POST'&&PRICE_ROUTES.includes(url.pathname)) {await priceCommand(req,res,url,controller);return;}
      if(req.method==='POST'&&derRoute(url.pathname)) {await derCommand(req,res,url,controller);return;}
      if(url.pathname===DER_EVENTS_ROUTE) {await derEventsRequest(req,res);return;}
      const command=req.method==='POST'&&ALL_ROUTES.includes(url.pathname);
      if(command&&!controller) {res.writeHead(403);res.end('{"error":"Command credential required"}');return;}
      if(!command&&!permitted(req.method,url.pathname)) {res.writeHead(403);res.end('{"error":"Laboratory route denied"}');return;}
      if(url.pathname==='/lab/control-policy') {
        res.end(JSON.stringify({station_id:station,can_control:controller,protocol:PROTOCOL,
          commands:ROUTES,protocols:PROTOCOLS,commands_by_protocol:COMMANDS_BY_PROTOCOL,
          max_import_w:MAX_IMPORT_W,max_export_w:MAX_EXPORT_W,
          max_profile_seconds:600,max_periods:10,automatic_control:false,
          station_configuration:{route:CONFIG_ROUTE,protocols:['ocpp1.6'],keys:CONFIG_KEYS},
          transaction_reconcile:{route:RECONCILE_ROUTE,protocols:['ocpp2.1','ocpp2.0.1'],
            automatic:o.command_control_enabled===true,every_s:RECONCILE_EVERY_MS/1000},
          clear_requires_closed_transaction:true,real_devices_enabled:o.command_real_stations_enabled===true,
          open_admission:o.open_admission_enabled===true,price_commands:pricePolicy(o),der_commands:derPolicy(o)}));return;
      }
      if(url.pathname==='/lab/status') {
        res.end(JSON.stringify({release:RELEASE,mode:'isolated',tenant:1,charger_listeners:listeners.length,
          simulator_identity:o.simulator_enabled?'SIM-CITRINE-LAB-01':null,
          profile_simulator_identity:o.profile_simulator_enabled?station:null,
          open_admission:o.open_admission_enabled===true,
          plugfest_stations:o.plugfest_enabled?(o.plugfest_stations||[]).map(st=>st.id):[],
          plugfest_open_admission:o.plugfest_enabled===true&&o.plugfest_open_admission===true,
          plugfest_protocols:o.plugfest_enabled?PLUGFEST_PROTOCOLS:[],
          read_only:!controller,operator_ui:o.operator_ui_enabled===true,
          operator_commands:o.operator_ui_enabled===true&&o.operator_commands_enabled===true,
          device_model_reports:deviceModelReports(o),der_commands:derEnabled(o)}));return;
      }
      let target,headers={},body;
      if(url.pathname==='/v1/graphql'||command) {
        let size=0;const chunks=[];
        for await(const c of req) {size+=c.length;if(size>65536){res.writeHead(413);res.end('{}');return;}chunks.push(c);}
        body=Buffer.concat(chunks).toString();
        const parsed=JSON.parse(body);
        if(command) {
          if(!validateCommand(url,parsed,station,real,price)){
            res.writeHead(400);res.end(JSON.stringify({error:commandRejection(url,parsed,price)}));return;
          }
          const state=await jsonFetch(`http://${o.hasura_host}:8080/v1/graphql`,{
            method:'POST',headers:{'Content-Type':'application/json',
              'x-hasura-admin-secret':o.hasura_secret,'x-hasura-role':'ha_reader','x-hasura-tenant-id':'1'},
            body:JSON.stringify({query:TARGET_QUERY,variables:{name:station}}),
          });
          if(!targetAllows(url,parsed,state,station)){
            // A start refused for an active transaction may be refused for a
            // stale one: ask the station now, so a retry can succeed.
            const stale=startRoute(url.pathname)&&reconcileTarget(state,station)?.transactions.length>0;
            if(stale)reconcile('start refused').catch(()=>{});
            res.writeHead(409);res.end(JSON.stringify({error:'Observed station protocol or transaction does not permit this command'
              +(stale?'; checking the station\'s active transactions, retry in a few seconds':'')}));return;
          }
          target=UPSTREAM+url.pathname+url.search;
          headers={'Content-Type':'application/json',Authorization:`Bearer ${signer.token(true)}`};
        } else {
        if(!parsed || Array.isArray(parsed) || typeof parsed.query!=='string') {res.writeHead(400);res.end('{}');return;}
        target=`http://${o.hasura_host}:8080/v1/graphql`;
        // Caller-supplied role, tenant and admin headers are never forwarded.
        headers={'Content-Type':'application/json','x-hasura-admin-secret':o.hasura_secret,'x-hasura-role':'ha_reader','x-hasura-tenant-id':'1'};
        }
      } else {
        if(url.pathname==='/commands/tariff') {
          for(const [k,v] of url.searchParams) if(k!=='tenantId' || v!=='1') {
            res.writeHead(403);res.end('{"error":"Tenant scope denied"}');return;
          }
          url.search='?tenantId=1';
        }
        target=UPSTREAM+url.pathname+url.search;
        headers={Authorization:`Bearer ${signer.token()}`};
      }
      const r=await fetch(target,{method:req.method,headers,body,redirect:'error',signal:AbortSignal.timeout(10000)});
      res.writeHead(r.status);res.end(await r.text());
    } catch {
      // A timeout after forwarding may mean the station received the command.
      // The caller must reconcile, not retry automatically.
      res.writeHead(502);res.end('{"error":"Laboratory dependency unavailable; command outcome may be unknown. Do not retry automatically."}');
    }
  });
  gateway.requestTimeout=15000;gateway.headersTimeout=10000;
  await new Promise(r=>gateway.listen(8080,'0.0.0.0',r));streams.push(gateway);
  // With scoped commands, every 30 s: all of the command station's active
  // transactions are checked when it comes online, and each again every
  // RECONCILE_EVERY_MS (a reconnect between two reads is caught that way).
  if(o.command_control_enabled===true) {
    let online=false;
    const watch=async()=>{
      try {
        const s=(await observe(station))?.data?.ChargingStations?.[0];
        const now=s?.isOnline===true, cameOnline=now&&!online;
        online=now;
        if(now&&!checking)await reconcile(cameOnline?'station online':'periodic',cameOnline);
      } catch {}
    };
    setInterval(watch,30000).unref();watch();
  }
  // Device model reports (control-policy.mjs): every 30 s, one GetBaseReport
  // to each OCPP 2.x station that has come online since the last check.
  // Runs beside startup, never before it; one check at a time.
  if(deviceModelReports(o)) {
    const reports=reportState();
    let reporting=false;
    const watchReports=async()=>{
      if(reporting)return;
      reporting=true;
      try {
        const result=await jsonFetch(`http://${o.hasura_host}:8080/v1/graphql`,{
          method:'POST',headers:{'Content-Type':'application/json',
            'x-hasura-admin-secret':o.hasura_secret,'x-hasura-role':'ha_reader','x-hasura-tenant-id':'1'},
          body:JSON.stringify({query:REPORT_STATIONS_QUERY}),
        });
        for(const t of reportsDue(result,reports,Date.now())) {
          const r=await call(t.route,t.identifier,
            {requestId:crypto.randomInt(1,2147483647),reportBase:'FullInventory'},REPORT_ROLE);
          console.log(`Device model report requested from ${t.identifier} (${t.protocol}): ${reportDone(reports,t.identifier,r,Date.now())}.`);
        }
      } catch {} finally {reporting=false;}
    };
    setInterval(watchReports,30000).unref();watchReports();
  }
  console.log(`CitrineOS ${RELEASE} isolated lab ready. Scoped commands ${o.command_control_enabled?'enabled':'disabled'}; ${listeners.length} charger listener(s).`);
  if(o.plugfest_enabled&&o.plugfest_open_admission)
    console.log('WARNING: Plugfest listeners 8083 and 8100-8105 admit any station without authentication (plugfest_open_admission).');
}
if(process.argv[1]===fileURLToPath(import.meta.url)) main().catch(()=>{
  console.error('Laboratory startup failed; inspect dependency health. Credentials omitted.');
  process.exit(1);
});
