# EVerest 2025.10.0 software-in-the-loop charger, repackaged for Home Assistant.
#
# The EVerest runtime comes from ghcr.io/purcell-lab/everest-runtime
# (everest_runtime/), a stripped extract of the upstream 4.3 GB demo image,
# so this build pulls about 50 MB instead. This stage selects the modules
# this App uses into a Debian 12 base (same ABI as the upstream build).
# The release check (everest-runtime.yml) proves the result is file-for-file
# identical to the image built from the upstream demo image directly.
ARG EVEREST_RUNTIME=ghcr.io/purcell-lab/everest-runtime:2025.10.0-1
ARG DEBIAN_IMAGE=debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

FROM ${EVEREST_RUNTIME} AS runtime

FROM ${DEBIAN_IMAGE} AS slim
ARG MODULES="API Auth DummyTokenProviderManual EnergyManager EnergyNode ErrorHistory EvManager EvseManager EvseSecurity OCPP201 PersistentStore System YetiSimulator"
COPY --from=runtime /opt/everest/bin/manager /stage/opt/everest/bin/manager
COPY --from=runtime /opt/everest/lib/ /stage/opt/everest/lib/
COPY --from=runtime /opt/everest/share/everest/ /stage/opt/everest/share/everest/
COPY --from=runtime /opt/everest/etc/everest/certs/ /stage/opt/everest/etc/everest/certs/
COPY --from=runtime /opt/everest/libexec/everest/modules/ /tmp/dist-modules/
COPY --from=runtime /usr/share/doc/everest/ /stage/usr/share/doc/everest/
RUN set -eu; \
    mkdir -p /stage/opt/everest/libexec/everest/modules; \
    for module in ${MODULES}; do cp -a "/tmp/dist-modules/${module}" /stage/opt/everest/libexec/everest/modules/; done; \
    rm -rf /tmp/dist-modules

FROM ${DEBIAN_IMAGE}
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.type="app" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends \
       libboost-log1.74.0 libboost-program-options1.74.0 libboost-filesystem1.74.0 \
       libssl3 libsqlite3-0 libcap2 libstdc++6 ca-certificates \
       mosquitto nginx-light python3 python3-paho-mqtt python3-yaml procps \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/nginx /data
COPY --from=slim /stage/ /
COPY rootfs/ /
COPY UPSTREAM.md /usr/share/doc/everest/UPSTREAM.md
# Upstream's admin-panel controller listens on all interfaces; this App
# replaces it with a stub that only tracks the manager's lifetime.
RUN install -m 0755 /opt/ha-everest/controller-stub.sh /opt/everest/bin/controller \
    && python3 -m py_compile /opt/ha-everest/*.py
WORKDIR /data
ENTRYPOINT ["python3", "/opt/ha-everest/app.py"]
