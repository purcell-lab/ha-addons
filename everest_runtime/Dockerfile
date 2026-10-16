# Shared EVerest 2025.10.0 runtime for the EVerest Apps. This is a build
# input, not a Home Assistant App (there is no config.yaml).
#
# The upstream demo image is about 4.3 GB compressed per architecture,
# almost all of it build tree, sources and toolchain. This image keeps only
# the installed runtime that the Apps copy, stripped exactly as the Apps
# did before (about 50 MB), so App builds no longer pull the 4.3 GB image.
#
# Contents, all under the paths the Apps use:
#   /opt/everest/bin/manager
#   /opt/everest/lib/            shared libraries the binaries load, lib/everest
#   /opt/everest/share/everest/  (empty www, data for the selected modules)
#   /opt/everest/etc/everest/certs/    upstream demo certificates (AC App only)
#   /opt/everest/libexec/everest/3rd_party/josev/   (V2G App only)
#   /opt/everest/libexec/everest/modules/<MODULES>  union of both Apps
#   /usr/share/doc/everest/      EVerest and third-party licence files
ARG EVEREST_IMAGE=ghcr.io/everest/everest-demo/manager:2025.10.0-single-phase@sha256:9165d0937323ae61ee2e496f68f3c4a465ed9099740e489df1f0161265492756
ARG DEBIAN_IMAGE=debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

FROM ${EVEREST_IMAGE} AS everest
# Collect licence/notice files of EVerest and its CPM-fetched dependencies.
RUN set -eu; mkdir -p /licences; cp /ext/source/LICENSE /licences/EVerest-LICENSE; \
    cd /ext/cache/cpm; \
    find . -mindepth 3 -maxdepth 3 -type f \( -iname 'LICENSE*' -o -iname 'LICENCE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) \
      | while read -r f; do dep="${f#./}"; dep="${dep%%/*}"; install -D -m 0644 "$f" "/licences/third_party/${dep}/$(basename "$f")"; done

FROM ${DEBIAN_IMAGE} AS slim
# Union of everest_simulator and everest_v2g_simulator MODULES.
ARG MODULES="API Auth DCSupplySimulator DummyTokenProviderManual EnergyManager EnergyNode ErrorHistory Evse15118D20 EvManager EvseManager EvseSecurity IMDSimulator OCPP201 PersistentStore PyEvJosev SlacSimulator System YetiSimulator"
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends binutils && rm -rf /var/lib/apt/lists/*
COPY --from=everest /ext/dist/bin/manager /stage/opt/everest/bin/manager
COPY --from=everest /ext/dist/lib/ /tmp/dist-lib/
COPY --from=everest /ext/dist/share/everest/ /stage/opt/everest/share/everest/
COPY --from=everest /ext/dist/etc/everest/certs/ /stage/opt/everest/etc/everest/certs/
COPY --from=everest /ext/dist/libexec/everest/3rd_party/josev/ /stage/opt/everest/libexec/everest/3rd_party/josev/
COPY --from=everest /ext/dist/libexec/everest/modules/ /tmp/dist-modules/
COPY --from=everest /licences/ /stage/usr/share/doc/everest/
RUN set -eu; \
    mkdir -p /stage/opt/everest/lib /stage/opt/everest/libexec/everest/modules; \
    cp -a /tmp/dist-lib/everest /stage/opt/everest/lib/; \
    for module in ${MODULES}; do cp -a "/tmp/dist-modules/${module}" /stage/opt/everest/libexec/everest/modules/; done; \
    # Keep only the EVerest shared libraries that the manager, the selected
    # modules and everestpy load (DT_NEEDED closure). This drops, for
    # example, libeverest_api_types (20 MB, linked by no shipped binary)
    # and the unversioned .so symlinks used only for linking.
    elfs() { find "$@" -type f | while read -r f; do \
      [ "$(head -c 4 "$f" | od -An -c | tr -d ' ')" = '177ELF' ] && echo "$f"; done; :; }; \
    needed() { for f in "$@"; do readelf -d "$f" | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p'; done | sort -u; }; \
    want=$(needed $(elfs /stage/opt/everest/bin /stage/opt/everest/libexec /stage/opt/everest/lib/everest)); seen=""; \
    while [ "$want" != "$seen" ]; do seen=$want; \
      want=$( (echo "$want"; for n in $want; do [ -e "/tmp/dist-lib/$n" ] && needed "/tmp/dist-lib/$n"; done; :) | sort -u); \
    done; \
    for n in $want; do [ -e "/tmp/dist-lib/$n" ] || continue; \
      cp -a "/tmp/dist-lib/$n" /stage/opt/everest/lib/; \
      t=$(readlink "/tmp/dist-lib/$n" || true); [ -z "$t" ] || cp -a "/tmp/dist-lib/$t" /stage/opt/everest/lib/; \
    done; \
    # Unused data: the admin panel web UI (the Apps replace the admin-panel
    # controller with a stub; the manager still requires the directory to
    # exist, so it is kept empty) and data for modules not in MODULES.
    find /stage/opt/everest/share/everest/www -mindepth 1 -delete; \
    for d in /stage/opt/everest/share/everest/modules/*; do \
      case " ${MODULES} " in *" $(basename "$d") "*) ;; *) rm -rf "$d" ;; esac; \
    done; \
    find /stage/opt/everest -type f | while read -r f; do \
      if [ "$(head -c 4 "$f" | od -An -c | tr -d ' ')" = '177ELF' ]; then strip --strip-unneeded "$f"; fi; \
    done; \
    rm -rf /tmp/dist-lib /tmp/dist-modules

FROM scratch
ARG RUNTIME_VERSION
LABEL org.opencontainers.image.title="EVerest runtime for purcell-lab/ha-addons" \
      org.opencontainers.image.version="${RUNTIME_VERSION}" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="ghcr.io/everest/everest-demo/manager:2025.10.0-single-phase@sha256:9165d0937323ae61ee2e496f68f3c4a465ed9099740e489df1f0161265492756"
COPY --from=slim /stage/ /
