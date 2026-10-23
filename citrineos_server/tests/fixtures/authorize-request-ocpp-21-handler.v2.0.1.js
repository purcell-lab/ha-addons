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
import { AbstractHandler, AsRequestHandler, OcppError, recordAuthorizeResult, } from '@citrineos/base';
import { AttributeEnum, AuthorizationStatusEnum, AuthorizeCertificateStatusEnum, ErrorCode, IdTokenEnum, OCPP2_1, OCPP_CallAction, OCPPVersion, OCPP2_request_types, OCPP2_response_types, } from '@citrineos/types';
import { CertificateAuthorityService } from '../../../services/index.js';
import { validateOcpp21IdToken } from '../../../util/index.js';
import {} from '@citrineos/dal';
import { OCPP2_1_Mapper } from '@citrineos/dal';
let AuthorizeRequestOcpp21Handler = class AuthorizeRequestOcpp21Handler extends AbstractHandler {
    _ocppSender;
    _certificateAuthorityService;
    _authorizers;
    _authorizationRepository;
    _variableAttributeRepository;
    _tariffRepository;
    constructor({ logger, ocppSender, certificateAuthorityService, authorizers, authorizationRepository, variableAttributeRepository, tariffRepository, }) {
        super(logger);
        this._ocppSender = ocppSender;
        this._certificateAuthorityService = certificateAuthorityService;
        this._authorizers = authorizers;
        this._authorizationRepository = authorizationRepository;
        this._variableAttributeRepository = variableAttributeRepository;
        this._tariffRepository = tariffRepository;
    }
    async handle(message, props) {
        this._logger.info(this.createHandlerReceivedMessageLog('AuthorizeRequest'), message, props);
        const request = message.payload;
        const context = message.context;
        let response = {
            idTokenInfo: {
                status: AuthorizationStatusEnum.Unknown,
            },
        };
        // Validate ID token format after AJV schema validation, checking if the token conforms to expected type
        // e.g. if type is ISO14443, the token should be a hex string of even length
        const tokenValidation = validateOcpp21IdToken(request.idToken.type, request.idToken.idToken);
        if (!tokenValidation.isValid) {
            this._logger.warn(`Invalid ID token format`, {
                type: request.idToken.type,
                token: request.idToken.idToken,
                error: tokenValidation.errorMessage,
            });
            const messageId = message.context.correlationId;
            const error = new OcppError(messageId, ErrorCode.PropertyConstraintViolation, tokenValidation.errorMessage || 'Invalid token value for specified type');
            this._logger.error('Token validation failed:', tokenValidation.errorMessage);
            await this._ocppSender.sendCallErrorWithMessage(message, error);
            return;
        }
        if (message.payload.idToken.type === IdTokenEnum.NoAuthorization) {
            response = {
                ...response,
                idTokenInfo: {
                    status: AuthorizationStatusEnum.Accepted,
                },
            };
            await this._sendAuthorizeResult(message, response);
            return;
        }
        // Validate Contract Certificates based on OCPP 2.1 Part 2 C07
        if (request.iso15118CertificateHashData || request.certificate) {
            // TODO - implement validation using cached OCSP data described in C07.FR.05
            // If Charging Station is not able to validate a contract certificate,
            // it SHALL pass the contract certificate chain to the CSMS in certificate attribute (in PEM
            // format) of AuthorizeRequest for validation by CSMS, see C07.FR.06
            if (request.certificate) {
                response.certificateStatus =
                    await this._certificateAuthorityService.validateCertificateChainPem(request.certificate);
            }
            else if (request.iso15118CertificateHashData?.length) {
                response.certificateStatus =
                    await this._certificateAuthorityService.validateCertificateHashData(request.iso15118CertificateHashData);
            }
            if (response.certificateStatus !== AuthorizeCertificateStatusEnum.Accepted) {
                response = {
                    ...response,
                    idTokenInfo: {
                        status: response.certificateStatus === AuthorizeCertificateStatusEnum.CertificateExpired
                            ? AuthorizationStatusEnum.Expired
                            : AuthorizationStatusEnum.Invalid,
                    },
                };
                const messageConfirmation = await this._sendAuthorizeResult(message, response);
                this._logger.debug(this.createHandlerSentMessageLog('Authorize 2.1 Response'), messageConfirmation);
                return;
            }
        }
        const authorization = await this._authorizationRepository.readOnlyOneByQuerystring(context.tenantId, {
            idToken: request.idToken.idToken,
            type: OCPP2_1_Mapper.AuthorizationMapper.fromIdTokenEnumType(request.idToken.type),
        });
        if (authorization) {
            // Use flat fields directly instead of authorization.idTokenInfo
            const idTokenInfo = OCPP2_1_Mapper.AuthorizationMapper.toIdTokenInfo(authorization);
            if (idTokenInfo.status === AuthorizationStatusEnum.Accepted) {
                if (idTokenInfo.cacheExpiryDateTime &&
                    new Date() > new Date(idTokenInfo.cacheExpiryDateTime)) {
                    response = {
                        ...response,
                        idTokenInfo: {
                            status: AuthorizationStatusEnum.Invalid,
                            groupIdToken: idTokenInfo.groupIdToken,
                        },
                    };
                }
                else {
                    let evseIds = undefined;
                    const allowedConnectorTypes = authorization.allowedConnectorTypes ?? [];
                    const hasConnectorTypeRestriction = allowedConnectorTypes.length > 0;
                    if (hasConnectorTypeRestriction) {
                        evseIds = new Set();
                        const connectorTypes = await this._variableAttributeRepository.readAllByQuerystring(context.tenantId, {
                            tenantId: context.tenantId,
                            ocppConnectionName: message.context.ocppConnectionName,
                            component_name: 'Connector',
                            variable_name: 'ConnectorType',
                            type: AttributeEnum.Actual,
                        });
                        for (const connectorType of connectorTypes) {
                            if (allowedConnectorTypes.includes(connectorType.value)) {
                                evseIds.add(connectorType.component?.evse?.id);
                            }
                        }
                    }
                    if (evseIds && evseIds.size === 0) {
                        response = {
                            ...response,
                            idTokenInfo: {
                                status: AuthorizationStatusEnum.NotAllowedTypeEVSE,
                                groupIdToken: idTokenInfo.groupIdToken,
                                // TODO determine how/if to set personalMessage
                            },
                        };
                    }
                    else {
                        if (authorization.disallowedEvseIdPrefixes &&
                            authorization.disallowedEvseIdPrefixes.length > 0) {
                            evseIds = evseIds ? evseIds : new Set();
                            const evseIdAttributes = await this._variableAttributeRepository.readAllByQuerystring(context.tenantId, {
                                tenantId: context.tenantId,
                                ocppConnectionName: message.context.ocppConnectionName,
                                component_name: 'EVSE',
                                variable_name: 'EvseId',
                                type: AttributeEnum.Actual,
                            });
                            for (const evseIdAttribute of evseIdAttributes) {
                                const evseIdDisallowed = authorization.disallowedEvseIdPrefixes.some((disallowedEvseId) => evseIdAttribute.value.startsWith(disallowedEvseId));
                                if (evseIdDisallowed) {
                                    evseIds.delete(evseIdAttribute.component?.evse?.id);
                                }
                                else if (!hasConnectorTypeRestriction) {
                                    evseIds.add(evseIdAttribute.component?.evse?.id);
                                }
                            }
                        }
                        if (evseIds && evseIds.size === 0) {
                            response = {
                                ...response,
                                idTokenInfo: {
                                    status: AuthorizationStatusEnum.NotAtThisLocation,
                                    groupIdToken: idTokenInfo.groupIdToken,
                                    // TODO determine how/if to set personalMessage
                                },
                            };
                        }
                        else {
                            // TODO: Determine how to check for NotAtThisTime
                            response.idTokenInfo = idTokenInfo;
                            const evseId = [...(evseIds ? evseIds.values() : [])];
                            if (evseId.length > 0) {
                                response.idTokenInfo.evseId = [evseId.pop(), ...evseId];
                            }
                        }
                    }
                }
                for (const authorizer of this._authorizers) {
                    if (response.idTokenInfo.status !== AuthorizationStatusEnum.Accepted) {
                        break;
                    }
                    const result = await authorizer.authorize(authorization, context);
                    response.idTokenInfo.status =
                        OCPP2_1_Mapper.AuthorizationMapper.fromAuthorizationStatusEnumType(result);
                }
                // C17 - Prepaid card authorization (OCPP 2.1 only)
                if (authorization.isPrepaid &&
                    response.idTokenInfo.status === AuthorizationStatusEnum.Accepted) {
                    if (authorization.prepaidBalance != null && authorization.prepaidBalance > 0) {
                        // C17.FR.01: Prepaid token with positive balance
                        response.idTokenInfo.cacheExpiryDateTime = new Date().toISOString();
                        this._logger.debug(`C17: Prepaid authorization accepted for idToken ${authorization.idToken} with balance ${authorization.prepaidBalance}`);
                    }
                    else {
                        // C17.FR.02: Prepaid token with zero or negative balance
                        response.idTokenInfo.status =
                            OCPP2_1_Mapper.AuthorizationMapper.fromAuthorizationStatusEnumType(AuthorizationStatusEnum.NoCredit);
                        response.idTokenInfo.cacheExpiryDateTime = new Date().toISOString();
                        this._logger.debug(`C17: Prepaid authorization rejected (NoCredit) for idToken ${authorization.idToken} with balance ${authorization.prepaidBalance}`);
                    }
                }
            }
            else {
                // Blocked, Expired, Invalid, NoCredit, Unknown
                response.idTokenInfo = idTokenInfo;
            }
        }
        else {
            // Status is Unknown if no authorization found
            this._cancelContractIfNotAuthorized(response);
            const messageConfirmation = await this._sendAuthorizeResult(message, response);
            this._logger.debug(this.createHandlerSentMessageLog('Authorize 2.1 Response'), messageConfirmation);
            return;
        }
        if (response.idTokenInfo.status === AuthorizationStatusEnum.Accepted) {
            const tariffEnabled = await this._variableAttributeRepository.readAllByQuerystring(context.tenantId, {
                tenantId: context.tenantId,
                ocppConnectionName: message.context.ocppConnectionName,
                component_name: 'TariffCostCtrlr',
                variable_name: 'Enabled',
                variable_instance: 'Tariff',
                type: AttributeEnum.Actual,
            });
            // A device model boolean arrives as the string "false" or "true" (Part 2 §2.1.4), so it
            // has to be compared, not coerced.
            if (tariffEnabled[0]?.value?.toLowerCase() === 'true') {
                if (authorization.tariffId != null) {
                    const tariff = await this._tariffRepository.findById(context.tenantId, authorization.tariffId);
                    if (tariff) {
                        // I08.FR.09: CSMS SHALL NOT provide validFrom in AuthorizeResponse
                        const { validFrom: _, ...tariffForResponse } = OCPP2_1_Mapper.TariffMapper.toTariffType(tariff);
                        response.tariff =
                            tariffForResponse;
                    }
                }
            }
        }
        this._cancelContractIfNotAuthorized(response);
        const messageConfirmation = await this._sendAuthorizeResult(message, response);
        this._logger.debug(this.createHandlerSentMessageLog('Authorize 2.1 Response'), messageConfirmation);
    }
    /**
     * Per OCPP C07.FR.13, a contract certificate that was accepted is reported as ContractCancelled
     * when the token itself is not authorized.
     */
    _cancelContractIfNotAuthorized(response) {
        const contractCancelledStatuses = [
            AuthorizationStatusEnum.Blocked,
            AuthorizationStatusEnum.Expired,
            AuthorizationStatusEnum.Invalid,
            AuthorizationStatusEnum.Unknown,
        ];
        if (response.certificateStatus === AuthorizeCertificateStatusEnum.Accepted &&
            contractCancelledStatuses.includes(response.idTokenInfo.status)) {
            response.certificateStatus = OCPP2_1.AuthorizeCertificateStatusEnumType.ContractCancelled;
        }
    }
    /**
     * Records the Authorize decision, then sends the CallResult.
     */
    _sendAuthorizeResult(message, response) {
        const status = response.idTokenInfo?.status ??
            response.idTagInfo?.status;
        recordAuthorizeResult({
            status,
            ocppVersion: String(message.protocol),
            action: 'Authorize',
        });
        return this._ocppSender.sendCallResultWithMessage(message, response);
    }
};
AuthorizeRequestOcpp21Handler = __decorate([
    AsRequestHandler([OCPPVersion.OCPP2_1], OCPP_CallAction.Authorize),
    __metadata("design:paramtypes", [Object])
], AuthorizeRequestOcpp21Handler);
export { AuthorizeRequestOcpp21Handler };
//# sourceMappingURL=authorize-request-ocpp-21-handler.js.map