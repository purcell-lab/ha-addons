import {createRequire} from 'node:module';
import {commandStation,LAB_TARIFF} from './control-policy.mjs';
const requireApp=createRequire('/usr/local/apps/citrineos/apps/ocpp-server/package.json');
const {Client}=createRequire(requireApp.resolve('@citrineos/dal'))('pg');
export {LAB_TARIFF};
export const LAB_LOCATION='Home Assistant lab';
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
    // Lab tariff and location (#30): upstream logs "Tariff not found for
    // connector" every minute of a transaction and "does not have a
    // locationId" at each start. A zero-cost tariff (upstream already reports
    // cost 0 without one) goes on every tenant-1 connector and one
    // non-published lab Location on every tenant-1 station. Only unset
    // associations are filled; a station or connector first seen after this
    // start (open admission, Plugfest status reports) gets them at the next start.
    await db.query(`INSERT INTO "Tariffs" ("tariffId","tenantId",currency,"pricePerKwh","createdAt","updatedAt")
      VALUES ($1,1,'EUR',0,NOW(),NOW()) ON CONFLICT ("tariffId","tenantId") DO NOTHING`,[LAB_TARIFF]);
    const {rows:[tariff]}=await db.query(`SELECT id FROM "Tariffs" WHERE "tariffId"=$1 AND "tenantId"=1`,[LAB_TARIFF]);
    await db.query(`UPDATE "Connectors" SET "tariffId"=$1 WHERE "tenantId"=1 AND "tariffId" IS NULL`,[tariff.id]);
    // $1 is cast: without it PostgreSQL deduces text in the select list and
    // varchar in the comparison and rejects the statement.
    await db.query(`INSERT INTO "Locations"
      (name,address,city,"tenantId","publishUpstream","timeZone",coordinates,"createdAt","updatedAt")
      SELECT $1::varchar,'Laboratory','Laboratory',1,false,'UTC',ST_GeomFromText('POINT(0 0)'),NOW(),NOW()
      WHERE NOT EXISTS (SELECT 1 FROM "Locations" WHERE "tenantId"=1 AND name=$1::varchar)`,[LAB_LOCATION]);
    const {rows:[location]}=await db.query(`SELECT id FROM "Locations"
      WHERE "tenantId"=1 AND name=$1 ORDER BY id LIMIT 1`,[LAB_LOCATION]);
    await db.query(`UPDATE "ChargingStations" SET "locationId"=$1 WHERE "tenantId"=1 AND "locationId" IS NULL`,[location.id]);
    await db.query(`INSERT INTO "Authorizations"
      ("idToken","idTokenType","tenantId",status,"concurrentTransaction","isPrepaid","createdAt","updatedAt")
      VALUES ('C17E0001','ISO14443',1,'Accepted',false,false,NOW(),NOW()) ON CONFLICT DO NOTHING`);
    await db.query('COMMIT');
  } catch {
    await db.query('ROLLBACK');
    throw new Error('Dedicated simulator provisioning failed; credentials omitted');
  } finally {await db.end();}
}
