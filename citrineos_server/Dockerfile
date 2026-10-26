# CitrineOS v2.1.0 (Apache-2.0, https://github.com/citrineos/citrineos-core)
# built from source at the pinned commit with this App's patches (patches/),
# modelled on upstream apps/ocpp-server/deploy.Dockerfile. The commit and both
# node images are pinned here (multi-arch index digests) and in
# compatibility-lock.json; no build argument can select another source or base.
# Each stage runs on the target architecture (no --platform), so native modules
# (sqlite3, bufferutil) are built for it. Published by GitHub Actions
# (citrineos-server-publish.yml); Home Assistant pulls the image.
FROM node:24.16.0@sha256:40ad9f3064e67d6860b4bc3fe1880b2953934fd6320ada990e45fe0efa6badd7 AS build
WORKDIR /usr/local/apps/citrineos
RUN git init -q . \
    && git remote add origin https://github.com/citrineos/citrineos-core.git \
    && git fetch -q --depth 1 origin 4fd7599b91c2fb6e6065e7c9b94be69880cced27 \
    && git checkout -q FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "4fd7599b91c2fb6e6065e7c9b94be69880cced27"
COPY patches/ /tmp/ha-patches/
# Every patch must apply cleanly to the pinned source, or the build fails.
RUN set -e; for patch in /tmp/ha-patches/*.patch; do \
      git apply --check "$patch"; git apply "$patch"; echo "applied $(basename "$patch")"; \
    done
RUN corepack enable \
    && pnpm install --frozen-lockfile --filter "@citrineos/ocpp-server..." \
    && pnpm --filter "@citrineos/ocpp-server..." build \
    && pnpm --filter "@citrineos/ocpp-server" deploy --legacy --prod /deploy \
    && cp apps/ocpp-server/.sequelizerc /deploy/.sequelizerc \
    && mkdir -p /deploy-doc \
    && cp LICENSE /deploy-doc/LICENSE \
    && cp /tmp/ha-patches/*.patch /deploy-doc/ \
    && git rev-parse HEAD > /deploy-doc/COMMIT
# The runtime layout launch.mjs expects; a missing file fails the build.
RUN cd /deploy && for f in dist/index.js dist/scripts/provision-partitions.js dist/assets/logo.png \
      dist/config/sequelize-bridge.config.js node_modules/.bin/sequelize-cli .sequelizerc; do \
      test -e "$f" || { echo "missing $f" >&2; exit 1; }; done \
    && test -n "$(ls dist/migrations/*.js)" \
    && grep -q "ha-citrine patch (0001-ocpp21-charging-needs)" \
      node_modules/@citrineos/ocpp/dist/src/handlers/requests/2/notify-ev-charging-needs-request-ocpp-2-handler.js \
    && grep -q "ha-citrine patch (0002-ocpp21-allowed-energy-transfer)" \
      node_modules/@citrineos/ocpp/dist/src/handlers/requests/2/authorize-request-ocpp-21-handler.js \
    && grep -q "ha-citrine patch (0003-ocpp21-der-control)" \
      node_modules/@citrineos/ocpp/dist/src/apis/ocpp/2/smart-charging.js \
    && grep -q "ha-citrine patch (0003-ocpp21-der-control)" \
      node_modules/@citrineos/base/dist/src/interfaces/schema/mapping-schema.js

FROM node:24.16.0-slim@sha256:2c87ef9bd3c6a3bd4b472b4bec2ce9d16354b0c574f736c476489d09f560a203
ARG BUILD_ARCH
LABEL io.hass.name="CitrineOS Isolated Lab" \
      io.hass.description="Private laboratory server with opt-in scoped simulator controls" \
      io.hass.type="addon" \
      io.hass.version="0.11.0" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons" \
      org.opencontainers.image.licenses="Apache-2.0"
COPY --from=build /deploy /usr/local/apps/citrineos/apps/ocpp-server
COPY --from=build /deploy-doc /usr/share/doc/citrineos-core
COPY rootfs/ /opt/citrine-ha/
COPY compatibility-lock.json /opt/citrine-ha/compatibility-lock.json
RUN mkdir -p /data && chown node:node /data
USER root
WORKDIR /opt/citrine-ha
# Disconnected by default; explicit isolated mode uses the guarded launcher.
ENTRYPOINT ["node", "/opt/citrine-ha/launch.mjs"]
CMD []
