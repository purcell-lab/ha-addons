import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

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
}
export function permitted(method, path) {
  return (method === 'GET' && ['/health/ready','/commands/tariff','/lab/status'].includes(path))
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
  return {jwk,token() {
    const now=Math.floor(Date.now()/1000);
    const unsigned=b64({alg:'RS256',kid:'lab',typ:'JWT'})+'.'+b64({
      iss:'citrine-ha-lab',aud:'citrine-api',sub:'ha-lab-reader',tenant_id:'1',
      roles:['lab-reader'],iat:now,exp:now+60,
    });
    return unsigned+'.'+crypto.sign('RSA-SHA256',Buffer.from(unsigned),privateKey).toString('base64url');
  }};
}
export async function main() {
  process.umask(0o077);
  const o=fs.existsSync(`${DATA}/options.json`) ? JSON.parse(fs.readFileSync(`${DATA}/options.json`)) : {mode:'disconnected'};
  validate(o);
  if(process.getuid()===0) {
    fs.chownSync(DATA,1000,1000);
    process.setgid(1000);process.setuid(1000);
  }
  if(o.mode==='disconnected') {
    console.log('CitrineOS disconnected: no database, broker or server activity.');
    const timer=setInterval(()=>{},3600000);
    for(const s of ['SIGTERM','SIGINT']) process.on(s,()=>{clearInterval(timer);process.exit(0);});
    return;
  }
  fs.mkdirSync(`${DATA}/assets`,{recursive:true});
  // Empty listener list is deliberate. No OCPP connections are admitted.
  fs.writeFileSync(`${DATA}/assets/websocket-servers.json`,'[]\n',{mode:0o600});
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
  const secrets=[o.database_password,o.broker_password,o.hasura_secret,o.api_token];
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
  function run(args) {
    return new Promise((resolve,reject)=>{
      child=spawn('node',args,{cwd:APP,env,stdio:['ignore','pipe','pipe']});
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
  await run([`${APP}/node_modules/.bin/sequelize-cli`,'db:migrate']);
  await run([`${APP}/dist/scripts/provision-partitions.js`]);
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
      if(!publicHealth && !equalToken(req.headers.authorization,`Bearer ${o.api_token}`)) {
        res.writeHead(401);res.end('{"error":"Authentication required"}');return;
      }
      if(!permitted(req.method,url.pathname)) {res.writeHead(403);res.end('{"error":"Read-only laboratory"}');return;}
      if(url.pathname==='/lab/status') {
        res.end(JSON.stringify({release:'v2.0.1',mode:'isolated',tenant:1,charger_listeners:0,read_only:true}));return;
      }
      let target,headers={},body;
      if(url.pathname==='/v1/graphql') {
        let size=0;const chunks=[];
        for await(const c of req) {size+=c.length;if(size>65536){res.writeHead(413);res.end('{}');return;}chunks.push(c);}
        body=Buffer.concat(chunks).toString();
        const parsed=JSON.parse(body);
        if(!parsed || Array.isArray(parsed) || typeof parsed.query!=='string') {res.writeHead(400);res.end('{}');return;}
        target=`http://${o.hasura_host}:8080/v1/graphql`;
        // Caller-supplied role, tenant and admin headers are never forwarded.
        headers={'Content-Type':'application/json','x-hasura-admin-secret':o.hasura_secret,'x-hasura-role':'ha_reader','x-hasura-tenant-id':'1'};
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
      res.writeHead(502);res.end('{"error":"Laboratory dependency unavailable"}');
    }
  });
  gateway.requestTimeout=15000;gateway.headersTimeout=10000;
  await new Promise(r=>gateway.listen(8080,'0.0.0.0',r));streams.push(gateway);
  console.log('CitrineOS v2.0.1 isolated lab ready. Read-only gateway; zero charger listeners.');
}
if(process.argv[1]===fileURLToPath(import.meta.url)) main().catch(()=>{
  console.error('Laboratory startup failed; inspect dependency health. Credentials omitted.');
  process.exit(1);
});
