FROM postgis/postgis:16-3.5@sha256:94146ac37bc61e2322f88016056c5920729cb8c64c8542ed590af8fc2abdac07
# PostgreSQL/PostGIS are already pinned in the image. Its old PGDG apt source
# is retired; only Debian's signed repository is needed for the jq helper.
RUN rm -f /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends jq && rm -rf /var/lib/apt/lists/*
COPY run.sh /opt/citrine/run.sh
RUN chmod 0755 /opt/citrine/run.sh && mkdir -p /data
ENV PGDATA=/data/pgdata POSTGRES_DB=citrine POSTGRES_USER=citrine
ENTRYPOINT ["/opt/citrine/run.sh"]
CMD ["postgres", "-c", "max_connections=80", "-c", "shared_buffers=128MB"]
