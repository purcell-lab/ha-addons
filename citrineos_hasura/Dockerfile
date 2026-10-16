# Official static jq 1.8.1 for the target architecture (BuildKit sets
# TARGETARCH); checksums from the jq-1.8.1 release sha256sum.txt.
FROM scratch AS jq-amd64
ADD --checksum=sha256:020468de7539ce70ef1bceaf7cde2e8c4f2ca6c3afb84642aabc5c97d9fc2a0d https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-linux-amd64 /jq
FROM scratch AS jq-arm64
ADD --checksum=sha256:6bc62f25981328edd3cfcfe6fe51b073f2d7e7710d7ef7fcdac28d4e384fc3d4 https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-linux-arm64 /jq
FROM jq-${TARGETARCH} AS jq

FROM hasura/graphql-engine:v2.40.3@sha256:679fb764590e848e59ab6b82b3e906cc46f87d776f869f49132ca728660df244
USER root
COPY --from=imresamu/postgis:16-3.5-bullseye@sha256:3ffaa98ccdb5d1c0f81456f02f75e7cbbadc2453f6e671917fb1e8705aa86bd3 /usr/local/bin/gosu /usr/local/bin/gosu
COPY --from=jq /jq /usr/local/bin/jq
COPY run.sh /opt/citrine/run.sh
RUN chmod 0755 /opt/citrine/run.sh /usr/local/bin/jq && mkdir -p /data
ENV HASURA_GRAPHQL_ENABLE_CONSOLE=false HASURA_GRAPHQL_DEV_MODE=false \
    HASURA_GRAPHQL_ENABLE_TELEMETRY=false HASURA_GRAPHQL_ENABLED_LOG_TYPES=startup \
    HASURA_GRAPHQL_PG_CONNECTIONS=10
ENTRYPOINT ["/opt/citrine/run.sh"]
