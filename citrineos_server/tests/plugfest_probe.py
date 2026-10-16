"""Plugfest listener check for stack_smoke.py (TEST_PLUGFEST=1).

Enables the opt-in Security Profile 1 listener on port 8083 with one
provisioned station, then connects from inside the server container (the
CI network is internal) with the upstream `ws` client:
- the provisioned identity and password: BootNotification is Accepted;
- the same identity with a wrong password: the upgrade is refused;
- an unknown identity: the upgrade is refused;
- the same station offering OCPP 1.6 only: a 1.6 BootNotification is
  Accepted; offering all three, 2.1 is chosen;
- after the station is removed from the options and the server restarts,
  its old password is refused;
- with plugfest_open_admission: an unknown identity without credentials
  boots on 2.1, 2.0.1 and 1.6, and 2.1 is preferred.
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
// password null: no Authorization header. The boot payload follows the
// protocol the server chose.
function attempt(id,password,protocols=['ocpp2.0.1']){
  return new Promise(resolve=>{
    const headers=password===null?{}:{Authorization:'Basic '+Buffer.from(id+':'+password).toString('base64')};
    const ws=new WebSocket('ws://127.0.0.1:8083/'+id,protocols,{headers,handshakeTimeout:8000});
    const done=v=>{try{ws.terminate();}catch{}resolve(v);};
    ws.on('unexpected-response',(_q,res)=>done({connected:false,status:res.statusCode}));
    ws.on('error',e=>done({connected:false,error:String(e.message||e)}));
    ws.on('open',()=>ws.send(JSON.stringify([2,'pf-1','BootNotification',ws.protocol==='ocpp1.6'
      ?{chargePointVendor:'purcell-lab',chargePointModel:'ci-probe'}
      :{chargingStation:{model:'ci-probe',vendorName:'purcell-lab'},reason:'PowerUp'}])));
    ws.on('message',m=>{const f=JSON.parse(m.toString());
      if(f[0]===3&&f[1]==='pf-1')done({connected:true,protocol:ws.protocol,boot:f[2].status});
      if(f[0]===4&&f[1]==='pf-1')done({connected:true,protocol:ws.protocol,error:f[2]});});
    setTimeout(()=>done({connected:false,error:'timeout'}),15000);
  });
}
const all=['ocpp1.6','ocpp2.0.1','ocpp2.1'];
console.log(JSON.stringify(x.open?{
  v21:await attempt('PF-OPEN-21',null,['ocpp2.1']),
  v201:await attempt('PF-OPEN-201',null,['ocpp2.0.1']),
  v16:await attempt('PF-OPEN-16',null,['ocpp1.6']),
  preferred:await attempt('PF-OPEN-ALL',null,all),
}:{
  good:await attempt(x.id,x.password),
  wrong:await attempt(x.id,x.password.slice(0,-1)+(x.password.endsWith('A')?'B':'A')),
  unknown:await attempt('PF-UNKNOWN-99',x.password),
  v16:await attempt(x.id,x.password,['ocpp1.6']),
  preferred:await attempt(x.id,x.password,all),
}));
"""


def probe(station, password, open_admission=False):
    r = subprocess.run(
        ["docker", "exec", "-i", "lab-server", "node", "--input-type=module", "-e", PROBE],
        input=json.dumps({"id": station, "password": password, "open": open_admission}),
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
    assert result["good"] == {"connected": True, "protocol": "ocpp2.0.1", "boot": "Accepted"}, result["good"]
    assert not result["wrong"]["connected"], "wrong password was admitted"
    assert not result["unknown"]["connected"], "unknown station was admitted"
    assert result["v16"] == {"connected": True, "protocol": "ocpp1.6", "boot": "Accepted"}, result["v16"]
    assert result["preferred"]["protocol"] == "ocpp2.1", result["preferred"]
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
    assert not revoked["v16"]["connected"], "removed station could still log in on 1.6"
    # Open admission: any identity, no credentials, 2.1 > 2.0.1 > 1.6.
    options = dict(server_options, plugfest_enabled=True, plugfest_open_admission=True,
                   plugfest_stations=[])
    p.write_text(json.dumps(options)); p.chmod(0o600)
    docker("cp", str(p), "lab-server:/data/options.json")
    docker("restart", "lab-server")
    for _ in range(90):
        try:
            if request("/lab/status")[1].get("plugfest_open_admission") is True:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise AssertionError("Plugfest open admission activation failed")
    opened = probe("PF-OPEN", None, open_admission=True)
    for key, protocol in (("v21", "ocpp2.1"), ("v201", "ocpp2.0.1"), ("v16", "ocpp1.6"),
                          ("preferred", "ocpp2.1")):
        assert opened[key] == {"connected": True, "protocol": protocol, "boot": "Accepted"}, (key, opened[key])
    print(json.dumps({"plugfest_listener": "passed", "accepted_boot": True,
                      "wrong_password_refused": True, "unknown_station_refused": True,
                      "ocpp16_boot": True, "ocpp21_preferred": True,
                      "removed_station_revoked": True, "open_admission_all_versions": True}))
