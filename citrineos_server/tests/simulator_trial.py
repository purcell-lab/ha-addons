"""Exercise the real MicroOCPP binary against pinned CitrineOS in private CI."""
import json
import time

def trial(docker, request, password):
    def api(path, body=None):
        # Only synthetic connector 1, in the dedicated CI container.
        code = """import urllib.request,json,sys
x=json.load(sys.stdin)
r=urllib.request.Request('http://127.0.0.1:8000'+x['path'],
 data=json.dumps(x['body']).encode() if x['body'] is not None else None,
 headers={'Content-Type':'application/json'})
with urllib.request.urlopen(r,timeout=3) as response: print(response.read().decode())
"""
        import subprocess
        p=subprocess.run(["docker","exec","-i","lab-simulator","python3","-c",code],
            input=json.dumps({"path":path,"body":body}),text=True,capture_output=True,check=True)
        return json.loads(p.stdout)
    def gql(query):
        status,data=request("/v1/graphql",body={"query":query})
        assert status==200 and not data.get("errors"),data
        return data["data"]
    def until(fn,label,seconds=70):
        until_at=time.monotonic()+seconds
        while time.monotonic()<until_at:
            try:
                value=fn()
                if value:return value
            except Exception:
                pass
            time.sleep(2)
        raise AssertionError(label+" timed out")
    until(lambda:gql('query { Boots { status lastBootTime } }')["Boots"][0]["lastBootTime"],"Boot")
    assert gql('query { Boots { status } }')["Boots"][0]["status"]=="Accepted"
    assert gql('query { ChargingStations { isOnline protocol } }')["ChargingStations"][0]["isOnline"]
    before=api("/api/connector/1/meter")
    assert before["power"]==0
    start_energy=before["energy"]
    try:
        api("/api/connector/1/evse",{k:True for k in ("evPlugged","evsePlugged","evReady","evseReady")})
        api("/api/connector/1/transaction",{"idTag":"C17E0001"})
        live=until(lambda:(m if (m:=api("/api/connector/1/meter"))["power"]>0 else None),"Positive power")
        until(lambda:any(t["isActive"] for t in gql('query { Transactions { isActive } }')["Transactions"]),"Active transaction")
        samples=until(lambda:(rows if (rows:=gql('query { MeterValues(order_by:{timestamp:desc},limit:15) { sampledValue } }')["MeterValues"])
            and any(float(s["value"])>0 and s.get("measurand")=="Power.Active.Import" for r in rows for s in r["sampledValue"]) else None),"CSMS power")
        time.sleep(12)
        final=api("/api/connector/1/meter")
        assert final["energy"]>start_energy
    finally:
        api("/api/connector/1/evse",{k:False for k in ("evPlugged","evsePlugged","evReady","evseReady")})
    until(lambda:api("/api/connector/1/meter")["power"]==0,"Zero stop power")
    until(lambda:any(t["eventType"]=="Ended" for t in gql('query { TransactionEvents { eventType } }')["TransactionEvents"]),"Ended event")
    tx=until(lambda:(rows if (rows:=gql('query { Transactions { transactionId isActive totalKwh endTime } }')["Transactions"])
        and all(not t["isActive"] and t["endTime"] for t in rows) else None),"Closed transaction")
    assert float(tx[0]["totalKwh"])>0,tx
    print(json.dumps({"native_simulator":"passed","power_w":live["power"],"energy_delta_wh":final["energy"]-start_energy,"transactions":tx}))
