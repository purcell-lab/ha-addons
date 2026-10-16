# CitrineOS Operator UI (Apache-2.0, https://github.com/citrineos/citrineos-core
# apps/operator-ui), built from the same pinned release as the lab server
# (v2.0.1) with this App's patch (operator-ui.patch) and run behind this
# App's Ingress proxy (rootfs/opt/operator-ui-ha). Built and published in
# GitHub Actions (operator-ui-publish.yml); Home Assistant pulls the image.
ARG BUILD_IMAGE=node:24.16.0@sha256:40ad9f3064e67d6860b4bc3fe1880b2953934fd6320ada990e45fe0efa6badd7
ARG RUN_IMAGE=node:24.16.0-slim@sha256:2c87ef9bd3c6a3bd4b472b4bec2ce9d16354b0c574f736c476489d09f560a203
ARG CORE_COMMIT=1a83638c31eebdb1dd8d6cdb0f5b8a9f142a1372

FROM ${BUILD_IMAGE} AS build
ARG CORE_COMMIT
WORKDIR /src
RUN git init -q . \
    && git remote add origin https://github.com/citrineos/citrineos-core.git \
    && git fetch -q --depth 1 origin "${CORE_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${CORE_COMMIT}"
COPY operator-ui.patch /tmp/operator-ui.patch
# Upstream tracks a development .env.local (an admin secret and password):
# it is removed so nothing from it is built in or shipped.
# NEXT_PUBLIC_* values are compiled into the browser bundle. The base path
# is a placeholder the Ingress proxy replaces with the per-install prefix;
# API URLs are same-origin paths the proxy forwards to the lab gateway.
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_BASE_PATH=/__ha_ingress_base__ \
    NEXT_PUBLIC_API_URL=/__ha_ingress_base__/hasura/v1/graphql \
    NEXT_PUBLIC_WS_URL= \
    NEXT_PUBLIC_CITRINE_CORE_URL=/__ha_ingress_base__/core \
    NEXT_PUBLIC_TRUSTED_PROXY_AUTH=true \
    NEXT_PUBLIC_AUTH_PROVIDER=generic \
    NEXT_PUBLIC_TENANT_ID=1 \
    NEXT_PUBLIC_APP_NAME="CitrineOS Lab" \
    NEXT_PUBLIC_LOGO_URL=/logo-collapsed.svg \
    NEXT_PUBLIC_DEFAULT_MAP_CENTER_LATITUDE=-27.47 \
    NEXT_PUBLIC_DEFAULT_MAP_CENTER_LONGITUDE=153.03
RUN git apply --check /tmp/operator-ui.patch && git apply /tmp/operator-ui.patch \
    && rm -f apps/operator-ui/.env apps/operator-ui/.env.* \
    && corepack enable \
    && pnpm install --frozen-lockfile --filter "@citrineos/operator-ui..." \
    && pnpm --filter "@citrineos/operator-ui..." build \
    && mkdir -p /out/app/apps/operator-ui/.next /out/usr/share/doc/citrineos-operator-ui \
    && cp -a apps/operator-ui/.next/standalone/. /out/app/ \
    && cp -a apps/operator-ui/.next/static /out/app/apps/operator-ui/.next/static \
    && cp -a apps/operator-ui/public /out/app/apps/operator-ui/public \
    && find /out/app -name '.env*' -prune -exec rm -rf {} + \
    && cp LICENSE /out/usr/share/doc/citrineos-operator-ui/LICENSE \
    && cp /tmp/operator-ui.patch /out/usr/share/doc/citrineos-operator-ui/operator-ui.patch \
    && echo "${CORE_COMMIT}" > /out/usr/share/doc/citrineos-operator-ui/COMMIT

FROM ${RUN_IMAGE}
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.type="app" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN groupadd --system --gid 1001 operatorui \
    && useradd --system --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin operatorui
COPY --from=build --chown=1001:1001 /out/app/ /app/
COPY --from=build /out/usr/ /usr/
COPY rootfs/ /
COPY UPSTREAM.md /usr/share/doc/citrineos-operator-ui/UPSTREAM.md
RUN mkdir -p /data \
    && node --check /opt/operator-ui-ha/run.mjs && node --check /opt/operator-ui-ha/proxy.mjs \
    && test -f /app/apps/operator-ui/server.js
WORKDIR /app
EXPOSE 8099
ENTRYPOINT ["node", "/opt/operator-ui-ha/run.mjs"]
