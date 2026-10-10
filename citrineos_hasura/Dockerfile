FROM hasura/graphql-engine:v2.40.3@sha256:679fb764590e848e59ab6b82b3e906cc46f87d776f869f49132ca728660df244
USER root
COPY --from=postgis/postgis:16-3.5@sha256:94146ac37bc61e2322f88016056c5920729cb8c64c8542ed590af8fc2abdac07 /usr/local/bin/gosu /usr/local/bin/gosu
ADD --checksum=sha256:020468de7539ce70ef1bceaf7cde2e8c4f2ca6c3afb84642aabc5c97d9fc2a0d https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-linux-amd64 /usr/local/bin/jq
COPY run.sh /opt/citrine/run.sh
RUN chmod 0755 /opt/citrine/run.sh /usr/local/bin/jq && mkdir -p /data
ENV HASURA_GRAPHQL_ENABLE_CONSOLE=false HASURA_GRAPHQL_DEV_MODE=false \
    HASURA_GRAPHQL_ENABLE_TELEMETRY=false HASURA_GRAPHQL_ENABLED_LOG_TYPES=startup \
    HASURA_GRAPHQL_PG_CONNECTIONS=10
ENTRYPOINT ["/opt/citrine/run.sh"]
