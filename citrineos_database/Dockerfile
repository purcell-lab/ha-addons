FROM postgis/postgis:16-3.5@sha256:94146ac37bc61e2322f88016056c5920729cb8c64c8542ed590af8fc2abdac07
# Static official jq avoids retired apt repositories in the pinned base image.
ADD --checksum=sha256:020468de7539ce70ef1bceaf7cde2e8c4f2ca6c3afb84642aabc5c97d9fc2a0d https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-linux-amd64 /usr/local/bin/jq
COPY run.sh /opt/citrine/run.sh
RUN chmod 0755 /opt/citrine/run.sh /usr/local/bin/jq && mkdir -p /data
ENV PGDATA=/data/pgdata POSTGRES_DB=citrine POSTGRES_USER=citrine
ENTRYPOINT ["/opt/citrine/run.sh"]
CMD ["postgres", "-c", "max_connections=80", "-c", "shared_buffers=128MB"]
