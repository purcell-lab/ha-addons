# Scaffolding only. This image holds open-licence parts: Python, Java (for
# Josev's EXI codec), Josev (iso15118, Apache-2.0) and the station's Python
# dependencies. It holds no Imatra test harness code. run.sh fetches the
# harness at the pinned commit only after accept_licence is true, checks its
# SHA-256 and keeps it in /data. The harness is PolyForm Internal Use 1.0.0
# and may not be distributed: never build and push this image.
FROM python:3.11-slim-bookworm
ARG BUILD_ARCH
LABEL io.hass.name="Imatra Test Harness (internal use)" \
      io.hass.description="Imatra test station and Josev test EV on a virtual link" \
      io.hass.type="addon" \
      io.hass.version="0.1.0" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends default-jre-headless iproute2 jq curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir iso15118==0.31.2 aiofile typing_extensions \
         "paho-mqtt>=2.0" "cryptography>=42" tlslite-ng==0.8.2 \
    && python -c "import iso15118, paho.mqtt, tlslite; print('josev and station dependencies ok')"
COPY rootfs/ /
RUN chmod 0755 /opt/imatra-harness/run.sh
ENTRYPOINT ["/opt/imatra-harness/run.sh"]
