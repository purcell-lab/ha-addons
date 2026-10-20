# Open Dynamic Export (MIT, https://github.com/longzheng/open-dynamic-export)
# v0.20.0, built from the pinned upstream commit with this App's patches
# (ingress, ramp-tms, influxdb-quiet, stdout-log-level, default-control-merge) and run
# by this App's launcher (rootfs/opt/ode-ha).
# Built and published in GitHub Actions (ode-publish.yml); Home Assistant
# pulls the prebuilt image rather than compiling on the host.
ARG NODE_IMAGE=node:24-alpine3.22@sha256:191c9f0080fcbbc6547a85dc0ff7988072214a355aabdc1d2ec55a7dae5eea8a
ARG ODE_COMMIT=bc807abbc4c58be3294257ee76f0348dc87c4945

FROM ${NODE_IMAGE} AS build
ARG ODE_COMMIT
# Compilers only for native dependencies without a musl prebuild.
RUN apk add --no-cache git python3 make g++ linux-headers
WORKDIR /src
RUN git init -q . \
    && git remote add origin https://github.com/longzheng/open-dynamic-export.git \
    && git fetch -q --depth 1 origin "${ODE_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${ODE_COMMIT}"
# Applied in order; each must apply cleanly to the pinned commit.
COPY ingress.patch ramp-tms.patch influxdb-quiet.patch stdout-log-level.patch \
     default-control-merge.patch poll-rate-after-error.patch /tmp/
RUN for p in ingress ramp-tms influxdb-quiet stdout-log-level default-control-merge \
             poll-rate-after-error; do \
        git apply --check "/tmp/$p.patch" && git apply "/tmp/$p.patch" || exit 1; \
    done \
    && corepack enable \
    && pnpm install --frozen-lockfile \
    && pnpm run build \
    && pnpm prune --prod \
    && mkdir -p /out/app /out/usr/share/doc/open-dynamic-export \
    && cp -a dist node_modules package.json /out/app/ \
    && cp LICENSE /out/usr/share/doc/open-dynamic-export/LICENSE \
    && cp /tmp/ingress.patch /tmp/ramp-tms.patch /tmp/influxdb-quiet.patch \
          /tmp/stdout-log-level.patch /tmp/default-control-merge.patch \
          /tmp/poll-rate-after-error.patch \
          /out/usr/share/doc/open-dynamic-export/ \
    && echo "${ODE_COMMIT}" > /out/usr/share/doc/open-dynamic-export/COMMIT

FROM ${NODE_IMAGE}
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.type="app" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons" \
      org.opencontainers.image.licenses="MIT"
COPY --from=build /out/ /
COPY rootfs/ /
COPY UPSTREAM.md /usr/share/doc/open-dynamic-export/UPSTREAM.md
# Upstream writes rotating debug logs (up to 1.1 GB) under ./logs. Keep them
# off persistent storage and out of backups; stdout still reaches the HA log.
RUN mkdir -p /data /tmp/ode-logs \
    && ln -s /tmp/ode-logs /app/logs \
    && node --check /opt/ode-ha/run.mjs
WORKDIR /app
EXPOSE 3000
ENTRYPOINT ["node", "/opt/ode-ha/run.mjs"]
