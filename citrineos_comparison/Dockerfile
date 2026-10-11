# Test image only. Context MUST be the verified next commit in pins.json.
FROM node:24.16.0@sha256:40ad9f3064e67d6860b4bc3fe1880b2953934fd6320ada990e45fe0efa6badd7 AS build
RUN corepack enable
WORKDIR /usr/local/apps/citrineos
COPY . .
RUN pnpm install --frozen-lockfile
RUN pnpm --filter "@citrineos/ocpp-server..." build
RUN pnpm --filter "@citrineos/ocpp-server" deploy --legacy --prod /deploy

FROM node:24.16.0-slim@sha256:2c87ef9bd3c6a3bd4b472b4bec2ce9d16354b0c574f736c476489d09f560a203
LABEL org.opencontainers.image.revision="19ef2b452f8dc1e5bcd97cd3c1aac072c821f588"
COPY --from=build /deploy /usr/local/apps/citrineos/apps/ocpp-server
USER node
WORKDIR /usr/local/apps/citrineos/apps/ocpp-server
# No upstream migration or server entrypoint is copied or invoked.
ENTRYPOINT ["node"]
CMD ["--version"]
