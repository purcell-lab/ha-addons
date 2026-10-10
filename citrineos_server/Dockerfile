# The index digest was resolved from the upstream v2.0.1 release tag.
# No build argument can select another upstream image.
FROM ghcr.io/citrineos/citrineos-server:v2.0.1@sha256:15316dff5f661714e2fddfa2f25baebea4c11d8d6aa2a9bb254a98159da58378

LABEL io.hass.name="CitrineOS Compatibility Lab" \
      io.hass.description="Disconnected-only CitrineOS packaging and compatibility gate" \
      io.hass.type="addon" \
      io.hass.version="0.1.0" \
      io.hass.arch="amd64" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons"

COPY rootfs/ /opt/citrine-ha/
COPY compatibility-lock.json /opt/citrine-ha/compatibility-lock.json
RUN mkdir -p /data && chown node:node /data
USER node
WORKDIR /opt/citrine-ha
# Deliberately replace upstream entrypoint: it otherwise defaults to migrations.
# Neither upstream Node server nor its migration script runs in this package.
ENTRYPOINT ["node", "/opt/citrine-ha/guard.mjs"]
CMD []
