FROM hasura/graphql-engine:v2.40.3@sha256:679fb764590e848e59ab6b82b3e906cc46f87d776f869f49132ca728660df244
USER root
RUN apt-get update && apt-get install -y --no-install-recommends jq util-linux && rm -rf /var/lib/apt/lists/*
COPY run.sh /opt/citrine/run.sh
RUN chmod 0755 /opt/citrine/run.sh && mkdir -p /data
ENV HASURA_GRAPHQL_ENABLE_CONSOLE=false HASURA_GRAPHQL_DEV_MODE=false \
    HASURA_GRAPHQL_ENABLE_TELEMETRY=false HASURA_GRAPHQL_ENABLED_LOG_TYPES=startup \
    HASURA_GRAPHQL_PG_CONNECTIONS=10
ENTRYPOINT ["/opt/citrine/run.sh"]
