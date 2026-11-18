# Imatra cloud ISO 15118-2 server (Apache-2.0, Chargetronic,
# https://github.com/Chargetronic/imatra.iso15118_server) as one Home Assistant
# App. The upstream source is fetched at the pinned v0.1.0 commit during the
# build; nothing from it is kept in this repository. Every base image is pinned
# by its multi-arch index digest.
#
# One container instead of upstream's Compose project: Postgres 16, Valkey 8,
# Mosquitto, the engine, relay, projector, operator API and the Caddy gateway.
# Only the gateway (8080, /v1 and /health) and the device listener (8883, mTLS)
# listen beyond 127.0.0.1, and neither is published unless a host port is set.
#
# The Imatra test harness (PolyForm Internal Use) is not part of this App.

ARG IMATRA_COMMIT=c7f030c9d6b03426e0c183139b5a57e0b09e91b7
ARG LIBCBV2G_TAG=v0.3.2

# --- upstream source, pinned ---
FROM golang:1.27-trixie@sha256:f18c3d73a184fb0582828510722e723b63a93f7188d11dd223d9be6f6880e65d AS src
ARG IMATRA_COMMIT
WORKDIR /src
RUN git init -q . \
    && git remote add origin https://github.com/Chargetronic/imatra.iso15118_server.git \
    && git fetch -q --depth 1 origin "${IMATRA_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${IMATRA_COMMIT}"

# --- engine, relay, projector (Go + libcbv2g), as upstream engine/Dockerfile ---
FROM golang:1.27-trixie@sha256:f18c3d73a184fb0582828510722e723b63a93f7188d11dd223d9be6f6880e65d AS engine
ARG LIBCBV2G_TAG
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends cmake ninja-build \
    && rm -rf /var/lib/apt/lists/*
RUN git clone -q --depth 1 --branch ${LIBCBV2G_TAG} https://github.com/EVerest/libcbv2g.git /src/libcbv2g \
    && cmake -S /src/libcbv2g -B /src/libcbv2g/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
       -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_SHARED_LIBS=OFF -DCMAKE_INSTALL_PREFIX=/opt/cbv2g \
    && cmake --build /src/libcbv2g/build && cmake --install /src/libcbv2g/build
COPY --from=src /src/engine /src/server
WORKDIR /src/server
ENV CGO_ENABLED=1 CGO_CFLAGS="-I/opt/cbv2g/include" CGO_LDFLAGS="-L/opt/cbv2g/lib"
# Upstream's unit tests need Valkey and Postgres; CI runs the App end to end instead.
RUN go mod download \
    && go build -trimpath -ldflags="-s -w" -o /out/engine ./cmd/engine \
    && go build -trimpath -ldflags="-s -w" -o /out/relay ./cmd/relay \
    && go build -trimpath -ldflags="-s -w" -o /out/projector ./cmd/projector

# --- gateway: Caddy with the rate-limit module, as upstream gateway/Dockerfile ---
FROM caddy:2.11-builder@sha256:aef223d1f943bc12a29a9e0a0a73983aa19a36672daede7507da4201a6b1016a AS gateway
RUN xcaddy build --with github.com/mholt/caddy-ratelimit --replace golang.org/x/net=golang.org/x/net@v0.62.0

FROM valkey/valkey:8-trixie@sha256:8f836008e0986c36adf50da714c7060cf689dbb335f61fe077939d90fa650809 AS valkey

# --- runtime ---
FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG BUILD_ARCH
ARG IMATRA_COMMIT
LABEL io.hass.name="Imatra ISO 15118-2 Lab" \
      io.hass.description="Imatra cloud ISO 15118-2 server with its own internal broker" \
      io.hass.type="addon" \
      io.hass.version="0.1.0" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Mosquitto runs as uid 1883 (upstream's scripts chown its files to 1883).
RUN groupadd -r -g 1883 mosquitto && useradd -r -u 1883 -g 1883 -d /var/lib/mosquitto -s /usr/sbin/nologin mosquitto \
    && groupadd -r imatra && useradd -r -g imatra -d /nonexistent -s /usr/sbin/nologin imatra \
    && apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends ca-certificates curl gnupg openssl jq postgresql-common \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y -qq --no-install-recommends postgresql-16 mosquitto mosquitto-clients \
    && apt-get purge -y -qq gnupg && apt-get autoremove -y -qq \
    && rm -rf /var/lib/apt/lists/*
COPY --from=valkey /usr/local/bin/valkey-server /usr/local/bin/valkey-cli /usr/local/bin/
COPY --from=gateway /usr/bin/caddy /usr/local/bin/caddy
COPY --from=engine /out/engine /out/relay /out/projector /usr/local/bin/
# Operator API (Python), unmodified.
COPY --from=src /src/api/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY --from=src /src/api/migrations /srv/migrations
COPY --from=src /src/api/schemas /srv/schemas
COPY --from=src /src/api/app /srv/app
# Broker, PKI and preflight scripts, unmodified; the paths they expect point
# into /data (run.sh). Two changes to upstream configuration, both checked here:
#  - the services' listener 1883 binds to 127.0.0.1 only;
#  - the gateway proxies to the API on 127.0.0.1 (no "api" host in one container).
COPY --from=src /src/mqtt/mosquitto.conf /etc/imatra/mosquitto.conf
COPY --from=src /src/mqtt/mqtt-init.sh /src/mqtt/mqtt-run.sh /src/pki/pki-init.sh /src/pki/preflight.sh /usr/local/bin/
COPY --from=src /src/gateway/Caddyfile /etc/imatra/Caddyfile
COPY --from=src /src/LICENSE /src/NOTICE /src/PATENTS.md /src/THIRD_PARTY.md /usr/share/doc/imatra/
RUN sed -i 's/^listener 1883$/listener 1883 127.0.0.1/' /etc/imatra/mosquitto.conf \
    && grep -qx 'listener 1883 127.0.0.1' /etc/imatra/mosquitto.conf \
    && grep -qx 'listener 8883' /etc/imatra/mosquitto.conf \
    && sed -i 's/reverse_proxy api:8000/reverse_proxy 127.0.0.1:8000/' /etc/imatra/Caddyfile \
    && ! grep -q 'api:8000' /etc/imatra/Caddyfile \
    && echo "${IMATRA_COMMIT}" > /usr/share/doc/imatra/COMMIT \
    && chmod 0755 /usr/local/bin/mqtt-init.sh /usr/local/bin/mqtt-run.sh /usr/local/bin/pki-init.sh /usr/local/bin/preflight.sh \
    && test -x /usr/local/bin/engine && test -x /usr/local/bin/relay && test -x /usr/local/bin/projector \
    && valkey-server --version && caddy version && mosquitto -h | head -1 \
    && /usr/lib/postgresql/16/bin/postgres --version
COPY rootfs/ /
RUN chmod 0755 /opt/imatra-ha/*.sh
WORKDIR /srv
ENTRYPOINT ["/opt/imatra-ha/run.sh"]
