import {createRequire} from 'node:module';
const requireApp=createRequire('/usr/local/apps/citrineos/apps/ocpp-server/package.json');
const {Client}=createRequire(requireApp.resolve('@citrineos/dal'))('pg');
export async function seedSimulator(o) {
  // Parameterised, dedicated-lab-only bootstrap. No public API exposes SQL.
  const db=new Client({host:o.database_host,user:'citrine',password:o.database_password,database:'citrine'});
  await db.connect();
  try {
    await db.query('BEGIN');
    const other=await db.query(`SELECT id FROM "ChargingStations"
      WHERE "tenantId" <> 1 OR "ocppConnectionName" <> 'SIM-CITRINE-LAB-01' LIMIT 1`);
    if(other.rowCount) throw new Error('Dedicated database contains a different station');
    await db.query(`INSERT INTO "ChargingStations"
      ("ocppConnectionName","tenantId","isOnline","use16StatusNotification0","createdAt","updatedAt")
      VALUES ('SIM-CITRINE-LAB-01',1,false,true,NOW(),NOW()) ON CONFLICT DO NOTHING`);
    const {rows:[station]}=await db.query(`SELECT id FROM "ChargingStations"
      WHERE "tenantId"=1 AND "ocppConnectionName"='SIM-CITRINE-LAB-01'`);
    for (const n of [1,2]) {
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
      [station.id,component.id,variable.id,o.simulator_password]);
    await db.query(`INSERT INTO "Authorizations"
      ("idToken","idTokenType","tenantId",status,"concurrentTransaction","isPrepaid","createdAt","updatedAt")
      VALUES ('C17E0001','ISO14443',1,'Accepted',false,false,NOW(),NOW()) ON CONFLICT DO NOTHING`);
    await db.query('COMMIT');
  } catch {
    await db.query('ROLLBACK');
    throw new Error('Dedicated simulator provisioning failed; credentials omitted');
  } finally {await db.end();}
}
