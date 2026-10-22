# The index digest was resolved from the upstream v2.0.1 release tag.
# No build argument can select another upstream image.
FROM ghcr.io/citrineos/citrineos-server:v2.0.1@sha256:15316dff5f661714e2fddfa2f25baebea4c11d8d6aa2a9bb254a98159da58378

ARG BUILD_ARCH
LABEL io.hass.name="CitrineOS Isolated Lab" \
      io.hass.description="Private laboratory server with opt-in scoped simulator controls" \
      io.hass.type="addon" \
      io.hass.version="0.7.4" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons"

COPY rootfs/ /opt/citrine-ha/
COPY compatibility-lock.json /opt/citrine-ha/compatibility-lock.json
COPY rootfs/rbac-rules.json /usr/local/apps/citrineos/apps/ocpp-server/rbac-rules.json
# Upstream reconnect race (#67): a reconnect waits until the old connection is
# deregistered. The build fails unless the file is the exact v2.0.1 build.
RUN node /opt/citrine-ha/patch-reconnect.mjs \
    && node /opt/citrine-ha/patch-reconnect.mjs --check
# Upstream rejects OCPP 2.1 charging needs (DC_BPT); same exact-build guard.
RUN node /opt/citrine-ha/patch-charging-needs.mjs \
    && node /opt/citrine-ha/patch-charging-needs.mjs --check
RUN mkdir -p /data && chown node:node /data
USER root
WORKDIR /opt/citrine-ha
# Disconnected by default; explicit isolated mode uses the guarded launcher.
ENTRYPOINT ["node", "/opt/citrine-ha/launch.mjs"]
CMD []
