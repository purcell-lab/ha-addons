# The index digest was resolved from the upstream v2.0.1 release tag.
# No build argument can select another upstream image.
FROM ghcr.io/citrineos/citrineos-server:v2.0.1@sha256:15316dff5f661714e2fddfa2f25baebea4c11d8d6aa2a9bb254a98159da58378

LABEL io.hass.name="CitrineOS Isolated Lab" \
      io.hass.description="Private laboratory server with opt-in scoped simulator controls" \
      io.hass.type="addon" \
      io.hass.version="0.4.0" \
      io.hass.arch="amd64" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons"

COPY rootfs/ /opt/citrine-ha/
COPY compatibility-lock.json /opt/citrine-ha/compatibility-lock.json
COPY rootfs/rbac-rules.json /usr/local/apps/citrineos/apps/ocpp-server/rbac-rules.json
RUN mkdir -p /data && chown node:node /data
USER root
WORKDIR /opt/citrine-ha
# Disconnected by default; explicit isolated mode uses the guarded launcher.
ENTRYPOINT ["node", "/opt/citrine-ha/launch.mjs"]
CMD []
