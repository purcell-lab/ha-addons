"""Plugfest listener check for stack_smoke.py (TEST_PLUGFEST=1).

Enables the opt-in Security Profile 1 listener on port 8083 with one
provisioned station, then connects from inside the server container (the
CI network is internal) with the upstream `ws` client:
- the provisioned identity and password: BootNotification is Accepted;
- the same identity with a wrong password: the upgrade is refused;
- an unknown identity: the upgrade is refused;
- after the station is removed from the options and the server restarts,
  its old password is refused.
No real charger is contacted.
"""
import json
import secrets
import subprocess
import time

STATION = "PF-CI-STATION-01"

PROBE = r"""
import {createRequire} from 'node:module';
const r=createRequire('/usr/local/apps/citrineos/apps/ocpp-server/package.json');
const WebSocket=r(r.resolve('ws'));
let s=''; for await (const c of process.stdin) s+=c;
const x=JSON.parse(s);
function attempt(id,password){
  return new Promise(resolve=>{
    const auth='Basic '+Buffer.from(id+':'+password).toString('base64');
    const ws=new WebSocket('ws://127.0.0.1:8083/'+id,['ocpp2.0.1'],{headers:{Authorization:auth},handshakeTimeout:8000});
    const done=v=>{try{ws.terminate();}catch{}resolve(v);};
    ws.on('unexpected-response',(_q,res)=>done({connected:false,status:res.statusCode}));
    ws.on('error',e=>done({connected:false,error:String(e.message||e)}));
    ws.on('open',()=>ws.send(JSON.stringify([2,'pf-1','BootNotification',
      {chargingStation:{model:'ci-probe',vendorName:'purcell-lab'},reason:'PowerUp'}])));
    ws.on('message',m=>{const f=JSON.parse(m.toString());
      if(f[0]===3&&f[1]==='pf-1')done({connected:true,boot:f[2].status});});
    setTimeout(()=>done({connected:false,error:'timeout'}),15000);
  });
}
console.log(JSON.stringify({
  good:await attempt(x.id,x.password),
  wrong:await attempt(x.id,x.password.slice(0,-1)+(x.password.endsWith('A')?'B':'A')),
  unknown:await attempt('PF-UNKNOWN-99',x.password),
}));
"""


def probe(station, password):
    r = subprocess.run(
        ["docker", "exec", "-i", "lab-server", "node", "--input-type=module", "-e", PROBE],
        input=json.dumps({"id": station, "password": password}),
        text=True, capture_output=True, timeout=90)
    if r.returncode:
        raise AssertionError("Plugfest probe failed to run")
    return json.loads(r.stdout.strip().splitlines()[-1])


def plugfest_trial(docker, request, server_options, values, tmp):
    password = "Pf-" + secrets.token_urlsafe(24)[:29]
    values.append(password)
    options = dict(server_options, plugfest_enabled=True,
                   plugfest_stations=[{"id": STATION, "password": password}])
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
        raise AssertionError("Plugfest listener activation failed")
    result = probe(STATION, password)
    assert result["good"] == {"connected": True, "boot": "Accepted"}, result["good"]
    assert not result["wrong"]["connected"], "wrong password was admitted"
    assert not result["unknown"]["connected"], "unknown station was admitted"
    # Removing the station from the options revokes its password on restart.
    other = "Pf-" + secrets.token_urlsafe(24)[:29]
    values.append(other)
    options["plugfest_stations"] = [{"id": "PF-CI-STATION-02", "password": other}]
    p.write_text(json.dumps(options)); p.chmod(0o600)
    docker("cp", str(p), "lab-server:/data/options.json")
    docker("restart", "lab-server")
    for _ in range(90):
        try:
            if request("/lab/status")[1].get("plugfest_stations") == ["PF-CI-STATION-02"]:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise AssertionError("Plugfest listener re-activation failed")
    revoked = probe(STATION, password)
    assert not revoked["good"]["connected"], "removed station could still log in"
    print(json.dumps({"plugfest_listener": "passed", "accepted_boot": True,
                      "wrong_password_refused": True, "unknown_station_refused": True,
                      "removed_station_revoked": True}))
