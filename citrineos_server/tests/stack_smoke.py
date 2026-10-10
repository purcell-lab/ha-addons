"""Bounded private full-stack test. Never connects a charger or uses HA credentials."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

def docker(*args, capture=True):
    return subprocess.run(["docker", *args], check=True, text=True, capture_output=capture).stdout

ROOT = Path(__file__).resolve().parents[2]
TMP = Path("/tmp/citrine-lab-ci")
TMP.mkdir(exist_ok=True, mode=0o700)
values = [secrets.token_hex(32) for _ in range(5)]
db, broker, hasura, token, simulator_password = values
names = ["lab-db", "lab-broker", "lab-hasura", "lab-server"]
options = [
    {"password": db},
    {"password": broker},
    {"database_host": "lab-db", "database_password": db, "admin_secret": hasura},
    {"mode": "isolated", "database_host": "lab-db", "database_password": db,
     "broker_host": "lab-broker", "broker_password": broker, "hasura_host": "lab-hasura",
     "hasura_secret": hasura, "api_token": token},
]
def request(path, body=None, auth=True, extra=None):
    headers = {"Authorization": "Bearer " + token} if auth else {}
    headers.update(extra or {})
    if body is not None:
        headers["Content-Type"] = "application/json"
    # --internal networks intentionally cannot be tested via host-published ports.
    # Credentials travel on stdin, never in process arguments or log output.
    code = """
    let s=''; for await (const c of process.stdin) s+=c;
    const x=JSON.parse(s);
    const r=await fetch('http://127.0.0.1:8080'+x.path,{
      method:x.body===null?'GET':'POST',headers:x.headers,
      body:x.body===null?undefined:JSON.stringify(x.body),signal:AbortSignal.timeout(10000)});
    console.log(JSON.stringify([r.status,await r.json()]));
    """
    r=subprocess.run(["docker","exec","-i","lab-server","node","--input-type=module","-e",code],
                     input=json.dumps({"path":path,"headers":headers,"body":body}),
                     text=True,capture_output=True,timeout=20)
    if r.returncode:
        raise RuntimeError("Private probe not ready")
    return json.loads(r.stdout)

try:
    docker("network", "create", "--internal", "citrine-ci")
    for name, app, config in zip(names, ["database","broker","hasura","server"], options):
        docker("create", "--name", name, "--network", "citrine-ci", "--memory", "1536m",
               "citrine-"+app+":test")
        p=TMP/(name+".json")
        p.write_text(json.dumps(config)); p.chmod(0o600)
        docker("cp", str(p), name+":/data/options.json")
        docker("start",name)
    for _ in range(150):
        try:
            code,_=request("/health/ready",auth=False)
            if code==200:
                break
        except Exception:
            pass
        if docker("inspect","-f","{{.State.Running}}","lab-server").strip()!="true":
            raise AssertionError("Server exited before readiness")
        time.sleep(2)
    else:
        raise AssertionError("Stack readiness timeout")
    assert request("/lab/status")[1]["charger_listeners"] == 0
    assert request("/commands/tariff?tenantId=1",auth=False)[0] == 401
    assert request("/commands/tariff?tenantId=1",extra={"Authorization":"Bearer wrong"})[0] == 401
    assert request("/commands/tariff?tenantId=2")[0] == 403
    assert request("/commands/tariff?tenantId=1")[0] == 200
    assert request("/admin",body={})[0] == 403
    assert request("/v1/graphql",body={"query":"query { ChargingStations { id tenantId } }"},auth=False)[0] == 401
    query = (ROOT/"citrineos_server/tests/discovery.graphql").read_text()
    status,data=request("/v1/graphql",body={"query":query,"variables":{"tenantId":1}})
    assert status==200 and not data.get("errors"),data
    assert all(data["data"][key]==[] for key in ("ChargingStations","Connectors","Transactions")),data
    _,bad=request("/v1/graphql",body={"query":"mutation { delete_ChargingStations(where: {}) { affected_rows } }"})
    assert bad.get("errors"),bad
    _,bad=request("/v1/graphql",body={"query":"query { ChargingStations { basicAuthPassword } }"})
    assert bad.get("errors"),bad
    # Native API and OCPP listener are not reachable from a sibling container.
    docker("exec","lab-server","node","--input-type=module","-e",
           "import fs from 'node:fs';let r=fs.readFileSync('/proc/1/status','utf8');"
           "if(!/^Uid:\\s+1000\\s/m.test(r))process.exit(1);")
    before=docker("exec","lab-db","psql","-U","citrine","-d","citrine","-Atc",'SELECT count(*) FROM "SequelizeMeta"').strip()
    # Logical restore into a separate disposable database proves migrations survive backup.
    docker("exec","lab-db","bash","-c",
           "pg_dump -U citrine -d citrine -Fc -f /data/ci-restore.dump && "
           "createdb -U citrine ci_restore && "
           "pg_restore -U citrine -d ci_restore --no-owner /data/ci-restore.dump")
    restored=docker("exec","lab-db","psql","-U","citrine","-d","ci_restore","-Atc",'SELECT count(*) FROM "SequelizeMeta"').strip()
    assert int(before)>0 and before==restored
    docker("restart","lab-server")
    for _ in range(90):
        try:
            if request("/lab/status")[0]==200:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise AssertionError("Restart persistence failed")
    assert request("/commands/tariff?tenantId=1")[0]==200
    if os.environ.get("TEST_NATIVE_SIMULATOR")=="1":
        options[-1].update(simulator_enabled=True,simulator_password=simulator_password)
        p=TMP/"lab-server.json";p.write_text(json.dumps(options[-1]));p.chmod(0o600)
        docker("cp",str(p),"lab-server:/data/options.json")
        docker("restart","lab-server")
        for _ in range(60):
            try:
                if request("/lab/status")[1].get("charger_listeners")==1:break
            except Exception:pass
            time.sleep(2)
        else:raise AssertionError("Simulator listener activation failed")
        docker("create","--name","lab-simulator","--network","citrine-ci","citrine-simulator:test")
        names.append("lab-simulator")
        p=TMP/"lab-simulator.json"
        p.write_text(json.dumps({"backend_url":"ws://lab-server:8081","charge_point_id":"SIM-CITRINE-LAB-01",
            "acknowledge_test_isolation":True,"password":simulator_password}));p.chmod(0o600)
        docker("cp",str(p),"lab-simulator:/data/options.json")
        docker("start","lab-simulator")
        from simulator_trial import trial
        trial(docker,request,simulator_password)
    print(json.dumps({"result":"passed","release":"v2.0.1","migration_count":int(before),
                      "authenticated_tariff":True,"empty_discovery":True,
                      "mutation_denied":True,"restart_persistence":True,"logical_restore":True,
                      "native_simulator_test":os.environ.get("TEST_NATIVE_SIMULATOR")=="1"}))
finally:
    for name in names:
        try:
            log_result=subprocess.run(["docker","logs",name],text=True,capture_output=True)
            logs=log_result.stdout+log_result.stderr
            for secret in values: logs=logs.replace(secret,"[redacted]")
            print(name,logs[-14000:])
        except Exception: pass
    for name in names:
        try: docker("rm","-f",name)
        except Exception: pass
    try: docker("network","rm","citrine-ci")
    except Exception: pass
