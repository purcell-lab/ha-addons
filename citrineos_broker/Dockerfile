# Official static jq 1.8.1 for the target architecture (BuildKit sets
# TARGETARCH); checksums from the jq-1.8.1 release sha256sum.txt.
FROM scratch AS jq-amd64
ADD --checksum=sha256:020468de7539ce70ef1bceaf7cde2e8c4f2ca6c3afb84642aabc5c97d9fc2a0d https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-linux-amd64 /jq
FROM scratch AS jq-arm64
ADD --checksum=sha256:6bc62f25981328edd3cfcfe6fe51b073f2d7e7710d7ef7fcdac28d4e384fc3d4 https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-linux-arm64 /jq
FROM jq-${TARGETARCH} AS jq

FROM rabbitmq:3.13.7-management@sha256:e582c0bc7766f3342496d8485efb5a1df782b5ce3886ad017e2eaae442311f69
COPY --from=jq /jq /usr/local/bin/jq
RUN rabbitmq-plugins disable --offline rabbitmq_management rabbitmq_management_agent rabbitmq_web_dispatch
COPY run.sh /opt/citrine/run.sh
RUN chmod 0755 /opt/citrine/run.sh /usr/local/bin/jq && mkdir -p /data
ENV RABBITMQ_MNESIA_BASE=/data/mnesia RABBITMQ_NODENAME=rabbit@localhost RABBITMQ_DEFAULT_USER=citrine
ENTRYPOINT ["/opt/citrine/run.sh"]
CMD ["rabbitmq-server"]
