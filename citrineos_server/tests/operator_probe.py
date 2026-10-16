"""Operator UI scope check for stack_smoke.py (TEST_OPERATOR=1).

Enables operator_ui_enabled and operator_commands_enabled with a separate
token, then checks through the gateway from inside the server container:
- GraphQL as operator_ro: upstream's relationships resolve, credential
  columns and webhook subscriptions are not exposed, and any mutation is
  refused by Hasura;
- the ha_reader path (api_token) is unchanged;
- commands outside the fixed set, or to unknown stations, are refused;
- a Reset sent to an online OCPP 2.0.1 probe station on the open listener
  (8082) reaches it and its Accepted reply comes back.
No real charger is contacted.
"""
import json
import secrets
import subprocess
import time

STATION = "PROBE-OPERATOR-01"

COMMAND_PROBE = r"""
import {createRequire} from 'node:module';
const r=createRequire('/usr/local/apps/citrineos/apps/ocpp-server/package.json');
const WebSocket=r(r.resolve('ws'));
let s=''; for await (const c of process.stdin) s+=c;
const x=JSON.parse(s);
const out={};
const ws=new WebSocket('ws://127.0.0.1:8082/'+x.id,['ocpp2.0.1'],{handshakeTimeout:8000});
const done=()=>{try{ws.terminate();}catch{}console.log(JSON.stringify(out));process.exit(0);};
setTimeout(done,40000);
ws.on('error',e=>{out.error=String(e.message||e);done();});
ws.on('open',()=>ws.send(JSON.stringify([2,'b1','BootNotification',
  {chargingStation:{model:'operator-probe',vendorName:'purcell-lab'},reason:'PowerUp'}])));
ws.on('message',async m=>{
  const f=JSON.parse(m.toString());
  if(f[0]===3&&f[1]==='b1'){
    out.boot=f[2].status;
    ws.send(JSON.stringify([2,'s1','StatusNotification',{timestamp:new Date().toISOString(),
      connectorStatus:'Available',evseId:1,connectorId:1}]));
    // Let CitrineOS record the station online and its protocol.
    await new Promise(r=>setTimeout(r,4000));
    const res=await fetch('http://127.0.0.1:8080/ocpp/2.0.1/configuration/reset?identifier='+x.id+'&tenantId=1',{
      method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+x.token},
      body:JSON.stringify({type:'Immediate'}),signal:AbortSignal.timeout(20000)});
    out.command_status=res.status;out.command_body=await res.text();
    // CitrineOS answers once the request is queued; the CALL follows.
    for(let i=0;i<40&&!out.reset_received;i++)await new Promise(r=>setTimeout(r,250));
    done();
  } else if(f[0]===2){
    if(f[2]==='Reset'){out.reset_received=f[3];}
    ws.send(JSON.stringify([3,f[1],f[2]==='Reset'?{status:'Accepted'}:{}]));
  }
});
"""


def gql(request, token, query):
    return request("/v1/graphql", {"query": query}, auth=False,
                   extra={"Authorization": "Bearer " + token})


def operator_trial(docker, request, server_options, values, tmp):
    op = secrets.token_hex(32)
    values.append(op)
    options = dict(server_options, open_admission_enabled=True, operator_ui_enabled=True,
                   operator_token=op, operator_commands_enabled=True)
    p = tmp / "lab-server.json"
    p.write_text(json.dumps(options)); p.chmod(0o600)
    docker("cp", str(p), "lab-server:/data/options.json")
    docker("restart", "lab-server")
    for _ in range(90):
        try:
            if request("/lab/status")[1].get("operator_commands") is True:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise AssertionError("Operator scope activation failed")

    status, body = gql(request, op, "{ ChargingStations { id ocppConnectionName Evses { id Connectors { connectorId status } } Location { id } } Tenants { id name } }")
    assert status == 200 and "errors" not in body, body
    for q in ("{ Tenants { serverProfileOCPI } }", "{ Subscriptions { id } }",
              "mutation { delete_ChargingStations(where: {}) { affected_rows } }"):
        status, body = gql(request, op, q)
        assert "errors" in body, (q, body)
    status, body = request("/v1/graphql", {"query": "{ ChargingStations { id } }"})
    assert status == 200 and "errors" not in body, body
    status, _ = request("/lab/status", auth=False, extra={"Authorization": "Bearer " + op})
    assert status == 405, status
    status, _ = request("/ocpp/2.0.1/monitoring/setVariables?identifier=" + STATION + "&tenantId=1",
                        {"setVariableData": []}, auth=False, extra={"Authorization": "Bearer " + op})
    assert status == 403, status
    status, _ = request("/ocpp/2.0.1/configuration/reset?identifier=UNKNOWN-STATION&tenantId=1",
                        {"type": "Immediate"}, auth=False, extra={"Authorization": "Bearer " + op})
    assert status == 409, status

    r = subprocess.run(
        ["docker", "exec", "-i", "lab-server", "node", "--input-type=module", "-e", COMMAND_PROBE],
        input=json.dumps({"id": STATION, "token": op}), text=True, capture_output=True, timeout=90)
    if r.returncode:
        raise AssertionError("Operator command probe failed to run")
    result = json.loads(r.stdout.strip().splitlines()[-1])
    assert result.get("boot") == "Accepted", result
    assert result.get("reset_received") == {"type": "Immediate"}, result
    assert result.get("command_status") == 200, result
    print(json.dumps({"operator_scope": "passed", "graphql_relationships": True,
                      "secrets_hidden": True, "mutation_refused": True,
                      "ha_reader_unchanged": True, "command_routes_bounded": True,
                      "reset_delivered": True}))
