# EVerest built from source for the EVerest runtime image. This is a build
# input, not a Home Assistant App (there is no config.yaml).
#
# There is no prebuilt everest-demo manager image for EVerest 2026.x, so this
# compiles everest-core at a pinned tag in EVerest's own CI build image
# (everest-ci build-kit-base, Debian 12: the same ABI as the Apps' Debian 12
# base). Only the modules in MODULES are configured and built
# (EVEREST_INCLUDE_MODULES), with tests, applications, run scripts and the
# Rust bindings off.
#
# The output lays EVerest out exactly as the everest-demo manager image does
# (/ext/dist, /ext/source/LICENSE and the licence files of the CPM-fetched
# dependencies under /ext/cache/cpm/<dependency>/<id>/), so the unchanged
# everest_runtime/Dockerfile extracts, prunes and strips it into the
# FROM scratch runtime image:
#
#   docker build -t everest-dist:local everest_runtime_source
#   docker build --build-arg EVEREST_IMAGE=everest-dist:local \
#     --build-arg MODULES="$(cat everest_runtime_source/MODULES)" \
#     --build-arg RUNTIME_VERSION="$(cat everest_runtime_source/VERSION)" \
#     -t everest-runtime:local everest_runtime
#
# .github/scripts/everest_runtime_source.sh runs both steps.
ARG BUILD_KIT_IMAGE=ghcr.io/everest/everest-ci/build-kit-base:v1.6.0@sha256:ca9da7d85c09295cbbfb75167b28eb2f17488a1e4dbca12892f3f848e9bf2f2f
ARG DEBIAN_IMAGE=debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

FROM ${BUILD_KIT_IMAGE} AS build
ARG EVEREST_CORE_REPOSITORY=https://github.com/EVerest/everest-core.git
ARG EVEREST_CORE_TAG=2026.10.0-rc1
ARG EVEREST_CORE_COMMIT=f45ba0d0827f29d53d516fec98960f2528460802
# Modules to configure and build (EVEREST_INCLUDE_MODULES). Keep in sync with
# MODULES (the runtime extraction list), which also names OCPP201 so that its
# share directory (libocpp's component configs and migrations, which OCPPmulti
# reads) survives the extraction.
ARG BUILD_MODULES="API Auth DCSupplySimulator DummyTokenProviderManual EnergyManager EnergyNode ErrorHistory Evse15118D20 EvManager EvseManager EvseSecurity IMDSimulator OCPP201 OCPPmulti PersistentStore PyEvJosev SlacSimulator System YetiSimulator"
ARG BUILD_JOBS=""
ENV CPM_SOURCE_CACHE=/ext/cache/cpm
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# One step, so the cached layer holds only the installed tree and licences
# (the source, build tree and dependency sources are removed again).
RUN set -eux; \
    git clone --depth 1 --branch "${EVEREST_CORE_TAG}" "${EVEREST_CORE_REPOSITORY}" /ext/source; \
    test "$(git -C /ext/source rev-parse HEAD)" = "${EVEREST_CORE_COMMIT}"; \
    # MinSizeRel, the build type everest-core's own CI uses (with GCC 12 in
    # this image). Release (-O3) trips a GCC 12 -Warray-bounds false positive
    # in lib/everest/io (mdns.cpp) under the module's -Werror; that one
    # warning is also kept from failing the build.
    cmake -S /ext/source -B /ext/build -G Ninja \
      -DCMAKE_BUILD_TYPE=MinSizeRel \
      -DCMAKE_CXX_FLAGS="-Wno-error=array-bounds -Wno-error=stringop-overflow" \
      -DCMAKE_INSTALL_PREFIX=/ext/dist \
      -DWHEEL_INSTALL_PREFIX=/ext/wheels \
      -DCPM_SOURCE_CACHE=/ext/cache/cpm \
      -DEVEREST_INCLUDE_MODULES="$(echo ${BUILD_MODULES} | tr ' ' ';')" \
      -DBUILD_TESTING=OFF \
      -DEVEREST_BUILD_APPLICATIONS=OFF \
      -DEVEREST_ENABLE_RUN_SCRIPT_GENERATION=OFF \
      -DEVEREST_ENABLE_RS_SUPPORT=OFF \
      -DEVEREST_ENABLE_JS_SUPPORT=OFF \
      -DEVEREST_ENABLE_PY_SUPPORT=ON \
      -DISO15118_2_GENERATE_AND_INSTALL_CERTIFICATES=OFF \
      -DENABLE_GRPC_GENERATOR=OFF; \
    # One job per CPU (ninja's default of CPUs + 2 risks running out of
    # memory on 16 GB CI runners with libocpp's large translation units).
    ninja -C /ext/build -j"${BUILD_JOBS:-$(nproc)}" install/strip; \
    for module in ${BUILD_MODULES}; do test -d "/ext/dist/libexec/everest/modules/${module}"; done; \
    test -x /ext/dist/bin/manager; \
    test -d /ext/dist/libexec/everest/3rd_party/josev; \
    test -d /ext/dist/share/everest/modules/OCPP201/component_config/standardized; \
    test -d /ext/dist/share/everest/modules/OCPP201/core_migrations; \
    test -d /ext/dist/share/everest/modules/OCPP201/device_model_migrations; \
    # The extraction copies these; this build has no demo certificates and no
    # admin panel web UI.
    mkdir -p /ext/dist/etc/everest/certs /ext/dist/share/everest/www; \
    # Licence and notice files of the fetched dependencies, in the CPM cache
    # layout <dependency>/<id>/<file> that everest_runtime/Dockerfile reads.
    mkdir -p /ext/licences; \
    if [ -d /ext/cache/cpm ]; then \
      find /ext/cache/cpm -mindepth 3 -maxdepth 3 -type f \( -iname 'LICENSE*' -o -iname 'LICENCE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) \
        | while read -r f; do rel="${f#/ext/cache/cpm/}"; install -D -m 0644 "$f" "/ext/licences/${rel}"; done; \
    fi; \
    for d in /ext/build/_deps/*-src; do \
      [ -d "$d" ] || continue; dep="$(basename "$d" -src)"; \
      find "$d" -mindepth 1 -maxdepth 1 -type f \( -iname 'LICENSE*' -o -iname 'LICENCE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) \
        | while read -r f; do install -D -m 0644 "$f" "/ext/licences/${dep}/src/$(basename "$f")"; done; \
    done; \
    cp /ext/source/LICENSE /ext/LICENSE; \
    git -C /ext/source rev-parse HEAD > /ext/EVEREST_CORE_COMMIT; \
    rm -rf /ext/source /ext/build /ext/cache /ext/wheels /root/.cache; \
    mkdir -p /ext/source /ext/cache; \
    mv /ext/LICENSE /ext/source/LICENSE; \
    mv /ext/EVEREST_CORE_COMMIT /ext/source/EVEREST_CORE_COMMIT; \
    mv /ext/licences /ext/cache/cpm

# The extraction stage of everest_runtime/Dockerfile needs a shell and
# coreutils; the build image is about 3 GB, so the result is copied onto
# Debian slim (about 1 GB less to load per build).
FROM ${DEBIAN_IMAGE}
ARG EVEREST_CORE_TAG=2026.10.0-rc1
LABEL org.opencontainers.image.title="EVerest ${EVEREST_CORE_TAG} built from source (build input for purcell-lab/ha-addons)" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons" \
      org.opencontainers.image.licenses="Apache-2.0"
COPY --from=build /ext/dist/ /ext/dist/
COPY --from=build /ext/source/ /ext/source/
COPY --from=build /ext/cache/ /ext/cache/
