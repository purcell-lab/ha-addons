# Pinned upstream and licence

This App builds [MicroOcppSimulator](https://github.com/matth-x/MicroOcppSimulator)
at `2cb07cdbe53954a694a29336ab31eac2d2b48673`, including the exact recursively
pinned submodules. It does not use the older purcell-lab fork or a floating
upstream image. Review the submodule tree whenever updating the pin.

The simulator is GPL-3.0; its MicroOCPP core has a separate MIT licence.
The complete adapted simulator source, including dependency licence files,
is included at `/usr/share/microocpp/corresponding-source.tar.gz` in every
image. The Dockerfile and `prepare_source.py` in this repository provide the
build instructions and adaptations. Preserve this source alongside any
distributed binary image. Repository packaging is MIT as stated in the root
README; this does not relicense upstream components.

The reviewed adaptations are applied with exact-context checks:

- Enable and force OCPP 2.0.1 with no silent 1.6 fallback.
- Disable full OCPP traffic logging and reduce normal log verbosity.
- Bind the unauthenticated native API to loopback.
- Remove the public echo-server fallback; default to an empty backend.
- Use a `SIM-` fallback identity and make network keys CSMS-read-only.
- Report the real string OCPP 2.0.1 transaction ID through the HTTP API.
- Default sampled import energy, power, current, voltage and SoC at start/end
  and ten-second transaction updates, rather than the empty upstream defaults.
- Handle SIGTERM with the same cleanup path as SIGINT.
- Replace the prebuilt UI's hard-coded localhost API URL with an
  Ingress-relative URL. No remote assets are added.

The source's power model is charging-only. Negative limits do not mean V2G.
The upstream in-memory energy accumulator is not a durable revenue meter.
Restart persistence of protocol records must not be confused with continuous
physical metering or automatic continuation of a charging scenario.

References:
- [Upstream simulator](https://github.com/matth-x/MicroOcppSimulator)
- [Upstream core](https://github.com/matth-x/MicroOcpp)
- [HA App configuration](https://developers.home-assistant.io/docs/apps/configuration/)
- [HA Ingress requirements](https://developers.home-assistant.io/docs/apps/presentation/)
