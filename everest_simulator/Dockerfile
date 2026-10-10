# EVerest 2025.10.0 software-in-the-loop charger, repackaged for Home Assistant.
#
# The upstream demo image (about 4.3 GB compressed) contains the full build
# toolchain and sources. Only the installed runtime of the modules this App
# uses is copied, stripped, into a Debian 12 base (same ABI as the build).
ARG EVEREST_IMAGE=ghcr.io/everest/everest-demo/manager:2025.10.0-single-phase@sha256:9165d0937323ae61ee2e496f68f3c4a465ed9099740e489df1f0161265492756
ARG DEBIAN_IMAGE=debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

FROM ${EVEREST_IMAGE} AS everest
# Collect licence/notice files of EVerest and its CPM-fetched dependencies.
RUN set -eu; mkdir -p /licences; cp /ext/source/LICENSE /licences/EVerest-LICENSE; \
    cd /ext/cache/cpm; \
    find . -mindepth 3 -maxdepth 3 -type f \( -iname 'LICENSE*' -o -iname 'LICENCE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) \
      | while read -r f; do dep="${f#./}"; dep="${dep%%/*}"; install -D -m 0644 "$f" "/licences/third_party/${dep}/$(basename "$f")"; done

FROM ${DEBIAN_IMAGE} AS slim
ARG MODULES="API Auth DummyTokenProviderManual EnergyManager EnergyNode ErrorHistory EvManager EvseManager EvseSecurity OCPP201 PersistentStore System YetiSimulator"
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends binutils && rm -rf /var/lib/apt/lists/*
COPY --from=everest /ext/dist/bin/manager /stage/opt/everest/bin/manager
COPY --from=everest /ext/dist/lib/ /tmp/dist-lib/
COPY --from=everest /ext/dist/share/everest/ /stage/opt/everest/share/everest/
COPY --from=everest /ext/dist/etc/everest/certs/ /stage/opt/everest/etc/everest/certs/
COPY --from=everest /ext/dist/libexec/everest/modules/ /tmp/dist-modules/
COPY --from=everest /licences/ /stage/usr/share/doc/everest/
RUN set -eu; \
    mkdir -p /stage/opt/everest/lib /stage/opt/everest/libexec/everest/modules; \
    cp -a /tmp/dist-lib/*.so* /tmp/dist-lib/everest /stage/opt/everest/lib/; \
    for module in ${MODULES}; do cp -a "/tmp/dist-modules/${module}" /stage/opt/everest/libexec/everest/modules/; done; \
    find /stage/opt/everest -type f | while read -r f; do \
      if [ "$(head -c 4 "$f" | od -An -c | tr -d ' ')" = '177ELF' ]; then strip --strip-unneeded "$f"; fi; \
    done; \
    rm -rf /tmp/dist-lib /tmp/dist-modules

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
