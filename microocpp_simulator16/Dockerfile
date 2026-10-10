FROM alpine:3.22 AS build
RUN apk add --no-cache build-base cmake git python3
WORKDIR /src
RUN git clone https://github.com/matth-x/MicroOcppSimulator.git . \
    && git checkout 2cb07cdbe53954a694a29336ab31eac2d2b48673 \
    && git submodule update --init --recursive
COPY prepare_source.py /prepare_source.py
COPY txprofile_status.h txprofile_status.js txprofile_status.css /
RUN python3 /prepare_source.py /src \
    && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    && cmake --build build --parallel 2 --target mo_simulator \
    && mkdir /source \
    && tar --exclude=.git --exclude=build -czf /source/corresponding-source.tar.gz .

FROM alpine:3.22
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.type="app" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.source="https://github.com/purcell-lab/ha-addons" \
      org.opencontainers.image.licenses="GPL-3.0-only"
RUN apk add --no-cache libstdc++ libgcc nginx python3 \
    && mkdir -p /opt/microocpp/public /run/nginx /data
COPY --from=build /src/build/mo_simulator /opt/microocpp/mo_simulator
COPY --from=build /src/public/bundle.html.gz /opt/microocpp/public/bundle.html.gz
COPY --from=build /src/public/bundle.html /opt/microocpp/public/bundle.html
COPY --from=build /source/ /usr/share/microocpp/
COPY app.py nginx.conf UPSTREAM.md /opt/microocpp/
WORKDIR /data
ENTRYPOINT ["python3", "/opt/microocpp/app.py"]
