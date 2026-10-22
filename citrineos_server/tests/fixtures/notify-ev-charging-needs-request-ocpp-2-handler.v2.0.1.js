var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __metadata = (this && this.__metadata) || function (k, v) {
    if (typeof Reflect === "object" && typeof Reflect.metadata === "function") return Reflect.metadata(k, v);
};
// SPDX-FileCopyrightText: 2026 Contributors to the CitrineOS Project
//
// SPDX-License-Identifier: Apache-2.0
import { AbstractHandler, AsRequestHandler, } from '@citrineos/base';
import { EnergyTransferModeEnum, EventGroup, NotifyEVChargingNeedsStatusEnum, OCPP_2_VER_LIST, OCPP_CallAction, OCPP2_common_types, OCPP2_request_types, OCPP2_response_types, } from '@citrineos/types';
import { OCPP2_0_1_Mapper } from '@citrineos/dal';
let NotifyEVChargingNeedsRequestOcpp2Handler = class NotifyEVChargingNeedsRequestOcpp2Handler extends AbstractHandler {
    _ocppSender;
    _transactionEventRepository;
    _chargingProfileRepository;
    _smartChargingService;
    constructor({ logger, ocppSender, transactionEventRepository, chargingProfileRepository, smartChargingService, }) {
        super(logger);
        this._ocppSender = ocppSender;
        this._transactionEventRepository = transactionEventRepository;
        this._chargingProfileRepository = chargingProfileRepository;
        this._smartChargingService = smartChargingService;
    }
    async handle(message, props) {
        this._logger.info(this.createHandlerReceivedMessageLog('NotifyEVChargingNeedsRequest'), message, props);
        const request = message.payload;
        const tenantId = message.context.tenantId;
        const ocppConnectionName = message.context.ocppConnectionName;
        const givenNeeds = request.chargingNeeds;
        const activeTransaction = await this._transactionEventRepository.getActiveTransactionByStationIdAndEvseId(tenantId, ocppConnectionName, request.evseId);
        this._logger.info(`Found active transaction on station ${ocppConnectionName} evse ${request.evseId}: ${JSON.stringify(activeTransaction)}`);
        // OCPP 2.0.1 Part 2 K17.FR.06
        const hasAcOrDcChargingParameters = givenNeeds.dcChargingParameters !== null || givenNeeds.acChargingParameters !== null;
        this._logger.info(`Has AC or DC charging parameters: ${hasAcOrDcChargingParameters}`);
        const matchedChargingType = ((givenNeeds.dcChargingParameters ?? false) &&
            givenNeeds.requestedEnergyTransfer === EnergyTransferModeEnum.DC) ||
            ((givenNeeds.acChargingParameters ?? false) &&
                givenNeeds.requestedEnergyTransfer !== EnergyTransferModeEnum.DC);
        this._logger.info(`Matched chargingParameters and requestedEnergyTransfer type: ${matchedChargingType}`);
        if (!activeTransaction || !hasAcOrDcChargingParameters || !matchedChargingType) {
            await this._ocppSender.sendCallResultWithMessage(message, {
                status: NotifyEVChargingNeedsStatusEnum.Rejected,
            });
            return;
        }
        let chargingProfile;
        try {
            chargingProfile = await this._smartChargingService.calculateChargingProfile(request, activeTransaction, tenantId, ocppConnectionName);
        }
        catch (error) {
            this._logger.error(`Failed to calculate charging profile: ${error}`);
            await this._ocppSender.sendCallResultWithMessage(message, {
                status: NotifyEVChargingNeedsStatusEnum.Rejected,
            });
            return;
        }
        const chargingNeeds = await this._chargingProfileRepository.createChargingNeeds(tenantId, request, ocppConnectionName);
        this._logger.info(`Charging needs created: ${JSON.stringify(chargingNeeds)}`);
        await this._ocppSender.sendCallResultWithMessage(message, {
            status: NotifyEVChargingNeedsStatusEnum.Accepted,
        });
        const storedChargingProfile = await this._chargingProfileRepository.createOrUpdateChargingProfile(tenantId, OCPP2_0_1_Mapper.ChargingProfileMapper.fromChargingProfileType(chargingProfile), ocppConnectionName, request.evseId);
        this._logger.info(`Charging profile created: ${JSON.stringify(storedChargingProfile)}`);
        await this._ocppSender.sendCall({
            ocppConnectionName,
            tenantId: message.context.tenantId,
            protocol: message.protocol,
            action: OCPP_CallAction.SetChargingProfile,
            eventGroup: EventGroup.SmartCharging,
            payload: {
                evseId: request.evseId,
                chargingProfile,
            },
        });
    }
};
NotifyEVChargingNeedsRequestOcpp2Handler = __decorate([
    AsRequestHandler(OCPP_2_VER_LIST, OCPP_CallAction.NotifyEVChargingNeeds),
    __metadata("design:paramtypes", [Object])
], NotifyEVChargingNeedsRequestOcpp2Handler);
export { NotifyEVChargingNeedsRequestOcpp2Handler };
//# sourceMappingURL=notify-ev-charging-needs-request-ocpp-2-handler.js.map