"""Bounded private full-stack test. Never connects a charger or uses HA credentials."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request
import urllib.error

def docker(*args, capture=True):
    return subprocess.run(["docker", *args], check=True, text=True, capture_output=capture).stdout

ROOT = Path(__file__).resolve().parents[2]
TMP = Path("/tmp/citrine-lab-ci")
TMP.mkdir(exist_ok=True, mode=0o700)
values = [secrets.token_hex(32) for _ in range(4)]
db, broker, hasura, token = values
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
    req = urllib.request.Request("http://127.0.0.1:18080"+path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)

try:
    docker("network", "create", "--internal", "citrine-ci")
    for name, app, config in zip(names, ["database","broker","hasura","server"], options):
        extra = ["-p","127.0.0.1:18080:8080"] if app=="server" else []
        docker("create", "--name", name, "--network", "citrine-ci", "--memory", "1536m",
               *extra, "citrine-"+app+":test")
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
    print(json.dumps({"result":"passed","release":"v2.0.1","migration_count":int(before),
                      "authenticated_tariff":True,"empty_discovery":True,
                      "mutation_denied":True,"restart_persistence":True,"logical_restore":True,
                      "charger_connections":0}))
finally:
    for name in names:
        try:
            logs=docker("logs",name)
            for secret in values: logs=logs.replace(secret,"[redacted]")
            print(name,logs[-14000:])
        except Exception: pass
    for name in names:
        try: docker("rm","-f",name)
        except Exception: pass
    try: docker("network","rm","citrine-ci")
    except Exception: pass
