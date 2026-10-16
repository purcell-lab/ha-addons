import {createRequire} from 'node:module';
import {commandStation} from './control-policy.mjs';
const requireApp=createRequire('/usr/local/apps/citrineos/apps/ocpp-server/package.json');
const {Client}=createRequire(requireApp.resolve('@citrineos/dal'))('pg');
export async function seedSimulator(o) {
  // Parameterised, dedicated-lab-only bootstrap. No public API exposes SQL.
  const db=new Client({host:o.database_host,user:'citrine',password:o.database_password,database:'citrine'});
  await db.connect();
  try {
    await db.query('BEGIN');
    const station=commandStation(o);
    // Open admission registers stations at BootNotification, so the
    // single-station guard applies only while every station is provisioned.
    // Plugfest stations are provisioned below, so the guard is off there too.
    if(!o.open_admission_enabled&&!o.plugfest_enabled) {
      const other=await db.query(`SELECT id FROM "ChargingStations"
        WHERE "tenantId" <> 1 OR "ocppConnectionName" NOT IN ('SIM-CITRINE-LAB-01',$1) LIMIT 1`,[station]);
      if(other.rowCount) throw new Error('Dedicated database contains a different station');
    }
    const targets=[];
    if(o.simulator_enabled)targets.push(['SIM-CITRINE-LAB-01',o.simulator_password,2]);
    if(o.profile_simulator_enabled)targets.push([station,o.profile_simulator_password,1]);
    // External Plugfest stations: identity and password only; their EVSEs
    // and connectors are created from their own status reports.
    if(o.plugfest_enabled)for(const st of o.plugfest_stations||[])targets.push([st.id,st.password,0]);
    for(const [name,password,connectors] of targets) {
    await db.query(`INSERT INTO "ChargingStations"
      ("ocppConnectionName","tenantId","isOnline","use16StatusNotification0","createdAt","updatedAt")
      VALUES ($1,1,false,true,NOW(),NOW()) ON CONFLICT DO NOTHING`,[name]);
    const {rows:[station]}=await db.query(`SELECT id FROM "ChargingStations"
      WHERE "tenantId"=1 AND "ocppConnectionName"=$1`,[name]);
    for (const n of Array.from({length:connectors},(_,i)=>i+1)) {
      await db.query(`INSERT INTO "Evses"
        ("stationId","tenantId","evseTypeId",removed,"createdAt","updatedAt")
        VALUES ($1,1,$2,false,NOW(),NOW()) ON CONFLICT DO NOTHING`,[station.id,n]);
      const {rows:[evse]}=await db.query(`SELECT id FROM "Evses"
        WHERE "stationId"=$1 AND "tenantId"=1 AND "evseTypeId"=$2`,[station.id,n]);
      await db.query(`INSERT INTO "Connectors"
        ("stationId","tenantId","evseId","connectorId","evseTypeConnectorId",status,"errorCode",timestamp,"createdAt","updatedAt")
        VALUES ($1,1,$2,$3,1,'Available','NoError',NOW(),NOW(),NOW()) ON CONFLICT DO NOTHING`,
        [station.id,evse.id,n]);
    }
    await db.query(`INSERT INTO "Boots"
      ("stationId","tenantId",status,"heartbeatInterval","bootRetryInterval","getBaseReportOnPending","createdAt","updatedAt")
      VALUES ($1,1,'Accepted',30,10,false,NOW(),NOW())
      ON CONFLICT ("stationId") DO UPDATE SET status='Accepted',"updatedAt"=NOW()`,[station.id]);
    await db.query(`INSERT INTO "Components" (name,"tenantId","createdAt","updatedAt")
      VALUES ('SecurityCtrlr',1,NOW(),NOW()) ON CONFLICT DO NOTHING`);
    await db.query(`INSERT INTO "Variables" (name,"tenantId","createdAt","updatedAt")
      VALUES ('BasicAuthPassword',1,NOW(),NOW()) ON CONFLICT DO NOTHING`);
    const {rows:[component]}=await db.query(`SELECT id FROM "Components" WHERE name='SecurityCtrlr' AND "tenantId"=1 AND instance IS NULL`);
    const {rows:[variable]}=await db.query(`SELECT id FROM "Variables" WHERE name='BasicAuthPassword' AND "tenantId"=1 AND instance IS NULL`);
    await db.query(`INSERT INTO "VariableAttributes"
      ("stationId","tenantId","componentId","variableId",type,"dataType",value,mutability,persistent,constant,"createdAt","updatedAt")
      VALUES ($1,1,$2,$3,'Actual','string',$4,'ReadOnly',true,true,NOW(),NOW())
      ON CONFLICT ("stationId",type,"variableId","componentId") DO UPDATE SET value=EXCLUDED.value,"updatedAt"=NOW()`,
      [station.id,component.id,variable.id,password]);
    }
    // Revoke Basic Auth for every station not provisioned by these options,
    // so a removed Plugfest or simulator identity cannot log in again.
    await db.query(`DELETE FROM "VariableAttributes" va
      USING "ChargingStations" cs, "Components" c, "Variables" v
      WHERE va."stationId"=cs.id AND va."componentId"=c.id AND va."variableId"=v.id
        AND c.name='SecurityCtrlr' AND c.instance IS NULL
        AND v.name='BasicAuthPassword' AND v.instance IS NULL
        AND NOT (cs."ocppConnectionName" = ANY($1::text[]))`,[targets.map(([name])=>name)]);
    await db.query(`INSERT INTO "Authorizations"
      ("idToken","idTokenType","tenantId",status,"concurrentTransaction","isPrepaid","createdAt","updatedAt")
      VALUES ('C17E0001','ISO14443',1,'Accepted',false,false,NOW(),NOW()) ON CONFLICT DO NOTHING`);
    await db.query('COMMIT');
  } catch {
    await db.query('ROLLBACK');
    throw new Error('Dedicated simulator provisioning failed; credentials omitted');
  } finally {await db.end();}
}
