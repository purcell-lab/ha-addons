"""Local energy check for stack_smoke.py (TEST_EMS=1), source patch 0004.

A scripted OCPP 2.1 station on the Plugfest listener, made the command
station, inside the server container (the CI network is internal):
- before anything, /lab/charging-limits lists no limit;
- NotifyChargingLimit from an EMS (local generation) is stored: the limit is
  listed active, with its source, flags and schedule;
- a LocalGeneration profile sent with the command credential reaches the
  station as SetChargingProfile, and clearing its id reaches it as
  ClearChargingProfile;
- ClearedChargingLimit makes the limit inactive, with the time it was cleared.
"""
import json
import secrets
import subprocess
import time

STATION = "PF-CI-EMS-01"

STATION_SCRIPT = r"""
import {createRequire} from 'node:module';
const r=createRequire('/usr/local/apps/citrineos/apps/ocpp-server/package.json');
const WebSocket=r(r.resolve('ws'));
let s=''; for await (const c of process.stdin) s+=c;
const x=JSON.parse(s);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const received=[];
const ws=await new Promise((resolve,reject)=>{
  const w=new WebSocket('ws://127.0.0.1:8083/'+x.id,['ocpp2.1'],{handshakeTimeout:8000,
    headers:{Authorization:'Basic '+Buffer.from(x.id+':'+x.password).toString('base64')}});
  w.once('open',()=>resolve(w));w.once('unexpected-response',(_q,res)=>reject(new Error('refused '+res.statusCode)));
  w.once('error',reject);
});
// Answer every CSMS call; record what arrived.
ws.on('message',m=>{const f=JSON.parse(m.toString());
  if(f[0]!==2)return;
  received.push({action:f[2],payload:f[3]});
  ws.send(JSON.stringify([3,f[1],['SetChargingProfile','ClearChargingProfile','GetBaseReport'].includes(f[2])
    ?{status:'Accepted'}:{}]));});
function call(id,action,payload){
  return new Promise(resolve=>{
    const on=m=>{const f=JSON.parse(m.toString());
      if(f[1]===id&&(f[0]===3||f[0]===4)){clearTimeout(t);ws.off('message',on);resolve(f[0]===3?f[2]:{callerror:f[2]});}};
    const t=setTimeout(()=>{ws.off('message',on);resolve({timeout:true});},10000);
    ws.on('message',on);ws.send(JSON.stringify([2,id,action,payload]));
  });
}
async function gw(path,body){
  const r=await fetch('http://127.0.0.1:8080'+path,{method:body?'POST':'GET',signal:AbortSignal.timeout(15000),
    headers:{Authorization:'Bearer '+x.token,...(body?{'Content-Type':'application/json'}:{})},
    body:body?JSON.stringify(body):undefined});
  return {status:r.status,body:await r.json().catch(()=>null)};
}
const q='?identifier='+x.id+'&tenantId=1';
const out={};
out.boot=await call('b1','BootNotification',{chargingStation:{model:'ci-ems',vendorName:'purcell-lab'},reason:'PowerUp'});
await sleep(3000);
out.before=await gw('/lab/charging-limits');
out.notify=await call('n1','NotifyChargingLimit',{evseId:1,
  chargingLimit:{chargingLimitSource:'EMS',isLocalGeneration:true,isGridCritical:false},
  chargingSchedule:[{id:1,chargingRateUnit:'W',chargingSchedulePeriod:[{startPeriod:0,limit:3000}]}]});
await sleep(2000);
out.reported=await gw('/lab/charging-limits');
const start=new Date(Date.now()+60000).toISOString().replace(/\.\d+Z$/,'Z');
out.local_generation=await gw('/ocpp/2.1/smartcharging/setChargingProfile'+q,{evseId:0,chargingProfile:{
  id:9100,stackLevel:1,chargingProfilePurpose:'LocalGeneration',chargingProfileKind:'Absolute',
  chargingSchedule:[{id:1,startSchedule:start,duration:3600,chargingRateUnit:'W',
    chargingSchedulePeriod:[{startPeriod:0,limit:4000},{startPeriod:1800,limit:2000}]}]}});
out.local_generation_cleared=await gw('/ocpp/2.1/smartcharging/clearChargingProfile'+q,{chargingProfileId:9100});
await sleep(2000);
out.cleared=await call('c1','ClearedChargingLimit',{chargingLimitSource:'EMS',evseId:1});
await sleep(2000);
out.after=await gw('/lab/charging-limits');
out.policy=(await gw('/lab/control-policy')).body?.local_energy;
out.received=received.filter(m=>['SetChargingProfile','ClearChargingProfile'].includes(m.action));
ws.terminate();
console.log(JSON.stringify(out));
"""


def ems_trial(docker, request, server_options, values, tmp):
    password, token = "Ems-" + secrets.token_urlsafe(24)[:28], secrets.token_hex(32)
    values.extend([password, token])
    options = dict(server_options, plugfest_enabled=True,
                   plugfest_stations=[{"id": STATION, "password": password}],
                   command_control_enabled=True, command_token=token, open_admission_enabled=True,
                   command_station_id=STATION, command_real_stations_enabled=True)
    p = tmp / "lab-server.json"
    p.write_text(json.dumps(options)); p.chmod(0o600)
    docker("cp", str(p), "lab-server:/data/options.json")
    docker("restart", "lab-server")
    for _ in range(90):
        try:
            if request("/lab/status")[1].get("plugfest_stations") == [STATION]:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise AssertionError("EMS station listener activation failed")
    r = subprocess.run(["docker", "exec", "-i", "lab-server", "node", "--input-type=module", "-e", STATION_SCRIPT],
                       input=json.dumps({"id": STATION, "password": password, "token": token}),
                       text=True, capture_output=True, timeout=120)
    if r.returncode:
        raise AssertionError("EMS station script failed: " + r.stderr[-500:])
    out = json.loads(r.stdout.strip().splitlines()[-1])
    text = json.dumps(out)
    for secret in values:
        text = text.replace(secret, "[redacted]")
    print(text)
    assert out["boot"].get("status") == "Accepted", out["boot"]
    assert out["before"]["status"] == 200 and out["before"]["body"]["active"] == [], out["before"]
    assert out["notify"] == {}, out["notify"]
    active = out["reported"]["body"]["active"]
    assert out["reported"]["status"] == 200 and len(active) == 1, out["reported"]
    assert active[0]["source"] == "EMS" and active[0]["local_generation"] is True and active[0]["evse_id"] == 1, active
    assert active[0]["schedule"][0]["chargingSchedulePeriod"] == [{"startPeriod": 0, "limit": 3000}], active
    assert out["local_generation"]["status"] == 200, out["local_generation"]
    assert out["local_generation_cleared"]["status"] == 200, out["local_generation_cleared"]
    sent = [m for m in out["received"] if m["action"] == "SetChargingProfile"]
    assert sent and sent[0]["payload"]["chargingProfile"]["chargingProfilePurpose"] == "LocalGeneration", out["received"]
    assert any(m["action"] == "ClearChargingProfile" and m["payload"].get("chargingProfileId") == 9100
               for m in out["received"]), out["received"]
    assert out["cleared"] == {}, out["cleared"]
    after = out["after"]["body"]
    assert out["after"]["status"] == 200 and after["active"] == [], out["after"]
    assert after["recent"][0]["cleared_at"] and after["recent"][0]["active"] is False, after
    assert out["policy"]["operation_modes"][-1] == "LocalLoadBalancing", out["policy"]
    return out
