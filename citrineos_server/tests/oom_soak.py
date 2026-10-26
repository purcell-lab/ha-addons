"""One-off soak experiment: does an empty-identity station row and/or the HA
integration's setup-retry load drive CitrineOS heap growth to OOM?

Disposable CI only (citrineos-oom-soak.yml). Never contacts a real charger or
Home Assistant. Starts the private stack like stack_smoke.py, with the Green's
relevant options, then samples the upstream server child (node dist/index.js)
every SAMPLE_S seconds for SOAK_MINUTES.

Scenario (SCENARIO env):
  control                    stack + native lab simulator, nothing else
  polling                    + integration setup-retry emulation every POLL_S
  empty-row                  + ChargingStations row with ocppConnectionName ''
                               (tenant 1, one Evse) inserted while the server
                               is stopped, then started (as the Green restarted)
  empty-row-live             as empty-row, inserted after the server is up
  empty-row-polling          empty-row + polling
  empty-row-online-polling   empty row marked isOnline/ocpp2.0.1 + polling
  empty-ws-polling           the row is created naturally: a websocket upgrade
                               at path '/' on the Plugfest listener (open
                               admission), then restart + polling
LOGLEVEL env: upstream log level for the soak (the App uses 4 = warn; 3 = info
shows the router's re-emit lines). Applied by copying a launch.mjs with only
that constant changed into the disposable container; the App is unchanged.
Outputs oom-soak/<scenario>.{csv,json} and a redacted server log.
"""
import csv
import json
import os
from pathlib import Path
import re
import secrets
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = os.environ.get("SCENARIO", "control")
SOAK_MINUTES = float(os.environ.get("SOAK_MINUTES", "22"))
SAMPLE_S = int(os.environ.get("SAMPLE_S", "30"))
POLL_S = float(os.environ.get("POLL_S", "5"))
LOGLEVEL = int(os.environ.get("LOGLEVEL", "3"))
OUT = Path(os.environ.get("OUT_DIR", "oom-soak"))
OUT.mkdir(exist_ok=True)
TMP = Path("/tmp/citrine-oom-soak")
TMP.mkdir(exist_ok=True, mode=0o700)

POLLING = SCENARIO.endswith("polling")
EMPTY = {"empty-row": "before", "empty-row-polling": "before", "empty-row-online-polling": "before-online",
         "empty-row-live": "after", "empty-ws-polling": "websocket",
         "empty-ws-held-polling": "websocket", "empty-ws-reconnect-polling": "websocket"}.get(SCENARIO)
# A client at path '/' during the soak: held open (silent), or reconnecting
# every 20 s (a charger in a reconnect loop).
EMPTY_CLIENT = {"empty-ws-held-polling": "held", "empty-ws-reconnect-polling": "reconnect"}.get(SCENARIO)
assert SCENARIO in ("control", "polling", "empty-row", "empty-row-live", "empty-row-polling",
                    "empty-row-online-polling", "empty-ws-polling", "empty-ws-held-polling",
                    "empty-ws-reconnect-polling"), SCENARIO

db, broker, hasura, token, command, operator = (secrets.token_hex(32) for _ in range(6))
simulator_password = secrets.token_hex(20)
values = [db, broker, hasura, token, command, operator, simulator_password]
names = ["lab-db", "lab-broker", "lab-hasura", "lab-server"]
server = {
    "mode": "isolated", "database_host": "lab-db", "database_password": db,
    "broker_host": "lab-broker", "broker_password": broker, "hasura_host": "lab-hasura",
    "hasura_secret": hasura, "api_token": token,
    # The Green's relevant options (command station offline in CI).
    "simulator_enabled": True, "simulator_password": simulator_password,
    "open_admission_enabled": True,
    "command_control_enabled": True, "command_token": command,
    "command_station_id": "SIM-EV-EVEREST-V2G-03",
    "price_commands_enabled": True, "der_commands_enabled": True,
    "plugfest_enabled": True, "plugfest_open_admission": True, "plugfest_stations": [],
    "operator_ui_enabled": True, "operator_token": operator,
    "device_model_reports": True,
}
options = [{"password": db}, {"password": broker},
           {"database_host": "lab-db", "database_password": db, "admin_secret": hasura}, server]


def docker(*args, check=True, timeout=120):
    return subprocess.run(["docker", *args], check=check, text=True, capture_output=True,
                          timeout=timeout).stdout


def redact(text):
    for secret in values:
        text = text.replace(secret, "[redacted]")
    return text


def request(path, body=None, auth=True):
    headers = {"Authorization": "Bearer " + token} if auth else {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    code = """
    let s=''; for await (const c of process.stdin) s+=c;
    const x=JSON.parse(s);
    const r=await fetch('http://127.0.0.1:8080'+x.path,{
      method:x.body===null?'GET':'POST',headers:x.headers,
      body:x.body===null?undefined:JSON.stringify(x.body),signal:AbortSignal.timeout(10000)});
    console.log(JSON.stringify([r.status,await r.json()]));
    """
    r = subprocess.run(["docker", "exec", "-i", "lab-server", "node", "--input-type=module", "-e", code],
                       input=json.dumps({"path": path, "headers": headers, "body": body}),
                       text=True, capture_output=True, timeout=20)
    if r.returncode:
        raise RuntimeError("Private probe not ready")
    return json.loads(r.stdout)


def psql(sql):
    return docker("exec", "lab-db", "psql", "-U", "citrine", "-d", "citrine", "-Atc", sql).strip()


def wait_ready(label, seconds=300):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if request("/lab/status")[0] == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise AssertionError(label + " readiness timeout")


def child_pid():
    out = docker("exec", "lab-server", "sh", "-c",
                 # The node process whose argv is exactly node .../dist/index.js
                 # (not this shell, whose own command line names the file).
                 "for p in /proc/[0-9]*; do case \"$(tr '\\0' ' ' < $p/cmdline 2>/dev/null)\" in "
                 "'node '*/dist/index.js' ') echo ${p#/proc/};; esac; done", check=False).split()
    return out[0] if out else None


def child_mem(pid):
    if not pid:
        return None, None
    out = docker("exec", "lab-server", "sh", "-c", f"grep -E '^Vm(RSS|HWM):' /proc/{pid}/status",
                 check=False)
    vals = dict(re.findall(r"^(Vm\w+):\s+(\d+) kB", out, re.M))
    rss = int(vals["VmRSS"]) / 1024 if "VmRSS" in vals else None
    hwm = int(vals["VmHWM"]) / 1024 if "VmHWM" in vals else None
    return rss, hwm


def container_mb():
    out = docker("stats", "--no-stream", "--format", "{{.MemUsage}}", "lab-server", check=False).strip()
    m = re.match(r"([\d.]+)\s*([KMG]i?B)", out)
    if not m:
        return None
    scale = {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "KB": 1 / 1000, "MB": 1, "GB": 1000}[m.group(2)]
    return float(m.group(1)) * scale


def server_logs():
    r = subprocess.run(["docker", "logs", "lab-server"], text=True, capture_output=True)
    return redact(r.stdout + r.stderr)


PATTERNS = {"oom": r"JavaScript heap out of memory", "mark_compact": r"Ineffective mark-compacts",
            "reemitting": r"Re-emitting", "waits_behind": r"waits behind it",
            "dead_lettering": r"Dead-lettering", "connection_not_found": r"ConnectionNotFound|not found for identifier|No connection",
            "upstream_exited": r"Upstream server exited", "empty_identifier": r"\b1:(\s|$|[,'\"\]])"}


def log_counts(text):
    return {k: len(re.findall(p, text)) for k, p in PATTERNS.items()}


def queues():
    out = docker("exec", "lab-broker", "rabbitmqctl", "list_queues", "-q", "--no-table-headers",
                 "name", "messages", "consumers", check=False, timeout=60)
    rows = [line.split("\t") for line in out.strip().splitlines() if "\t" in line]
    total = sum(int(r[1]) for r in rows if len(r) > 1 and r[1].isdigit())
    top = sorted(((int(r[1]), r[0]) for r in rows if len(r) > 1 and r[1].isdigit()), reverse=True)[:5]
    return {"queues": len(rows), "messages": total, "top": [f"{n}={m}" for m, n in top]}


POLLER = r"""
let s=''; for await (const c of process.stdin) s+=c;
const x=JSON.parse(s);
const h={Authorization:'Bearer '+x.token};
const counts={cycles:0,errors:0,codes:{}};
async function call(p,opt={}){
  try{const r=await fetch('http://127.0.0.1:8080'+p,{method:opt.body?'POST':'GET',
      headers:{...h,...(opt.body?{'Content-Type':'application/json'}:{})},body:opt.body,signal:AbortSignal.timeout(10000)});
    await r.text();const k=p.split('?')[0]+' '+r.status;counts.codes[k]=(counts.codes[k]||0)+1;}
  catch{counts.errors++;}
}
for(;;){
  // As the integration's setup: policy, status, readiness, then discovery as ha_reader.
  await call('/lab/control-policy');await call('/lab/status');await call('/health/ready');
  for(const q of x.queries)await call('/v1/graphql',{body:JSON.stringify({query:q,variables:{tenantId:1}})});
  counts.cycles++;console.log(JSON.stringify(counts));
  await new Promise(r=>setTimeout(r,x.interval*1000));
}
"""


def start_poller():
    queries = [(ROOT / "citrineos_server/tests" / f).read_text() for f in ("discovery.graphql", "device-model.graphql")]
    p = subprocess.Popen(["docker", "exec", "-i", "lab-server", "node", "--input-type=module", "-e", POLLER],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    p.stdin.write(json.dumps({"token": token, "queries": queries, "interval": POLL_S}))
    p.stdin.close()
    os.set_blocking(p.stdout.fileno(), False)
    return p


def poller_counts(p, last):
    try:
        chunk = p.stdout.read() or ""
    except Exception:
        chunk = ""
    lines = [line for line in chunk.splitlines() if line.startswith("{")]
    return json.loads(lines[-1]) if lines else last


EMPTY_WS = r"""
import {createRequire} from 'node:module';
const r=createRequire('/usr/local/apps/citrineos/apps/ocpp-server/package.json');
const WebSocket=r(r.resolve('ws'));
const out={};
const ws=new WebSocket('ws://127.0.0.1:8083/',['ocpp2.0.1'],{handshakeTimeout:8000});
ws.on('unexpected-response',(_q,res)=>{out.status=res.statusCode;});
ws.on('open',()=>{out.open=true;out.protocol=ws.protocol;});
ws.on('message',m=>{out.messages=(out.messages||0)+1;out.last=m.toString().slice(0,300);});
ws.on('error',e=>{out.error=String(e.message||e);});
ws.on('close',(c)=>{out.close=c;});
await new Promise(r=>setTimeout(r,30000));
try{ws.close();}catch{}
await new Promise(r=>setTimeout(r,3000));
console.log(JSON.stringify(out));process.exit(0);
"""

EMPTY_CLIENT_JS = r"""
import {createRequire} from 'node:module';
const r=createRequire('/usr/local/apps/citrineos/apps/ocpp-server/package.json');
const WebSocket=r(r.resolve('ws'));
const mode=process.argv[1];
const c={opened:0,refused:0,errors:0,closes:0,messages:0};
const report=()=>console.log(JSON.stringify(c));
setInterval(report,30000);
function connect(){
  const ws=new WebSocket('ws://127.0.0.1:8083/',['ocpp2.0.1'],{handshakeTimeout:8000});
  let t;
  ws.on('unexpected-response',()=>{c.refused++;});
  ws.on('open',()=>{c.opened++;if(mode==='reconnect')t=setTimeout(()=>ws.close(),15000);});
  ws.on('message',()=>{c.messages++;});
  ws.on('error',()=>{c.errors++;});
  ws.on('close',()=>{c.closes++;clearTimeout(t);setTimeout(connect,5000);});
}
connect();
"""


def start_empty_client():
    p = subprocess.Popen(["docker", "exec", "lab-server", "node", "--input-type=module", "-e", EMPTY_CLIENT_JS,
                          EMPTY_CLIENT], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    os.set_blocking(p.stdout.fileno(), False)
    return p


EMPTY_ROWS_SQL = ('SELECT s.id, s."tenantId", s."isOnline", s.protocol, '
                  '(SELECT count(*) FROM "Evses" e WHERE e."stationId"=s.id) '
                  'FROM "ChargingStations" s WHERE s."ocppConnectionName"=\'\'')


def insert_empty(online=False):
    station = psql('INSERT INTO "ChargingStations" ("ocppConnectionName","tenantId","isOnline",'
                   + ('protocol,' if online else '') + '"use16StatusNotification0","createdAt","updatedAt") '
                   "VALUES ('',1," + ("true,'ocpp2.0.1'," if online else "false,") + "true,NOW(),NOW()) RETURNING id")
    station = station.splitlines()[0]
    psql('INSERT INTO "Evses" ("stationId","tenantId","evseTypeId",removed,"createdAt","updatedAt") '
         f"VALUES ({int(station)},1,1,false,NOW(),NOW())")
    return station


def slope(points):
    """Least-squares MB/min over (minutes, MB) points."""
    pts = [(t, v) for t, v in points if v is not None]
    if len(pts) < 3:
        return None
    mt = statistics.mean(t for t, _ in pts)
    mv = statistics.mean(v for _, v in pts)
    den = sum((t - mt) ** 2 for t, _ in pts)
    return sum((t - mt) * (v - mv) for t, v in pts) / den if den else None


report = {"scenario": SCENARIO, "loglevel": LOGLEVEL, "soak_minutes": SOAK_MINUTES,
          "sample_s": SAMPLE_S, "polling": POLLING, "empty_row": EMPTY, "result": "running"}
samples = []
poller = None
client = None
try:
    docker("network", "create", "--internal", "citrine-ci")
    for name, app, config in zip(names, ["database", "broker", "hasura", "server"], options):
        docker("create", "--name", name, "--network", "citrine-ci", "--memory", "1536m",
               "--restart", "unless-stopped", "citrine-" + app + ":test")
        p = TMP / (name + ".json")
        p.write_text(json.dumps(config)); p.chmod(0o600)
        docker("cp", str(p), name + ":/data/options.json")
        if name == "lab-server":
            launch = TMP / "launch.mjs"
            docker("cp", "lab-server:/opt/citrine-ha/launch.mjs", str(launch))
            text = launch.read_text()
            assert text.count("LOGLEVEL:4,") == 1, "launch.mjs log level constant moved"
            launch.write_text(text.replace("LOGLEVEL:4,", f"LOGLEVEL:{LOGLEVEL},"))
            docker("cp", str(launch), "lab-server:/opt/citrine-ha/launch.mjs")
        docker("start", name)
    wait_ready("First start")
    docker("create", "--name", "lab-simulator", "--network", "citrine-ci", "citrine-simulator:test")
    names.append("lab-simulator")
    p = TMP / "lab-simulator.json"
    p.write_text(json.dumps({"backend_url": "ws://lab-server:8081", "charge_point_id": "SIM-CITRINE-LAB-01",
                             "acknowledge_test_isolation": True, "password": simulator_password}))
    p.chmod(0o600)
    docker("cp", str(p), "lab-simulator:/data/options.json")
    docker("start", "lab-simulator")
    time.sleep(20)
    if EMPTY == "websocket":
        r = subprocess.run(["docker", "exec", "lab-server", "node", "--input-type=module", "-e", EMPTY_WS],
                           text=True, capture_output=True, timeout=60)
        report["empty_ws_probe"] = redact(r.stdout.strip()[-1000:])
        report["empty_rows_after_ws"] = psql(EMPTY_ROWS_SQL)
    # Every scenario restarts the server once, so uptime is comparable; the
    # Green crashed after restarts with the empty row already present.
    docker("stop", "--time", "30", "lab-server")
    if EMPTY in ("before", "before-online"):
        report["empty_station_id"] = insert_empty(online=EMPTY == "before-online")
    docker("start", "lab-server")
    t0 = time.monotonic()
    report["soak_started_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    wait_ready("Soak start")
    report["ready_after_s"] = round(time.monotonic() - t0, 1)
    if EMPTY == "after":
        report["empty_station_id"] = insert_empty()
    report["empty_rows"] = psql(EMPTY_ROWS_SQL)
    report["stations"] = psql('SELECT id, "ocppConnectionName", "isOnline", protocol FROM "ChargingStations" ORDER BY id')
    if POLLING:
        poller = start_poller()
    if EMPTY_CLIENT:
        client = start_empty_client()
    client_counts = {}
    polled = {}
    oom_at = None
    restarts0 = int(docker("inspect", "-f", "{{.RestartCount}}", "lab-server").strip() or 0)
    pids = []
    i = 0
    while time.monotonic() - t0 < SOAK_MINUTES * 60:
        i += 1
        target = t0 + i * SAMPLE_S
        time.sleep(max(0, target - time.monotonic()))
        elapsed = time.monotonic() - t0
        state = docker("inspect", "-f", "{{.State.Status}} {{.RestartCount}}", "lab-server", check=False).split()
        pid = child_pid()
        rss, hwm = child_mem(pid)
        row = {"elapsed_s": round(elapsed), "child_pid": pid, "child_rss_mb": rss, "child_hwm_mb": hwm,
               "container_mb": container_mb(), "state": state[0] if state else None,
               "restarts": (int(state[1]) - restarts0) if len(state) > 1 else None}
        if pid and pid not in pids:
            pids.append(pid)
        if client:
            client_counts = poller_counts(client, client_counts)
            row["empty_client_opened"] = client_counts.get("opened")
            if client.poll() is not None and row["state"] == "running":
                client = start_empty_client()
        if poller:
            polled = poller_counts(poller, polled)
            row["poll_cycles"] = polled.get("cycles")
            if poller.poll() is not None and row["state"] == "running":
                poller = start_poller()
        if i % 4 == 0:
            counts = log_counts(server_logs())
            row.update({k: counts[k] for k in ("oom", "reemitting", "waits_behind", "dead_lettering")})
            q = queues()
            row["queue_count"], row["queue_messages"] = q["queues"], q["messages"]
            if counts["oom"] and oom_at is None:
                oom_at = elapsed
        if oom_at is None and (row["restarts"] or 0) > 0:
            oom_at = elapsed
        samples.append(row)
        print(json.dumps(row), flush=True)
    logs = server_logs()
    counts = log_counts(logs)
    if counts["oom"] and oom_at is None:
        oom_at = samples[-1]["elapsed_s"]
    # Slope over the first child process only (until any crash), after 2 min of warm-up.
    first = [s for s in samples if s["child_pid"] == (pids[0] if pids else None)]
    warm = [(s["elapsed_s"] / 60, s["child_rss_mb"]) for s in first if s["elapsed_s"] >= 120]
    rss_values = [s["child_rss_mb"] for s in samples if s["child_rss_mb"] is not None]
    report.update({
        "result": "completed", "samples": len(samples), "child_pids": len(pids),
        "start_mb": rss_values[0] if rss_values else None, "end_mb": rss_values[-1] if rss_values else None,
        "max_mb": max(rss_values) if rss_values else None,
        "slope_mb_per_min": slope(warm), "oom": bool(counts["oom"]) or len(pids) > 1,
        "time_to_oom_s": oom_at, "log_counts": counts, "queues_end": queues(),
        "poller_end": polled, "empty_client_end": client_counts, "restarts": samples[-1]["restarts"] if samples else None,
        "empty_rows_end": psql(EMPTY_ROWS_SQL),
    })
except Exception as error:
    report.update(result="failed", error_type=type(error).__name__, error=redact(str(error))[:2000])
    raise
finally:
    for proc in (poller, client):
        if proc:
            proc.kill()
    try:
        logs = server_logs()
        (OUT / f"{SCENARIO}-server.log").write_text(logs)
        print(logs[-20000:])
    except Exception:
        pass
    keys = sorted({k for s in samples for k in s})
    with open(OUT / f"{SCENARIO}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(samples)
    report["series"] = samples
    (OUT / f"{SCENARIO}.json").write_text(redact(json.dumps(report, indent=2)))
    brief = {k: v for k, v in report.items() if k != "series"}
    print(redact(json.dumps(brief, indent=2)))
    for name in names:
        try:
            docker("rm", "-f", name)
        except Exception:
            pass
    try:
        docker("network", "rm", "citrine-ci")
    except Exception:
        pass
