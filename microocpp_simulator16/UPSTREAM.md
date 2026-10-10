# Pinned upstream and licence

Built from [MicroOcppSimulator](https://github.com/matth-x/MicroOcppSimulator)
at `2cb07cdbe53954a694a29336ab31eac2d2b48673` with recursively pinned submodules.
MicroOCPP core is pinned to `4b89f4649d65c83cc559e4cc7c65f430db482217`.

The simulator is GPL-3.0; its MicroOCPP core has its own MIT licence.
Each image contains complete adapted source and dependency licence files
at `/usr/share/microocpp/corresponding-source.tar.gz`. Preserve it when
distributing binaries. Repository packaging does not relicense upstream code.

Exact-context downstream changes:

- Force OCPP 1.6 at runtime and retain its native integer transaction IDs
  and watt-based smart-charging callback.
- Disable traffic logging, bind the API to loopback, remove the public
  echo endpoint, protect network identity and handle SIGTERM.
- Use a `SIM-16-` fallback identity and independent App state.
- Default ten-second samples of energy, power, current and voltage; include
  final transaction samples.
- Correct UI plug flags and response handling; serve HTML correctly through
  relative Ingress paths; do not fabricate Charging through badge clicks.
- Apply sample-time meter refresh equivalent to the separately staged
  2.0.1 PR #4 and clip simulated variation to the charging ceiling.
- Correct the pinned 1.6 profile evaluator to schedule recalculation at
  `validTo` and consider that boundary expired. Without this, a final
  period with no subsequent boundary could retain its cap after expiry.

No new smart-charging engine is implemented. This uses the existing upstream
OCPP 1.6 engine, with packaging kept independent of the 2.0.1 App.
Shared safety fixes should be reviewed for both App directories when changed;
the build deliberately has no dependency on a sibling App's Docker context.
