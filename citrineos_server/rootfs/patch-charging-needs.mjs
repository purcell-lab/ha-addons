// Build-time patch to upstream CitrineOS v2.0.1: OCPP 2.1 charging needs
// (ISO 15118-20 bidirectional DC, DC_BPT) were always answered Rejected.
//
// NotifyEVChargingNeedsRequestOcpp2Handler accepts DC needs only when
// requestedEnergyTransfer is exactly `DC`, so a 2.1 EV that asks for `DC_BPT`
// (or `DC_ACDP`, `DC_ACDP_BPT`) with dcChargingParameters is Rejected. A
// station then refuses the EV's energy transfer: Trialog's ComboCS4M-SW ended
// its transaction with `ReqEnergyTransferRejected` (Plugfest, 23 October 2026).
// Upstream's automatic profile calculation also only knows the 2.0.1 modes
// (it throws "Unsupported energy transfer mode", which is Rejected too).
//
// The patch matches the 2.1 DC modes like `DC`. For any mode that is not a
// 2.0.1 mode, it stores the charging needs, answers Accepted and sends no
// automatic profile: the lab's own TxProfile (scoped command path) sets the
// V2X operation mode, and an automatic profile would stack above it. The
// 2.0.1 modes (AC_*, DC) are unchanged.
//
// The build fails unless the file is the exact upstream v2.0.1 build (or this
// patch's output), so a new upstream version cannot silently drop the patch.
// `--check` succeeds only for a patched file.
import crypto from 'node:crypto';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

export const TARGET='/usr/local/apps/citrineos/apps/ocpp-server/node_modules/@citrineos/ocpp/dist/src/handlers/requests/2/notify-ev-charging-needs-request-ocpp-2-handler.js';
export const UPSTREAM_SHA256='e8104b76a8e1a880c50c94d6db1ccb61af99a8e060d57edd15094cbffa01fc6c';
export const PATCHED_SHA256='1106e46f464c261995380c3f029489522c189202832612f283de0cd6caa74bc7';
export const MARKER='ha-citrine patch (patch-charging-needs.mjs)';

export const EDITS=[
  {
    name:'match 2.1 DC modes',
    anchor:`        const matchedChargingType = ((givenNeeds.dcChargingParameters ?? false) &&
            givenNeeds.requestedEnergyTransfer === EnergyTransferModeEnum.DC) ||
`,
    replacement:`        // ha-citrine patch (patch-charging-needs.mjs): the OCPP 2.1 DC modes
        // (bidirectional DC_BPT, DC_ACDP, DC_ACDP_BPT) carry dcChargingParameters too.
        const matchedChargingType = ((givenNeeds.dcChargingParameters ?? false) &&
            ['DC', 'DC_BPT', 'DC_ACDP', 'DC_ACDP_BPT'].includes(givenNeeds.requestedEnergyTransfer)) ||
`,
  },
  {
    name:'accept 2.1 modes without an automatic profile',
    anchor:`        let chargingProfile;
        try {
            chargingProfile = await this._smartChargingService.calculateChargingProfile(`,
    replacement:`        // ha-citrine patch (patch-charging-needs.mjs): upstream calculates profiles
        // for the 2.0.1 modes only. For an OCPP 2.1 mode, store the needs and accept;
        // no automatic profile, the lab's TxProfile sets the V2X operation mode.
        if (!['AC_single_phase', 'AC_two_phase', 'AC_three_phase', 'DC'].includes(givenNeeds.requestedEnergyTransfer)) {
            try {
                const chargingNeeds = await this._chargingProfileRepository.createChargingNeeds(tenantId, request, ocppConnectionName);
                this._logger.info(\`Charging needs created (\${givenNeeds.requestedEnergyTransfer}, no automatic profile): \${JSON.stringify(chargingNeeds)}\`);
            }
            catch (error) {
                this._logger.error(\`Failed to store charging needs: \${error}\`);
            }
            await this._ocppSender.sendCallResultWithMessage(message, {
                status: NotifyEVChargingNeedsStatusEnum.Accepted,
            });
            return;
        }
        let chargingProfile;
        try {
            chargingProfile = await this._smartChargingService.calculateChargingProfile(`,
  },
];

export function sha256(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}
// Exact text edits; each anchor must occur exactly once.
export function applyEdits(text) {
  if(text.includes(MARKER))throw new Error('notify-ev-charging-needs-request-ocpp-2-handler.js is already partly patched');
  for(const {name,anchor} of EDITS) {
    const count=text.split(anchor).length-1;
    if(count!==1)throw new Error(`Anchor "${name}" found ${count} times, expected exactly once`);
  }
  return EDITS.reduce((out,{anchor,replacement})=>out.replace(anchor,()=>replacement),text);
}
// Returns the patched text; a file already patched by this version is unchanged.
export function patch(text) {
  const digest=sha256(text);
  if(digest===PATCHED_SHA256)return text;
  if(digest!==UPSTREAM_SHA256)
    throw new Error('notify-ev-charging-needs-request-ocpp-2-handler.js is not the pinned CitrineOS v2.0.1 build');
  const patched=applyEdits(text);
  if(sha256(patched)!==PATCHED_SHA256)throw new Error('Patched file does not match the expected result');
  return patched;
}
export function main(args=process.argv.slice(2)) {
  const check=args.includes('--check');
  const path=args.find(a=>a!=='--check')??TARGET;
  const text=fs.readFileSync(path,'utf8');
  if(check) {
    if(sha256(text)!==PATCHED_SHA256)throw new Error(`${path} is not patched`);
    console.log(`${path} is patched (OCPP 2.1 charging needs)`);
    return;
  }
  const patched=patch(text);
  if(patched===text){console.log(`${path} is already patched`);return;}
  fs.writeFileSync(path,patched);
  const syntax=spawnSync(process.execPath,['--check',path],{encoding:'utf8'});
  if(syntax.status!==0) {
    fs.writeFileSync(path,text);
    throw new Error(`Patched file does not parse: ${syntax.stderr.trim()}`);
  }
  console.log(`patched ${path}: OCPP 2.1 charging needs (DC_BPT) are accepted`);
}
if(process.argv[1]===fileURLToPath(import.meta.url)) {
  try {main();}
  catch(error) {console.error(`patch-charging-needs: ${error.message}`);process.exit(1);}
}
