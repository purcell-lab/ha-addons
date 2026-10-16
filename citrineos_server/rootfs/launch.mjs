import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {STATION_PATTERN,PROTOCOL,MAX_POWER_W,ROUTES,validateCommand,TARGET_QUERY,targetAllows,commandStation} from './control-policy.mjs';

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
  for(const flag of ['profile_simulator_enabled','command_control_enabled','open_admission_enabled'])
    if(o[flag]!==undefined&&typeof o[flag]!=='boolean')throw new Error('Invalid control flag');
  if(o.profile_simulator_enabled&&!/^[a-f0-9]{32}$/.test(o.profile_simulator_password||''))throw new Error('Missing profile simulator credential');
  if(o.command_station_id!==undefined&&!STATION_PATTERN.test(o.command_station_id))throw new Error('Command station must be a SIM-EV- identity');
  if(o.command_control_enabled&&(!(o.profile_simulator_enabled||o.open_admission_enabled)||!/^[a-f0-9]{64}$/.test(o.command_token||'')
    ||[o.api_token,o.database_password,o.broker_password,o.hasura_secret].includes(o.command_token)))throw new Error('Distinct command credential required');
  validatePlugfest(o);
}
// OCPP identity used as the Basic Auth user name: no ':' or '/'.
export const PLUGFEST_ID=/^[A-Za-z0-9._~*+-]{1,48}$/;
// OCPP 2.0.1/2.1 BasicAuthPassword: 16 to 40 printable characters.
export const PLUGFEST_PASSWORD=/^[\x21-\x7e]{16,40}$/;
export function validatePlugfest(o) {
  if(o.plugfest_enabled!==undefined&&typeof o.plugfest_enabled!=='boolean')throw new Error('Invalid Plugfest flag');
  const stations=o.plugfest_stations??[];
  if(!Array.isArray(stations))throw new Error('plugfest_stations must be a list');
  if(!o.plugfest_enabled)return;
  if(!stations.length)throw new Error('Plugfest listener needs at least one provisioned station');
  const reserved=new Set(['SIM-CITRINE-LAB-01',commandStation(o)]);
  const secrets=[o.database_password,o.broker_password,o.hasura_secret,o.api_token,o.command_token,
    o.simulator_password,o.profile_simulator_password].filter(Boolean);
  const ids=new Set(), passwords=new Set();
  for(const st of stations) {
    if(!st||typeof st!=='object'||!PLUGFEST_ID.test(st.id||''))throw new Error('Invalid Plugfest station identity');
    // Vendor stations stay out of the simulator command namespace.
    if(reserved.has(st.id)||st.id.startsWith('SIM-EV-'))throw new Error('Plugfest identity is reserved for a simulator');
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
// rejected. It is the only port the App can publish on the host.
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
  if(o.plugfest_enabled) listeners.push({
    id:'citrine-plugfest',host:'0.0.0.0',port:8083,protocols:['ocpp2.1','ocpp2.0.1'],
    securityProfile:1,allowUnknownChargingStations:false,ignoreAuthenticationHeaders:false,
    tenantId:1,dynamicTenantResolution:false,pingInterval:30,
  });
  return listeners;
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
async function jsonFetch(url, options={}) {
  const r=await fetch(url,{...options,signal:AbortSignal.timeout(10000),redirect:'error'});
  const data=await r.json();
  if(!r.ok || data.errors || data.error) throw new Error(`Dependency response rejected (${r.status})`);
  return data;
}
function makeSigner() {
  // Keys stay in memory. Restart invalidates internal short-lived JWTs.
  const {privateKey,publicKey}=crypto.generateKeyPairSync('rsa',{modulusLength:2048});
  const jwk={...publicKey.export({format:'jwk'}),kid:'lab',use:'sig',alg:'RS256'};
  const b64=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
  return {jwk,token(control=false) {
    const now=Math.floor(Date.now()/1000);
    const unsigned=b64({alg:'RS256',kid:'lab',typ:'JWT'})+'.'+b64({
      iss:'citrine-ha-lab',aud:'citrine-api',sub:'ha-lab-reader',tenant_id:'1',
      roles:[control?'lab-controller':'lab-reader'],iat:now,exp:now+60,
    });
    return unsigned+'.'+crypto.sign('RSA-SHA256',Buffer.from(unsigned),privateKey).toString('base64url');
  }};
}
export async function main() {
  process.umask(0o077);
  const o=fs.existsSync(`${DATA}/options.json`) ? JSON.parse(fs.readFileSync(`${DATA}/options.json`)) : {mode:'disconnected'};
  validate(o);
  if(process.getuid()===0) {
    if(o.mode==='isolated') fs.chownSync(DATA,1000,1000);
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
  fs.writeFileSync(`${DATA}/assets/websocket-servers.json`,JSON.stringify(listeners),{mode:0o600});
  const env={...process.env,APP_NAME:'all',NODE_OPTIONS:'--max-old-space-size=768'};
  const config={
    ENV:'production',HOST:'127.0.0.1',PORT:8088,
    DATABASE_HOST:o.database_host,DATABASE_USERNAME:'citrine',DATABASE_PASSWORD:o.database_password,
    DATABASE_DATABASE:'citrine',DATABASE_POOL:{max:10,min:0},DATABASE_SYNC:false,DATABASE_ALTER:false,DATABASE_FORCE:false,
    MESSAGEBROKER_AMQP_URL:`amqp://citrine:${o.broker_password}@${o.broker_host}:5672`,
    FILEACCESS_LOCAL_DEFAULTFILEPATH:`${DATA}/assets`,
    AUTH:{localBypass:false,oidc:{jwksUri:'http://127.0.0.1:8091/jwks',issuer:'citrine-ha-lab',audience:'citrine-api'}},
    SWAGGER:{enabled:true,exposeMessage:true,exposeData:true,logoPath:`${APP}/dist/assets/logo.png`},
    LOGLEVEL:4,INTEGRATIONS:{},
  };
  // JSON encoding prevents upstream config-loader debug output exposing string secrets.
  for(const [k,v] of Object.entries(config)) env['CITRINEOS_'+k]=JSON.stringify(v);
  const secrets=[o.database_password,o.broker_password,o.hasura_secret,o.api_token,o.simulator_password,o.profile_simulator_password,o.command_token,
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
  const upstream=run([`${APP}/dist/index.js`]);
  upstream.then(()=>{if(!shutting)process.exit(1);else process.exit(0);}).catch(()=>{
    console.error('Upstream server exited; gateway closing.');stop();process.exitCode=1;
  });
  await waitFor('CitrineOS',async()=> {
    try { const r=await fetch('http://127.0.0.1:8088/health/ready',{signal:AbortSignal.timeout(1500)});return r.ok; } catch{return false;}
  });
  await waitFor('Hasura',async()=> {
    try {const r=await fetch(`http://${o.hasura_host}:8080/healthz`,{signal:AbortSignal.timeout(1500)});return r.ok;}catch{return false;}
  });
  const metadata=JSON.parse(fs.readFileSync(`${here}/metadata.json`));
  await jsonFetch(`http://${o.hasura_host}:8080/v1/metadata`,{
    method:'POST',headers:{'Content-Type':'application/json','x-hasura-admin-secret':o.hasura_secret},
    body:JSON.stringify({type:'replace_metadata',args:{allow_inconsistent_metadata:false,metadata}}),
  });
  const gateway=http.createServer(async(req,res)=>{
    res.setHeader('Cache-Control','no-store');res.setHeader('Content-Type','application/json');
    try {
      const url=new URL(req.url,'http://lab');
      const publicHealth=req.method==='GET' && url.pathname==='/health/ready';
      const controller=o.command_control_enabled===true&&equalToken(req.headers.authorization,`Bearer ${o.command_token}`);
      if(!publicHealth && !controller && !equalToken(req.headers.authorization,`Bearer ${o.api_token}`)) {
        res.writeHead(401);res.end('{"error":"Authentication required"}');return;
      }
      const command=req.method==='POST'&&ROUTES.includes(url.pathname);
      if(command&&!controller) {res.writeHead(403);res.end('{"error":"Command credential required"}');return;}
      if(!command&&!permitted(req.method,url.pathname)) {res.writeHead(403);res.end('{"error":"Laboratory route denied"}');return;}
      if(url.pathname==='/lab/control-policy') {
        res.end(JSON.stringify({station_id:station,can_control:controller,protocol:PROTOCOL,
          commands:ROUTES,max_import_w:MAX_POWER_W,max_export_w:MAX_POWER_W,
          max_profile_seconds:600,max_periods:10,automatic_control:false,
          clear_requires_closed_transaction:true,real_devices_enabled:false,
          open_admission:o.open_admission_enabled===true}));return;
      }
      if(url.pathname==='/lab/status') {
        res.end(JSON.stringify({release:'v2.0.1',mode:'isolated',tenant:1,charger_listeners:listeners.length,
          simulator_identity:o.simulator_enabled?'SIM-CITRINE-LAB-01':null,
          profile_simulator_identity:o.profile_simulator_enabled?station:null,
          open_admission:o.open_admission_enabled===true,
          plugfest_stations:o.plugfest_enabled?(o.plugfest_stations||[]).map(st=>st.id):[],
          read_only:!controller}));return;
      }
      let target,headers={},body;
      if(url.pathname==='/v1/graphql'||command) {
        let size=0;const chunks=[];
        for await(const c of req) {size+=c.length;if(size>65536){res.writeHead(413);res.end('{}');return;}chunks.push(c);}
        body=Buffer.concat(chunks).toString();
        const parsed=JSON.parse(body);
        if(command) {
          if(!validateCommand(url,parsed,station)){res.writeHead(400);res.end('{"error":"Command outside lab bounds"}');return;}
          const state=await jsonFetch(`http://${o.hasura_host}:8080/v1/graphql`,{
            method:'POST',headers:{'Content-Type':'application/json',
              'x-hasura-admin-secret':o.hasura_secret,'x-hasura-role':'ha_reader','x-hasura-tenant-id':'1'},
            body:JSON.stringify({query:TARGET_QUERY,variables:{name:station}}),
          });
          if(!targetAllows(url,parsed,state,station)){
            res.writeHead(409);res.end('{"error":"Observed station protocol or transaction does not permit this command"}');return;
          }
          target='http://127.0.0.1:8088'+url.pathname+url.search;
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
        target='http://127.0.0.1:8088'+url.pathname+url.search;
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
  console.log(`CitrineOS v2.0.1 isolated lab ready. Scoped commands ${o.command_control_enabled?'enabled':'disabled'}; ${listeners.length} charger listener(s).`);
}
if(process.argv[1]===fileURLToPath(import.meta.url)) main().catch(()=>{
  console.error('Laboratory startup failed; inspect dependency health. Credentials omitted.');
  process.exit(1);
});
