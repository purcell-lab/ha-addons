FROM rabbitmq:3.13.7-management@sha256:e582c0bc7766f3342496d8485efb5a1df782b5ce3886ad017e2eaae442311f69
RUN apt-get update && apt-get install -y --no-install-recommends jq && rm -rf /var/lib/apt/lists/* \
    && rabbitmq-plugins disable --offline rabbitmq_management rabbitmq_management_agent rabbitmq_web_dispatch
COPY run.sh /opt/citrine/run.sh
RUN chmod 0755 /opt/citrine/run.sh && mkdir -p /data
ENV RABBITMQ_MNESIA_BASE=/data/mnesia RABBITMQ_NODENAME=rabbit@localhost RABBITMQ_DEFAULT_USER=citrine
ENTRYPOINT ["/opt/citrine/run.sh"]
CMD ["rabbitmq-server"]
