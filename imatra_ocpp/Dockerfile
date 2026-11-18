# imatra-ocpp (Apache-2.0, https://github.com/purcell-lab/imatra-ocpp) as a
# Home Assistant App, installed from the pinned commit's source archive.
ARG IMATRA_OCPP_COMMIT=22202140bc1c51ee32a8cd52d7b55746dd5d56a2

FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG BUILD_ARCH
ARG IMATRA_OCPP_COMMIT
LABEL io.hass.name="Imatra OCPP Bridge" \
      io.hass.description="Imatra devices as OCPP 2.1 / 2.0.1 charging stations" \
      io.hass.type="addon" \
      io.hass.version="0.1.0" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends jq && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "https://github.com/purcell-lab/imatra-ocpp/archive/${IMATRA_OCPP_COMMIT}.tar.gz" \
    && python -c "import imatra_ocpp, ocpp; print('imatra-ocpp', imatra_ocpp.__version__)" \
    && echo "${IMATRA_OCPP_COMMIT}" > /etc/imatra-ocpp-commit \
    && useradd -r -d /nonexistent -s /usr/sbin/nologin bridge
COPY rootfs/ /
RUN chmod 0755 /opt/imatra-ocpp/run.sh
ENTRYPOINT ["/opt/imatra-ocpp/run.sh"]
