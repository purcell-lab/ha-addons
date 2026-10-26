// A narrow laboratory command policy, not general-purpose device enrolment.
// Upstream AJV validation remains mandatory after these additional constraints.
// Default command target. Option command_station_id selects one station at a
// time: a SIM-EV- simulator, or, with command_real_stations_enabled, any OCPP
// identity (a physical charger on the Plugfest listener).
export const STATION='SIM-EV-EVEREST-V2G-01';
export const STATION_PATTERN=/^SIM-EV-[A-Za-z0-9_-]{1,36}$/;
export const REAL_STATION_PATTERN=/^[A-Za-z0-9._~*+-]{1,48}$/;
export const commandStation=o=>o.command_station_id||STATION;
export const stationAllowed=(station,real=false)=>
  STATION_PATTERN.test(station)||(real===true&&REAL_STATION_PATTERN.test(station));
// PROTOCOL and ROUTES keep the original OCPP 2.1 contract that clients check.
// PROTOCOLS adds OCPP 2.0.1 and 1.6 stations (charging-only periods; no setpoints).
export const PROTOCOL='ocpp2.1';
export const PROTOCOLS=['ocpp2.1','ocpp2.0.1','ocpp1.6'];
// Lab bounds per period: 25 kW charging (import) and V2G discharge (export),
// above a 3-phase 32 A AC simulator (3 x 32 A x 240 V = 23 kW).
export const MAX_IMPORT_W=25000;
export const MAX_EXPORT_W=25000;
// OCPP 2.1 operation modes a TxProfile period may carry. In the last three the
// station (or a local EMS) chooses the power within limit and dischargeLimit.
export const LOCAL_MODES=['ExternalLimits','ExternalSetpoint','LocalLoadBalancing'];
export const OPERATION_MODES=['ChargingOnly','CentralSetpoint',...LOCAL_MODES];
// Same order for every version: start, stop, profile, clear.
const ACTIONS=['evdriver/requestStartTransaction','evdriver/requestStopTransaction',
  'smartcharging/setChargingProfile','smartcharging/clearChargingProfile'];
const ACTIONS_16=['evdriver/remoteStartTransaction','evdriver/remoteStopTransaction',
  'smartcharging/setChargingProfile','smartcharging/clearChargingProfile'];
export const routesFor=protocol=>(protocol==='ocpp1.6'?ACTIONS_16:ACTIONS)
  .map(a=>`/ocpp/${protocol.slice(4)}/${a}`);
export const ROUTES=routesFor(PROTOCOL);
export const COMMANDS_BY_PROTOCOL=Object.fromEntries(PROTOCOLS.map(p=>[p,routesFor(p)]));
export const ALL_ROUTES=Object.values(COMMANDS_BY_PROTOCOL).flat();
// CitrineOS role-based access for the internal JWT roles, derived from the
// same route lists the gateway enforces so the two cannot drift apart (0.6.0
// accepted 2.0.1 and 1.6 routes at the gateway but CitrineOS refused them).
// roleRoutes() lists the upstream routes each role may call:
// - lab-reader: GET /commands/tariff only;
// - lab-controller (COMMAND_ROLE): the tariff read, plus, when scoped commands
//   are enabled, exactly ALL_ROUTES, the read-only configuration route and the
//   transaction status routes (STATUS_ROUTES, sent only by the gateway itself),
//   plus the price routes (PRICE_ROUTES) when price commands are enabled too,
//   and the DER routes (DER_ROUTES) when DER commands are;
// - lab-operator (OPERATOR_ROLE): the Operator UI command set on OCPP 2.0.1 and
//   2.1 (OPERATOR_COMMANDS and the metering SetVariables);
// - lab-reporter (REPORT_ROLE): the two GetBaseReport routes when device model
//   reports are on.
// CitrineOS v2.1.0 checks a permission per route, named from the route without
// its OCPP version (permissionName); rolesSeed() turns the route lists into
// its roles seed file. A permission therefore also covers the same action on
// the other OCPP versions: the gateway's version checks (validateCommand,
// targetAllows, operatorCommand, operatorTargetAllows, the price and report
// targets) remain what scopes a role to an OCPP version.
export const COMMAND_ROLE='lab-controller';
export const READER_ROLE='lab-reader';
export const OPERATOR_ROLE='lab-operator';
export const TARIFF_READ={method:'GET',route:'/commands/tariff'};
export function roleRoutes(commandsEnabled,priceEnabled=false,reportsEnabled=false,derCommands=false) {
  const post=routes=>routes.map(route=>({method:'POST',route}));
  const commands=commandsEnabled===true
    ?[...ALL_ROUTES,CONFIG_UPSTREAM,...Object.values(STATUS_ROUTES),...(priceEnabled===true?PRICE_ROUTES:[]),
      ...(derCommands===true?Object.values(DER_ROUTES):[])]:[];
  return {
    [READER_ROLE]:[TARIFF_READ],
    [COMMAND_ROLE]:[TARIFF_READ,...post(commands)],
    [OPERATOR_ROLE]:post(OPERATOR_PROTOCOLS.flatMap(p=>[...OPERATOR_COMMANDS,METERING_COMMAND]
      .map(a=>`/ocpp/${p.slice(4)}/${a}`))),
    [REPORT_ROLE]:post(reportsEnabled===true?Object.values(REPORT_ROUTES):[]),
  };
}
// CitrineOS v2.1.0 permission names (packages/base permission-name.ts): an
// OCPP message route /ocpp/<version>/<eventGroup>/<action> needs
// ocpp.<eventGroup>.<action>; a command route <prefix>/<path> with method M
// needs <prefix>.<path>.<m>. null for anything else.
export function permissionName({method,route}) {
  const ocpp=/^\/ocpp\/(?:1\.6|2\.0\.1|2\.1)\/([a-z]+)\/([a-z][A-Za-z0-9]*)$/.exec(route);
  if(ocpp)return method==='POST'?`ocpp.${ocpp[1]}.${ocpp[2]}`:null;
  const command=/^\/(commands)\/([a-z][A-Za-z0-9]*)$/.exec(route);
  return command?`${command[1]}.${command[2]}.${method.toLowerCase()}`:null;
}
// The roles seed file (CITRINEOS_ROLES seedFile): {role: {resources, permissions}}.
// Resources are the Operator UI's own access model; the lab grants none.
export function rolesSeed(commandsEnabled,priceEnabled=false,reportsEnabled=false,derCommands=false) {
  return Object.fromEntries(Object.entries(roleRoutes(commandsEnabled,priceEnabled,reportsEnabled,derCommands))
    .map(([role,routes])=>[role,{resources:{},permissions:[...new Set(routes.map(permissionName))].sort()}]));
}
// The OCPP version a command route speaks, e.g. 'ocpp2.0.1'; null if not a lab route.
export function routeProtocol(pathname) {
  return PROTOCOLS.find(p=>COMMANDS_BY_PROTOCOL[p].includes(pathname))||null;
}
const action=pathname=>{
  const p=routeProtocol(pathname);
  return p?COMMANDS_BY_PROTOCOL[p].indexOf(pathname):-1;
};
const keys=(o,allowed)=>o!==null && typeof o==='object' && !Array.isArray(o)
  && Object.keys(o).every(k=>allowed.includes(k));
const int=(n,min,max)=>Number.isInteger(n)&&n>=min&&n<=max;
// OCPP identifierString characters: physical chargers use more than the simulators do.
const transaction=n=>typeof n==='string'&&/^[A-Za-z0-9*_=:+|@.-]{1,64}$/.test(n);
const timestamp=n=>typeof n==='string'
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(n)
  && Number.isFinite(Date.parse(n));

// Exactly identifier=<one station> and tenantId=1: no callbacks or duplicate routing.
const queryStation=url=>[...url.searchParams.keys()].length===2
  &&url.searchParams.getAll('identifier').length===1
  &&url.searchParams.getAll('tenantId').length===1
  &&url.searchParams.get('tenantId')==='1'?url.searchParams.get('identifier'):null;

// price: priceOptions(o). Only with it enabled may an OCPP 2.1 profile carry a
// price schedule (information for the station; the limits are unchanged).
export function validateCommand(url,p,station=STATION,real=false,price=null) {
  const protocol=routeProtocol(url.pathname);
  if(!protocol||!stationAllowed(station,real)) return false;
  const a=action(url.pathname);
  if(queryStation(url)!==station) return false;
  if(protocol==='ocpp1.6') return validate16(a,p);
  if(a===0) return keys(p,['remoteStartId','evseId','idToken'])
    &&int(p.remoteStartId,0,2147483647)&&p.evseId===1
    &&keys(p.idToken,['idToken','type'])&&p.idToken.idToken==='C17E0001'&&p.idToken.type==='ISO14443';
  if(a===1) return keys(p,['transactionId'])&&transaction(p.transactionId);
  // No clear-all command. The caller must select its exact test profile.
  if(a===3) return keys(p,['chargingProfileId'])
    &&int(p.chargingProfileId,1,2147483647);
  if(p?.chargingProfile?.chargingProfilePurpose===LOCAL_GENERATION.purpose)
    return protocol==='ocpp2.1'&&validLocalGeneration(p);
  if(!keys(p,['evseId','chargingProfile'])||p.evseId!==1)return false;
  const c=p.chargingProfile;
  if(!keys(c,['id','stackLevel','chargingProfilePurpose','chargingProfileKind','transactionId','chargingSchedule'])
    ||!int(c.id,1,2147483647)||!int(c.stackLevel,0,10)
    ||c.chargingProfilePurpose!=='TxProfile'||!transaction(c.transactionId)
    ||!['Absolute','Relative'].includes(c.chargingProfileKind)
    ||!Array.isArray(c.chargingSchedule)||c.chargingSchedule.length!==1)return false;
  const s=c.chargingSchedule[0];
  const priced=price?.enabled===true&&protocol==='ocpp2.1';
  if(!keys(s,['id','startSchedule','duration','chargingRateUnit','chargingSchedulePeriod',
    ...(priced?['absolutePriceSchedule','priceLevelSchedule']:[])])
    ||(priced&&!validPriceSchedule(s,price.currency))
    ||!int(s.id,0,2147483647)||!int(s.duration,1,600)||s.chargingRateUnit!=='W'
    ||!Array.isArray(s.chargingSchedulePeriod)||s.chargingSchedulePeriod.length<1
    ||s.chargingSchedulePeriod.length>10)return false;
  if(c.chargingProfileKind==='Absolute'&&!timestamp(s.startSchedule))return false;
  if(c.chargingProfileKind==='Relative'&&s.startSchedule!==undefined)return false;
  let last=-1;
  return s.chargingSchedulePeriod.every((x,i)=>{
    const ok=validPeriod(x,s.duration,i,last,protocol);
    last=x.startPeriod;return ok;
  });
}
// OCPP 2.1 LocalGeneration (smart charging with local generation): extra
// charging capacity from on-site generation, on top of the grid limits. Not
// tied to a transaction: EVSE 0 (the station) or 1, an id in its own range so
// it can be cleared at any time without touching the TxProfile, charging
// limits only (no setpoint, discharge or operation mode), up to a day ahead.
// The station takes it only if SmartChargingCtrlr.SupportedAdditionalPurposes
// lists LocalGeneration; otherwise it answers Rejected.
export const LOCAL_GENERATION={purpose:'LocalGeneration',ids:[9100,9199],evse_ids:[0,1],
  max_duration_s:86400,max_periods:48};
export const localGenerationProfile=id=>int(id,LOCAL_GENERATION.ids[0],LOCAL_GENERATION.ids[1]);
function validLocalGeneration(p) {
  const c=p.chargingProfile;
  if(!keys(p,['evseId','chargingProfile'])||!LOCAL_GENERATION.evse_ids.includes(p.evseId)
    ||!keys(c,['id','stackLevel','chargingProfilePurpose','chargingProfileKind','chargingSchedule'])
    ||!localGenerationProfile(c.id)||!int(c.stackLevel,0,10)
    ||!['Absolute','Relative'].includes(c.chargingProfileKind)
    ||!Array.isArray(c.chargingSchedule)||c.chargingSchedule.length!==1)return false;
  const s=c.chargingSchedule[0];
  if(!keys(s,['id','startSchedule','duration','chargingRateUnit','chargingSchedulePeriod'])
    ||!int(s.id,0,2147483647)||!int(s.duration,1,LOCAL_GENERATION.max_duration_s)||s.chargingRateUnit!=='W'
    ||!Array.isArray(s.chargingSchedulePeriod)||s.chargingSchedulePeriod.length<1
    ||s.chargingSchedulePeriod.length>LOCAL_GENERATION.max_periods)return false;
  if(c.chargingProfileKind==='Absolute'&&!timestamp(s.startSchedule))return false;
  if(c.chargingProfileKind==='Relative'&&s.startSchedule!==undefined)return false;
  let last=-1;
  return s.chargingSchedulePeriod.every((x,i)=>{
    const ok=keys(x,['startPeriod','limit','numberPhases'])
      &&int(x.startPeriod,0,s.duration-1)&&(i!==0||x.startPeriod===0)&&x.startPeriod>last
      &&Number.isFinite(x.limit)&&x.limit>=0&&x.limit<=MAX_IMPORT_W
      &&(x.numberPhases===undefined||x.numberPhases===1||x.numberPhases===3);
    last=x.startPeriod;return ok;
  });
}
// OCPP 1.6 has integer transaction IDs, connectorId instead of evseId, a single
// csChargingProfiles schedule and no setpoints. Limits are whole watts here, which
// satisfies the 1.6 multipleOf 0.1 without floating-point surprises.
function validate16(a,p) {
  if(a===0) return keys(p,['connectorId','idTag'])&&p.connectorId===1&&p.idTag==='C17E0001';
  if(a===1) return keys(p,['transactionId'])&&int(p.transactionId,0,2147483647);
  if(a===3) return keys(p,['id'])&&int(p.id,1,2147483647);
  if(!keys(p,['connectorId','csChargingProfiles'])||p.connectorId!==1)return false;
  const c=p.csChargingProfiles;
  if(!keys(c,['chargingProfileId','stackLevel','chargingProfilePurpose','chargingProfileKind','transactionId','chargingSchedule'])
    ||!int(c.chargingProfileId,1,2147483647)||!int(c.stackLevel,0,10)
    ||c.chargingProfilePurpose!=='TxProfile'||!int(c.transactionId,0,2147483647)
    ||!['Absolute','Relative'].includes(c.chargingProfileKind))return false;
  const s=c.chargingSchedule;
  if(!keys(s,['startSchedule','duration','chargingRateUnit','chargingSchedulePeriod'])
    ||!int(s.duration,1,600)||s.chargingRateUnit!=='W'
    ||!Array.isArray(s.chargingSchedulePeriod)||s.chargingSchedulePeriod.length<1
    ||s.chargingSchedulePeriod.length>10)return false;
  if(c.chargingProfileKind==='Absolute'&&!timestamp(s.startSchedule))return false;
  if(c.chargingProfileKind==='Relative'&&s.startSchedule!==undefined)return false;
  let last=-1;
  return s.chargingSchedulePeriod.every((x,i)=>{
    const ok=keys(x,['startPeriod','limit','numberPhases'])
      &&int(x.startPeriod,0,s.duration-1)&&(i!==0||x.startPeriod===0)&&x.startPeriod>last
      &&int(x.limit,0,MAX_IMPORT_W)
      &&(x.numberPhases===undefined||x.numberPhases===1||x.numberPhases===3);
    last=x.startPeriod;return ok;
  });
}

// A period is either a V2G CentralSetpoint period (setpoint and discharge
// limit required, OCPP 2.1 only), an OCPP 2.1 period in which the station or a
// local EMS sets the power within the bounds (ExternalLimits, ExternalSetpoint,
// LocalLoadBalancing: discharge limit required, no setpoint), or an AC
// charging-only period (operationMode absent or ChargingOnly, no setpoint or
// discharge). OCPP 2.0.1 has no
// operationMode, setpoint or dischargeLimit at all. libocpp assumes 3 phases when
// numberPhases is absent, so a single-phase AC station would get a third of a
// watt limit (#39): numberPhases may be 1 or 3, and phaseToUse (1-3) only
// with numberPhases 1.
function validPeriod(x,duration,i,last,protocol=PROTOCOL) {
  if(!keys(x,['startPeriod','limit','dischargeLimit','setpoint','operationMode','numberPhases','phaseToUse'])
    ||!int(x.startPeriod,0,duration-1)||(i===0&&x.startPeriod!==0)||x.startPeriod<=last
    ||!Number.isFinite(x.limit)||x.limit<0||x.limit>MAX_IMPORT_W)return false;
  if(x.numberPhases!==undefined&&x.numberPhases!==1&&x.numberPhases!==3)return false;
  if(x.phaseToUse!==undefined&&(x.numberPhases!==1||!int(x.phaseToUse,1,3)))return false;
  if(protocol==='ocpp2.0.1')
    return x.operationMode===undefined&&x.setpoint===undefined&&x.dischargeLimit===undefined;
  const discharge=Number.isFinite(x.dischargeLimit)&&x.dischargeLimit>=-MAX_EXPORT_W&&x.dischargeLimit<=0;
  if(x.operationMode==='CentralSetpoint')
    return discharge&&Number.isFinite(x.setpoint)&&x.setpoint>=x.dischargeLimit&&x.setpoint<=x.limit;
  if(LOCAL_MODES.includes(x.operationMode))return discharge&&x.setpoint===undefined;
  return (x.operationMode===undefined||x.operationMode==='ChargingOnly')
    &&x.setpoint===undefined&&x.dischargeLimit===undefined;
}

// Read the observed protocol and active transaction before any dispatch.
// The route's OCPP version must be the station's negotiated protocol (no
// fallback between versions), and never start another active session.
export const TARGET_QUERY=`query ControlTarget($name: String!) {
  ChargingStations(where: {tenantId: {_eq: 1}, ocppConnectionName: {_eq: $name}}, limit: 2) {
    id tenantId ocppConnectionName protocol isOnline
  }
  Transactions(where: {tenantId: {_eq: 1}, isActive: {_eq: true}}, limit: 501) {
    stationId tenantId transactionId isActive
  }
}`;
// The station's active transactions, or null unless the station is the
// expected one, online on exactly this protocol, and every row is well formed.
function observed(result,station,protocol) {
  const stations=result?.data?.ChargingStations, transactions=result?.data?.Transactions;
  if(!Array.isArray(stations)||stations.length!==1||!Array.isArray(transactions)
    ||transactions.length>500)return null;
  const s=stations[0];
  if(!s||!int(s.id,1,Number.MAX_SAFE_INTEGER)||s.tenantId!==1
    ||s.ocppConnectionName!==station||!protocol||s.protocol!==protocol||s.isOnline!==true)return null;
  if(transactions.some(t=>!t||t.tenantId!==1||t.isActive!==true
    ||!int(t.stationId,1,Number.MAX_SAFE_INTEGER)||!transaction(t.transactionId)))return null;
  return transactions.filter(t=>t.stationId===s.id);
}
export function targetAllows(url,p,result,station=STATION) {
  const active=observed(result,station,routeProtocol(url.pathname));
  if(!active)return false;
  const a=action(url.pathname);
  if(a===0)return active.length===0;
  // A LocalGeneration profile is the station's, not the session's: set and
  // cleared whatever the transactions.
  if(a===2&&p.chargingProfile?.chargingProfilePurpose===LOCAL_GENERATION.purpose)return true;
  if(a===3&&localGenerationProfile(p.chargingProfileId))return true;
  // Clearing a profile during discharge can restore the default import limit.
  // Only allow cleanup once the transaction is evidenced closed.
  if(a===3)return active.length===0;
  const id=a===1?p.transactionId:(p.chargingProfile||p.csChargingProfiles).transactionId;
  // CitrineOS stores 1.6 integer transaction IDs as strings.
  return active.length===1&&active[0].transactionId===String(id);
}
// The lab start route for any protocol (the first route of each list).
export const startRoute=pathname=>PROTOCOLS.some(p=>COMMANDS_BY_PROTOCOL[p][0]===pathname);

// Stale transactions. CitrineOS keeps a transaction active until the station
// sends TransactionEvent Ended. A station that loses its transaction state
// (an App update recreates the simulator container) never does, so every
// later start was refused as "another active session". OCPP 2.x
// GetTransactionStatus asks the station: upstream's response handler sets the
// transaction inactive when the station answers ongoingIndicator false with
// no queued messages, and active again when it answers true. OCPP 1.6 has no
// equivalent, so 1.6 transactions are left as they are.
export const RECONCILE_ROUTE='/lab/reconcile-transactions';
export const STATUS_ROUTES={
  'ocpp2.1':'/ocpp/2.1/transactions/getTransactionStatus',
  'ocpp2.0.1':'/ocpp/2.0.1/transactions/getTransactionStatus',
};
// Each active transaction is asked about at most this often, and at once when
// the station comes online.
export const RECONCILE_EVERY_MS=300000;
// {protocol, route, transactions} for the command station, or null unless it
// is online on OCPP 2.0.1/2.1 and every row is well formed (as targetAllows).
export function reconcileTarget(result,station=STATION) {
  const s=result?.data?.ChargingStations?.[0];
  const route=s?STATUS_ROUTES[s.protocol]:undefined;
  if(!route)return null;
  const active=observed(result,station,s.protocol);
  return active&&{protocol:s.protocol,route,transactions:active.map(t=>t.transactionId)};
}
// The transactions to ask about now: all when the station has just come
// online, otherwise those not asked about within RECONCILE_EVERY_MS.
// checked maps transaction ID to the time of its last check.
export function reconcileDue(target,now,checked,cameOnline=false) {
  if(!target)return [];
  return target.transactions.filter(id=>cameOnline||!checked.has(id)||now-checked.get(id)>=RECONCILE_EVERY_MS);
}

// Device model reports (option device_model_reports, default on). CitrineOS
// stores a station's device model only from NotifyReport, which a station
// sends when asked: upstream asks with GetBaseReport only on a Pending boot,
// so stations it accepts at once never report their EVSE Power rating. When
// an OCPP 2.1 or 2.0.1 station of tenant 1 comes online (any listener), the
// gateway sends it one GetBaseReport FullInventory, a read-only request,
// with the internal role REPORT_ROLE, which CitrineOS permits on these two
// routes only. Callers cannot send them through the gateway. OCPP 1.6 has
// no device model. Rate limit: a station that comes online again within
// REPORT_EVERY_MS of its last report is not asked again, at most
// REPORT_PER_CYCLE stations are asked per 30 s check, and a request
// CitrineOS could not send is retried on REPORT_ATTEMPTS checks at most.
export const REPORT_ROLE='lab-reporter';
export const REPORT_ROUTES={
  'ocpp2.1':'/ocpp/2.1/reporting/getBaseReport',
  'ocpp2.0.1':'/ocpp/2.0.1/reporting/getBaseReport',
};
export const REPORT_EVERY_MS=600000;
export const REPORT_PER_CYCLE=3;
export const REPORT_ATTEMPTS=3;
export const REPORT_STATUSES=['Accepted','Rejected','NotSupported','EmptyResultSet'];
export const deviceModelReports=o=>o.device_model_reports!==false;
export const REPORT_STATIONS_QUERY=`query DeviceModelStations {
  ChargingStations(where: {tenantId: {_eq: 1}}, limit: 501) {
    id tenantId ocppConnectionName protocol isOnline
  }
}`;
// state: {online: Set of identities, pending: Map identity -> failed sends,
// last: Map identity -> time of the last report request}.
export const reportState=()=>({online:new Set(),pending:new Map(),last:new Map()});
// Updates state from the station rows and returns the requests to send now,
// [{identifier, protocol, route}]. Malformed results change nothing.
export function reportsDue(result,state,now) {
  const rows=result?.data?.ChargingStations;
  if(!Array.isArray(rows)||rows.length>500)return [];
  const online=new Map();
  for(const s of rows) {
    if(s&&s.tenantId===1&&s.isOnline===true&&REPORT_ROUTES[s.protocol]
      &&typeof s.ocppConnectionName==='string'&&OPERATOR_IDENTITY.test(s.ocppConnectionName))
      online.set(s.ocppConnectionName,s.protocol);
  }
  for(const id of online.keys()) {
    if(state.online.has(id))continue;
    const last=state.last.get(id);
    if(last===undefined||now-last>=REPORT_EVERY_MS)state.pending.set(id,0);
  }
  for(const id of state.pending.keys()) if(!online.has(id))state.pending.delete(id);
  state.online=new Set(online.keys());
  return [...state.pending.keys()].slice(0,REPORT_PER_CYCLE)
    .map(id=>({identifier:id,protocol:online.get(id),route:REPORT_ROUTES[online.get(id)]}));
}
// Records one send. reply is call()'s result: {payload} or {status,error};
// 502 means CitrineOS did not send it. Returns the station's status, or
// the reason, for the log.
export function reportDone(state,id,reply,now) {
  if(reply?.status===502) {
    const failed=(state.pending.get(id)??0)+1;
    if(failed>=REPORT_ATTEMPTS)state.pending.delete(id);else state.pending.set(id,failed);
    return failed>=REPORT_ATTEMPTS?'not sent, giving up':'not sent, will retry';
  }
  state.pending.delete(id);
  state.last.set(id,now);
  if(!reply?.payload)return 'no reply within 8 s';
  return REPORT_STATUSES.includes(reply.payload.status)?reply.payload.status:'unexpected reply';
}

// Read-only station configuration for the command station (OCPP 1.6
// GetConfiguration). Only standard, non-secret keys that describe metering
// and smart charging can be read, so a charger's credentials or network
// settings are never requested or returned. The gateway answers this route
// itself and waits for the station's reply on a loopback callback.
export const CONFIG_ROUTE='/lab/station-configuration';
export const CONFIG_UPSTREAM='/ocpp/1.6/configuration/getConfiguration';
export const CONFIG_KEYS=[
  'SupportedFeatureProfiles','NumberOfConnectors','GetConfigurationMaxKeys',
  'MeterValuesSampledData','MeterValueSampleInterval','StopTransactionOnEVSideDisconnect',
  'ChargingScheduleAllowedChargingRateUnit','ChargingScheduleMaxPeriods',
  'ChargeProfileMaxStackLevel','MaxChargingProfilesInstalled','ConnectorSwitch3to1PhaseSupported',
];
export const validateConfigRequest=p=>keys(p,['key'])&&Array.isArray(p.key)
  &&p.key.length>=1&&new Set(p.key).size===p.key.length&&p.key.every(k=>CONFIG_KEYS.includes(k));
export function configTargetAllows(result,station=STATION) {
  const stations=result?.data?.ChargingStations;
  if(!Array.isArray(stations)||stations.length!==1)return false;
  const s=stations[0];
  return !!s&&s.tenantId===1&&s.ocppConnectionName===station&&s.protocol==='ocpp1.6'&&s.isOnline===true;
}
// Returns only the requested keys, whatever else the station sends.
export function configResult(payload,requested) {
  const known=Array.isArray(payload?.configurationKey)?payload.configurationKey:null;
  const unknown=Array.isArray(payload?.unknownKey)?payload.unknownKey:[];
  if(!known&&!Array.isArray(payload?.unknownKey))return {error:'Station did not return a configuration'};
  return {
    configurationKey:(known||[]).filter(k=>k&&requested.includes(k.key)).map(k=>({key:k.key,readonly:k.readonly===true,
      ...(typeof k.value==='string'?{value:k.value.slice(0,500)}:{})})),
    unknownKey:unknown.filter(k=>requested.includes(k)),
  };
}

// Operator UI scope (operator_ui_enabled). Reads go to Hasura as the
// read-only "operator_ro" role. With operator_commands_enabled, a fixed set
// of OCPP 2.0.1/2.1 operational commands may target any tenant-1 station;
// upstream AJV still validates each payload. Commands that change station
// credentials, certificates, firmware, network profiles or variables (except
// the metering variables below), or that make the station upload files, are
// never allowed.
export const OPERATOR_COMMANDS=[
  'evdriver/requestStartTransaction','evdriver/requestStopTransaction',
  'evdriver/unlockConnector','evdriver/clearCache',
  'configuration/reset','configuration/changeAvailability','configuration/triggerMessage',
  'monitoring/getVariables','reporting/getBaseReport','transactions/getTransactionStatus',
  'smartcharging/setChargingProfile','smartcharging/clearChargingProfile',
  'smartcharging/getChargingProfiles','smartcharging/getCompositeSchedule',
];
// One exception to "never variables": SetVariables limited to the metering
// variables below (SampledDataCtrlr, AlignedDataCtrlr), so a station that sends
// power only when asked over OCPP (ChargeSim, Plugfest 23 October 2026) can be
// told what to sample. Checked by meteringVariables() before it is sent.
export const METERING_COMMAND='monitoring/setVariables';
export const METERING_VARIABLES={
  SampledDataCtrlr:['TxStartedMeasurands','TxUpdatedMeasurands','TxUpdatedInterval','TxEndedMeasurands','TxEndedInterval'],
  AlignedDataCtrlr:['Measurands','Interval','TxEndedMeasurands','TxEndedInterval'],
};
const MEASURAND=/^[A-Z][A-Za-z]*(?:\.[A-Za-z0-9]+){0,3}$/;
const meteringValue=(name,v)=>typeof v==='string'&&(name.endsWith('Interval')
  ?/^(0|[1-9]\d{0,4})$/.test(v)&&Number(v)<=86400
  :v.length<=500&&v.split(',').every(m=>MEASURAND.test(m.trim())));
// 1-10 entries, each a listed variable of a listed controller (no EVSE,
// connector or instance), attribute type Actual, and a valid value.
export function meteringVariables(p) {
  const d=p?.setVariableData;
  return !!p&&typeof p==='object'&&!Array.isArray(p)&&Object.keys(p).every(k=>k==='setVariableData')
    &&Array.isArray(d)&&d.length>=1&&d.length<=10&&d.every(e=>keys(e,['attributeType','attributeValue','component','variable'])
      &&(e.attributeType===undefined||e.attributeType==='Actual')
      &&keys(e.component,['name'])&&keys(e.variable,['name'])
      &&(METERING_VARIABLES[e.component.name]||[]).includes(e.variable.name)
      &&meteringValue(e.variable.name,e.attributeValue));
}
// The OCPP versions operator commands may use (OPERATOR_ROUTE below).
export const OPERATOR_PROTOCOLS=['ocpp2.0.1','ocpp2.1'];
const OPERATOR_ROUTE=/^\/ocpp\/(2\.0\.1|2\.1)\/([a-z]+\/[A-Za-z]+)$/;
export const OPERATOR_IDENTITY=/^[A-Za-z0-9._~*+-]{1,48}$/;
export function operatorCommand(url) {
  const m=OPERATOR_ROUTE.exec(url.pathname);
  if(!m||!(OPERATOR_COMMANDS.includes(m[2])||m[2]===METERING_COMMAND))return null;
  if([...url.searchParams.keys()].length!==2||url.searchParams.getAll('identifier').length!==1
    ||url.searchParams.getAll('tenantId').length!==1||url.searchParams.get('tenantId')!=='1')return null;
  const identifier=url.searchParams.get('identifier');
  if(!OPERATOR_IDENTITY.test(identifier))return null;
  return {protocol:'ocpp'+m[1],action:m[2],identifier};
}
export const OPERATOR_TARGET_QUERY=`query OperatorTarget($name: String!) {
  ChargingStations(where: {tenantId: {_eq: 1}, ocppConnectionName: {_eq: $name}}, limit: 2) {
    id tenantId ocppConnectionName protocol isOnline
  }
}`;
// The route's OCPP version must match the station's negotiated protocol,
// and the station must be online, so a command is never sent in the wrong
// dialect or queued for a disconnected station.
export function operatorTargetAllows(cmd,result) {
  const stations=result?.data?.ChargingStations;
  if(!cmd||!Array.isArray(stations)||stations.length!==1)return false;
  const s=stations[0];
  return !!s&&s.tenantId===1&&s.ocppConnectionName===cmd.identifier
    &&s.protocol===cmd.protocol&&s.isOnline===true;
}

// Dynamic pricing (price_commands_enabled, off by default). Prices are
// information for the station; they never change the power bounds above.
// B: an OCPP 2.1 setChargingProfile may carry one price schedule.
// C: CostUpdated (California Pricing customData) for the command station's
//    active transaction, OCPP 2.1 or 2.0.1.
// D: SetDefaultTariff (OCPP 2.1) to the command station or a provisioned
//    Plugfest station. Not a control command, so any listed identity may get it.
export const PRICE_ALGORITHM='urn:iso:std:iso:15118:-20:PriceAlgorithm:1-Power';
export const PRICE_SCHEDULE_LIMITS={max_rule_stacks:288,max_level_entries:100,max_horizon_s:172800};
export const TARIFF_LIMITS={max_prices:96,min_price_kwh:-5,max_price_kwh:20};
export const COST_UPDATED_BY_PROTOCOL={
  'ocpp2.1':'/ocpp/2.1/transactions/costUpdated','ocpp2.0.1':'/ocpp/2.0.1/transactions/costUpdated'};
export const DEFAULT_TARIFF_ROUTE='/ocpp/2.1/transactions/setDefaultTariff';
export const PRICE_ROUTES=[...Object.values(COST_UPDATED_BY_PROTOCOL),DEFAULT_TARIFF_ROUTE];
export const COST_VENDOR='org.openchargealliance.costmsg';
export const MAX_TOTAL_COST=10000;
// The tariff the App seeds on every connector (#30). CitrineOS stores an
// accepted SetDefaultTariff by tariffId, so that id would overwrite it.
export const LAB_TARIFF='HA-LAB-ZERO';
export const priceOptions=o=>({enabled:o.price_commands_enabled===true,currency:o.price_currency||'AUD'});
// The command station and every provisioned Plugfest identity, once each.
export const tariffStations=o=>[...new Set([commandStation(o),
  ...(o.plugfest_enabled===true?(o.plugfest_stations||[]).map(st=>st.id):[])])];
// The /lab/control-policy "price_commands" value.
export function pricePolicy(o) {
  const price=priceOptions(o);
  if(!price.enabled)return {enabled:false};
  return {enabled:true,currency:price.currency,price_schedule:{...PRICE_SCHEDULE_LIMITS},
    cost_updated_by_protocol:{...COST_UPDATED_BY_PROTOCOL},default_tariff:DEFAULT_TARIFF_ROUTE,
    tariff_limits:{...TARIFF_LIMITS},tariff_stations:tariffStations(o)};
}
export const priceProtocol=pathname=>
  Object.keys(COST_UPDATED_BY_PROTOCOL).find(p=>COST_UPDATED_BY_PROTOCOL[p]===pathname)
  ||(pathname===DEFAULT_TARIFF_ROUTE?'ocpp2.1':null);
// A schedule carries a price schedule key (for a clearer rejection message).
export const hasPriceSchedule=p=>{
  const s=p?.chargingProfile?.chargingSchedule?.[0];
  return !!s&&typeof s==='object'&&('absolutePriceSchedule' in s||'priceLevelSchedule' in s);
};
const text=(n,max)=>typeof n==='string'&&n.length<=max;
const price=n=>Number.isFinite(n)&&n>=TARIFF_LIMITS.min_price_kwh&&n<=TARIFF_LIMITS.max_price_kwh;
// RationalNumber: value x 10^exponent, kept small enough for any station.
const rational=r=>keys(r,['value','exponent'])&&int(r.value,-32768,32767)&&int(r.exponent,-3,3);
const horizon=entries=>entries.reduce((sum,x)=>sum+x.duration,0)<=PRICE_SCHEDULE_LIMITS.max_horizon_s;
// No price schedule, or exactly one of the two kinds.
function validPriceSchedule(s,currency) {
  const a=s.absolutePriceSchedule, l=s.priceLevelSchedule;
  if(a!==undefined&&l!==undefined)return false;
  if(a!==undefined)return keys(a,['timeAnchor','priceScheduleID','priceScheduleDescription','currency','language',
      'priceAlgorithm','minimumCost','maximumCost','priceRuleStacks'])
    &&timestamp(a.timeAnchor)&&int(a.priceScheduleID,0,2147483647)
    &&(a.priceScheduleDescription===undefined||text(a.priceScheduleDescription,160))
    &&a.currency===currency&&a.language==='en'&&a.priceAlgorithm===PRICE_ALGORITHM
    &&(a.minimumCost===undefined||rational(a.minimumCost))&&(a.maximumCost===undefined||rational(a.maximumCost))
    &&Array.isArray(a.priceRuleStacks)&&a.priceRuleStacks.length>=1
    &&a.priceRuleStacks.length<=PRICE_SCHEDULE_LIMITS.max_rule_stacks
    &&a.priceRuleStacks.every(st=>keys(st,['duration','priceRule'])
      &&int(st.duration,1,PRICE_SCHEDULE_LIMITS.max_horizon_s)
      &&Array.isArray(st.priceRule)&&st.priceRule.length>=1&&st.priceRule.length<=8
      &&st.priceRule.every(r=>keys(r,['energyFee','powerRangeStart'])&&rational(r.energyFee)
        &&rational(r.powerRangeStart)&&r.powerRangeStart.value===0&&r.powerRangeStart.exponent===0))
    &&horizon(a.priceRuleStacks);
  if(l!==undefined)return keys(l,['timeAnchor','priceScheduleId','numberOfPriceLevels','priceLevelScheduleEntries'])
    &&timestamp(l.timeAnchor)&&int(l.priceScheduleId,0,2147483647)&&int(l.numberOfPriceLevels,1,10)
    &&Array.isArray(l.priceLevelScheduleEntries)&&l.priceLevelScheduleEntries.length>=1
    &&l.priceLevelScheduleEntries.length<=PRICE_SCHEDULE_LIMITS.max_level_entries
    &&l.priceLevelScheduleEntries.every(x=>keys(x,['duration','priceLevel'])
      &&int(x.duration,1,PRICE_SCHEDULE_LIMITS.max_horizon_s)&&int(x.priceLevel,0,l.numberOfPriceLevels-1))
    &&horizon(l.priceLevelScheduleEntries);
  return true;
}
// C: California Pricing CostUpdated to the command station (AUD/kWh incl. GST).
const chargingPrice=(c,only)=>keys(c,only?['kWhPrice']:['kWhPrice','hourPrice','flatFee'])&&price(c.kWhPrice)
  &&(c.hourPrice===undefined||price(c.hourPrice))&&(c.flatFee===undefined||price(c.flatFee));
export function validateCostUpdated(url,p,station=STATION,real=false,options=null) {
  if(options?.enabled!==true||!priceProtocol(url.pathname)||url.pathname===DEFAULT_TARIFF_ROUTE
    ||!stationAllowed(station,real)||queryStation(url)!==station)return false;
  const d=p?.customData;
  return keys(p,['totalCost','transactionId','customData'])
    &&Number.isFinite(p.totalCost)&&p.totalCost>=0&&p.totalCost<=MAX_TOTAL_COST&&transaction(p.transactionId)
    &&keys(d,['vendorId','chargingPrice','nextPeriod','priceText'])&&d.vendorId===COST_VENDOR
    &&chargingPrice(d.chargingPrice,false)
    &&(d.nextPeriod===undefined||(keys(d.nextPeriod,['atTime','chargingPrice'])
      &&timestamp(d.nextPeriod.atTime)&&chargingPrice(d.nextPeriod.chargingPrice,true)))
    &&(d.priceText===undefined||text(d.priceText,255));
}
// Same observed state as a profile: online on the route's protocol, and the
// CostUpdated names the station's one active transaction.
export function costTargetAllows(url,p,result,station=STATION) {
  const active=observed(result,station,priceProtocol(url.pathname));
  return !!active&&active.length===1&&active[0].transactionId===p.transactionId;
}
// D: the listed station a SetDefaultTariff request names, or null.
export function tariffTarget(url,stations,options=null) {
  if(options?.enabled!==true||url.pathname!==DEFAULT_TARIFF_ROUTE)return null;
  const id=queryStation(url);
  return id!==null&&stations.includes(id)?id:null;
}
const timeOfDay=n=>typeof n==='string'&&/^([01]\d|2[0-3]):[0-5]\d$/.test(n);
const date=n=>typeof n==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(n)
  &&new Date(n+'T00:00:00Z').toISOString().slice(0,10)===n;
const DAYS=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
// W; negative for export (the station pays the driver).
const watts=n=>n===undefined||(Number.isFinite(n)&&Math.abs(n)<=1000000);
const conditions=c=>c===undefined||(keys(c,['startTimeOfDay','endTimeOfDay','dayOfWeek','validFromDate',
    'validToDate','minPower','maxPower'])
  &&(c.startTimeOfDay===undefined||timeOfDay(c.startTimeOfDay))&&(c.endTimeOfDay===undefined||timeOfDay(c.endTimeOfDay))
  &&(c.dayOfWeek===undefined||(Array.isArray(c.dayOfWeek)&&c.dayOfWeek.length>=1&&c.dayOfWeek.length<=7
    &&new Set(c.dayOfWeek).size===c.dayOfWeek.length&&c.dayOfWeek.every(d=>DAYS.includes(d))))
  &&(c.validFromDate===undefined||date(c.validFromDate))&&(c.validToDate===undefined||date(c.validToDate))
  &&watts(c.minPower)&&watts(c.maxPower));
// Energy prices only (AUD/kWh excl. GST), optional GST 10 %: no time, idle,
// fixed or reservation fees, and no minimum or maximum cost.
export function validateTariff(p,options=null) {
  const t=p?.tariff, e=t?.energy;
  return options?.enabled===true&&keys(p,['evseId','tariff'])&&int(p.evseId,0,2147483647)
    &&keys(t,['tariffId','currency','description','validFrom','energy'])
    &&typeof t.tariffId==='string'&&/^[\x20-\x7e]{1,60}$/.test(t.tariffId)&&t.tariffId.trim()===t.tariffId
    &&t.tariffId!==LAB_TARIFF&&t.currency===options.currency
    &&(t.description===undefined||(Array.isArray(t.description)&&t.description.length>=1&&t.description.length<=3
      &&t.description.every(m=>keys(m,['format','language','content'])&&m.format==='UTF8'&&m.language==='en'
        &&text(m.content,255)&&m.content.length>0)))
    &&(t.validFrom===undefined||timestamp(t.validFrom))
    &&keys(e,['prices','taxRates'])&&Array.isArray(e.prices)&&e.prices.length>=1
    &&e.prices.length<=TARIFF_LIMITS.max_prices
    &&e.prices.every(x=>keys(x,['priceKwh','conditions'])&&price(x.priceKwh)&&conditions(x.conditions))
    &&(e.taxRates===undefined||(Array.isArray(e.taxRates)&&e.taxRates.length===1
      &&keys(e.taxRates[0],['type','tax'])&&e.taxRates[0].type==='GST'&&e.taxRates[0].tax===10));
}
// Online on OCPP 2.1 (SetDefaultTariff is a 2.1 message); transactions do not matter.
export const tariffTargetAllows=(result,station)=>observed(result,station,'ocpp2.1')!==null;

// DER control (der_commands_enabled; source patch 0003 adds the routes).
// OCPP 2.1 SetDERControl, GetDERControl and ClearDERControl to the command
// station only, online on OCPP 2.1. Four control types with lab bounds; the
// station's replies and DER messages (ReportDERControl, NotifyDERStartStop,
// NotifyDERAlarm) are read back from OCPPMessages, where CitrineOS keeps
// every message, through ha_reader (metadata.json grants exactly these actions).
export const DER_ROUTES={
  set:'/ocpp/2.1/smartcharging/setDERControl',
  get:'/ocpp/2.1/smartcharging/getDERControl',
  clear:'/ocpp/2.1/smartcharging/clearDERControl'};
export const DER_EVENTS_ROUTE='/lab/der-events';
export const DER_EVENT_ACTIONS=['ReportDERControl','NotifyDERStartStop','NotifyDERAlarm'];
export const DER_EVENT_LIMIT=20;
export const DER_REPORT_WAIT_MS=5000;
// control type -> its one SetDERControl field.
export const DER_CONTROLS={LimitMaxDischarge:'limitMaxDischarge',FixedPFInject:'fixedPFInject',
  FixedPFAbsorb:'fixedPFAbsorb',FixedVar:'fixedVar'};
export const DER_LIMITS={pct_max_discharge_power:[0,100],displacement:[0,1],var_setpoint_pct:[-100,100],
  max_duration_s:86400};
export const DER_VAR_UNITS=['PctMaxW','PctMaxVar','PctVarAvail'];
// Every OCPP 2.1 DERControlEnumType value, for Get and Clear filters.
export const DER_CONTROL_TYPES=['EnterService','FreqDroop','FreqWatt','FixedPFAbsorb','FixedPFInject',
  'FixedVar','Gradients','HFMustTrip','HFMayTrip','HVMustTrip','HVMomCess','HVMayTrip','LimitMaxDischarge',
  'LFMustTrip','LVMustTrip','LVMomCess','LVMayTrip','PowerMonitoringMustTrip','VoltVar','VoltWatt','WattPF','WattVar'];
export const derEnabled=o=>o.der_commands_enabled===true;
export const derRoute=pathname=>Object.values(DER_ROUTES).includes(pathname);
// The /lab/control-policy "der_commands" value.
export function derPolicy(o) {
  if(!derEnabled(o))return {enabled:false};
  return {enabled:true,station_id:commandStation(o),protocol:'ocpp2.1',routes:{...DER_ROUTES},
    events:DER_EVENTS_ROUTE,control_types:Object.keys(DER_CONTROLS),
    limits:Object.fromEntries(Object.entries(DER_LIMITS).map(([k,v])=>[k,Array.isArray(v)?[...v]:v]))};
}
const controlId=n=>typeof n==='string'&&/^[A-Za-z0-9._:-]{1,36}$/.test(n);
const within=(n,[min,max])=>Number.isFinite(n)&&n>=min&&n<=max;
// Optional start time and duration (s) of a control.
const period=c=>(c.startTime===undefined||timestamp(c.startTime))
  &&(c.duration===undefined||(Number.isFinite(c.duration)&&c.duration>=1&&c.duration<=DER_LIMITS.max_duration_s));
const DER_FIELDS={
  limitMaxDischarge:c=>keys(c,['priority','pctMaxDischargePower','startTime','duration'])
    &&within(c.pctMaxDischargePower,DER_LIMITS.pct_max_discharge_power),
  fixedPFInject:c=>keys(c,['priority','displacement','excitation','startTime','duration'])
    &&Number.isFinite(c.displacement)&&c.displacement>0&&c.displacement<=1&&typeof c.excitation==='boolean',
  fixedVar:c=>keys(c,['priority','setpoint','unit','startTime','duration'])
    &&within(c.setpoint,DER_LIMITS.var_setpoint_pct)&&DER_VAR_UNITS.includes(c.unit),
};
DER_FIELDS.fixedPFAbsorb=DER_FIELDS.fixedPFInject;
const derFilter=p=>(p.isDefault===undefined||typeof p.isDefault==='boolean')
  &&(p.controlType===undefined||DER_CONTROL_TYPES.includes(p.controlType))
  &&(p.controlId===undefined||controlId(p.controlId));
// A DER request inside the lab bounds, sent to the command station only.
export function validateDer(url,p,station=STATION,real=false) {
  if(!derRoute(url.pathname)||!stationAllowed(station,real)||queryStation(url)!==station)return false;
  if(url.pathname===DER_ROUTES.get)return keys(p,['requestId','isDefault','controlType','controlId'])
    &&int(p.requestId,0,2147483647)&&derFilter(p);
  if(url.pathname===DER_ROUTES.clear)return keys(p,['isDefault','controlType','controlId'])
    &&typeof p.isDefault==='boolean'&&derFilter(p);
  const field=DER_CONTROLS[p?.controlType];
  const c=field?p[field]:undefined;
  return !!field&&keys(p,['isDefault','controlId','controlType',field])&&typeof p.isDefault==='boolean'
    &&controlId(p.controlId)&&int(c?.priority,0,2147483647)&&DER_FIELDS[field](c)&&period(c);
}
// Online on OCPP 2.1 (DER control is a 2.1 feature); transactions do not matter.
export const derTargetAllows=(result,station)=>observed(result,station,'ocpp2.1')!==null;
// The command station's database id, once derTargetAllows has passed.
export const derStationId=result=>result.data.ChargingStations[0].id;
// ha_reader may filter only on columns it can select; its permission adds the
// tenant scope (metadata.json).
export const DER_EVENTS_QUERY=`query DerEvents($stationId: Int!, $actions: [String!]!, $limit: Int!) {
  OCPPMessages(where: {stationId: {_eq: $stationId}, origin: {_eq: "cs"}, type: {_eq: 2},
      action: {_in: $actions}}, order_by: [{timestamp: desc}, {id: desc}], limit: $limit) {
    id action timestamp payload
  }
}`;
// DER messages from the query result, newest first; null when malformed.
export function derEvents(result) {
  const rows=result?.data?.OCPPMessages;
  if(!Array.isArray(rows)||rows.length>DER_EVENT_LIMIT||rows.some(r=>!r||!DER_EVENT_ACTIONS.includes(r.action)
    ||typeof r.timestamp!=='string'||r.payload===null||typeof r.payload!=='object'||Array.isArray(r.payload)))return null;
  return rows.map(r=>({action:r.action,timestamp:r.timestamp,payload:r.payload}));
}
// The ReportDERControl payloads for requestId, oldest first, and whether the
// last one has arrived (tbc false or absent).
export function derReports(events,requestId) {
  const reports=events.filter(e=>e.action==='ReportDERControl'&&e.payload.requestId===requestId)
    .reverse().map(e=>e.payload);
  return {reports,complete:reports.length>0&&reports[reports.length-1].tbc!==true};
}

// EMS limits (source patch 0004): the station's NotifyChargingLimit and
// ClearedChargingLimit, stored by CitrineOS in ChargingLimits (one row per
// notification; a clear or a newer notification for the same EVSE and source
// makes it inactive). Read for the command station as ha_reader.
export const CHARGING_LIMITS_ROUTE='/lab/charging-limits';
export const CHARGING_LIMITS_LIMIT=20;
export const CHARGING_LIMITS_QUERY=`query ChargingLimits($stationId: Int!, $limit: Int!) {
  ChargingLimits(where: {stationId: {_eq: $stationId}}, order_by: [{createdAt: desc}, {id: desc}], limit: $limit) {
    id evseId chargingLimitSource isGridCritical isLocalGeneration chargingSchedule isActive clearedAt createdAt
  }
}`;
const bool=n=>n===null||typeof n==='boolean';
const iso=n=>n===null||(typeof n==='string'&&Number.isFinite(Date.parse(n)));
// {active, recent} newest first; null when the rows are not as expected.
export function chargingLimits(result) {
  const rows=result?.data?.ChargingLimits;
  if(!Array.isArray(rows)||rows.length>CHARGING_LIMITS_LIMIT||rows.some(r=>!r||!int(r.id,1,Number.MAX_SAFE_INTEGER)
    ||!(r.evseId===null||int(r.evseId,0,1000))||typeof r.chargingLimitSource!=='string'
    ||!bool(r.isGridCritical)||!bool(r.isLocalGeneration)||typeof r.isActive!=='boolean'
    ||!(r.chargingSchedule===null||Array.isArray(r.chargingSchedule))||!iso(r.clearedAt)||!iso(r.createdAt)))return null;
  const recent=rows.map(r=>({evse_id:r.evseId,source:r.chargingLimitSource,grid_critical:r.isGridCritical,
    local_generation:r.isLocalGeneration,active:r.isActive,schedule:r.chargingSchedule,
    reported_at:r.createdAt,cleared_at:r.clearedAt}));
  return {active:recent.filter(r=>r.active),recent};
}
// The /lab/control-policy "local_energy" value: what the gateway lets the
// command credential send for local generation and EMS operation, and where
// the station's EMS limits are read.
export const localEnergyPolicy=()=>({local_generation:{...LOCAL_GENERATION,ids:[...LOCAL_GENERATION.ids],
  evse_ids:[...LOCAL_GENERATION.evse_ids],protocol:'ocpp2.1'},operation_modes:[...OPERATION_MODES],
  charging_limits:CHARGING_LIMITS_ROUTE});
