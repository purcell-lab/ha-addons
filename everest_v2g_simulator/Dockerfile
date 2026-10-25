# EVerest 2026.10.0-rc1 software-in-the-loop bidirectional DC charger
# (ISO 15118-20 DC_BPT) and EV simulator with OCPP 2.1 DER control,
# repackaged for Home Assistant.
#
# The EVerest runtime comes from ghcr.io/purcell-lab/everest-runtime. For
# 2026.10 there is no prebuilt everest-demo image, so that runtime is
# everest-core compiled from source (everest_runtime_source/) and extracted
# like the 2025.10.0 one (everest_runtime/Dockerfile): stripped, FROM
# scratch. This stage selects the modules this App uses into a Debian 12 base
# (the same ABI as the everest-ci build image).
#
# Until the runtime is published and pinned by digest, CI compiles it
# (everest-runtime-source-build.yml) and builds this App from that local
# image; releases accept only the pinned, public runtime.
ARG EVEREST_RUNTIME=ghcr.io/purcell-lab/everest-runtime:2026.10.0-rc1-1
ARG DEBIAN_IMAGE=debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

FROM ${EVEREST_RUNTIME} AS runtime

FROM ${DEBIAN_IMAGE} AS slim
ARG MODULES="API Auth DCSupplySimulator DummyTokenProviderManual EnergyManager EnergyNode ErrorHistory Evse15118D20 EvManager EvseManager EvseSecurity IMDSimulator OCPPmulti PersistentStore PyEvJosev SlacSimulator System YetiSimulator"
COPY --from=runtime /opt/everest/bin/manager /stage/opt/everest/bin/manager
COPY --from=runtime /opt/everest/lib/ /stage/opt/everest/lib/
COPY --from=runtime /opt/everest/share/everest/ /stage/opt/everest/share/everest/
# No certificates are copied: each install generates its own test PKI (pki.py).
COPY --from=runtime /opt/everest/libexec/everest/3rd_party/josev/ /stage/opt/everest/libexec/everest/3rd_party/josev/
COPY --from=runtime /opt/everest/libexec/everest/modules/ /tmp/dist-modules/
COPY --from=runtime /usr/share/doc/everest/ /stage/usr/share/doc/everest/
RUN set -eu; \
    mkdir -p /stage/opt/everest/libexec/everest/modules; \
    for module in ${MODULES}; do cp -a "/tmp/dist-modules/${module}" /stage/opt/everest/libexec/everest/modules/; done; \
    rm -rf /tmp/dist-modules; \
    find /stage -name '__pycache__' -prune -exec rm -rf {} +

FROM ${DEBIAN_IMAGE} AS pydeps
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends python3-pip && rm -rf /var/lib/apt/lists/*
COPY requirements-josev.txt /tmp/
RUN pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
      --target /stage/usr/local/lib/python3.11/dist-packages -r /tmp/requirements-josev.txt

# Josev needs Java only for its EXI codec (EXICodec.jar through py4j). A
# jlink runtime with just the modules those jars use (jdeps) replaces the
# full openjdk-17-jre-headless package: about 184 MB down to a few tens.
# --add-options bakes a small fixed heap into the runtime (Green-class
# hosts have 4 GB), so it applies however the manager starts Josev.
FROM ${DEBIAN_IMAGE} AS jre
ARG JAVA_MODULES="java.base,java.compiler,java.desktop,java.management,java.naming,java.rmi,java.sql,java.xml,jdk.unsupported"
RUN mkdir -p /usr/share/man/man1 \
    && apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends openjdk-17-jdk-headless binutils \
    && rm -rf /var/lib/apt/lists/* \
    && jlink --add-modules "${JAVA_MODULES}" --strip-debug --no-man-pages \
       --no-header-files --compress=2 \
       --add-options="-Xms16m -Xmx128m -XX:MaxMetaspaceSize=64m -XX:+UseSerialGC -XX:TieredStopAtLevel=1 -Xss512k" \
       --output /stage/opt/java \
    && mkdir -p /stage/usr/bin && ln -s /opt/java/bin/java /stage/usr/bin/java \
    && install -D -m 0644 /usr/share/doc/openjdk-17-jre-headless/copyright \
       /stage/usr/share/doc/openjdk-17/copyright

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
       libboost-log1.74.0 libboost-program-options1.74.0 libboost-filesystem1.74.0 libboost-thread1.74.0 \
       libssl3 libsqlite3-0 libcap2 libstdc++6 ca-certificates \
       mosquitto nginx-light python3 python3-paho-mqtt python3-yaml procps \
       python3-pydantic python3-cryptography python3-netifaces \
       python3-psutil python3-dateutil openssl iproute2 nftables \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/nginx /data
COPY --from=slim /stage/ /
COPY --from=pydeps /stage/ /
COPY --from=jre /stage/ /
COPY rootfs/ /
COPY UPSTREAM.md /usr/share/doc/everest/UPSTREAM.md
# EVerest 2026.10's manager no longer starts the admin-panel controller, so
# the stub that replaced it (0.1.x) is gone. patch_josev.py: a failed EV
# session (for example an unanswered SDP request) no longer ends upstream's
# plug-in loop; each plug-in starts a fresh stack; the simulated EV may
# discharge 25 kW and waits for authorisation longer than the charger. The
# board limits come from YetiSimulator's caps_max_current_A (configure.py),
# not a binary patch. rootfs/ adds the App's HaGridSupport module.
RUN python3 /opt/ha-everest/patch_josev.py \
    && python3 -m py_compile /opt/ha-everest/*.py \
    && python3 -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]" \
       /opt/everest/libexec/everest/modules/HaGridSupport/module.py \
    && python3 -c "import pydantic, py4j, aiofile, environs, netifaces, psutil, cryptography"
WORKDIR /data
ENTRYPOINT ["python3", "/opt/ha-everest/app.py"]
