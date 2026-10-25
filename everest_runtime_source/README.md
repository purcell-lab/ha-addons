# EVerest runtime image built from source (build input)

`ghcr.io/purcell-lab/everest-runtime:<VERSION>` for EVerest versions that
have no prebuilt everest-demo image. `VERSION` is `2026.10.0-rc1-1`:
everest-core tag `2026.10.0-rc1` (commit `f45ba0d`, a release candidate),
first build of this runtime. It is the same kind of image as the
2025.10.0 runtime (`everest_runtime/`): multi-arch (amd64, arm64),
`FROM scratch`, never run, not a Home Assistant App. Only
`everest_v2g_simulator` uses it; the AC `everest_simulator` keeps
`2025.10.0-1`.

## How it is built

1. **Compile** (`Dockerfile` here). everest-core is cloned at the tag (the
   commit is checked) and built in EVerest's own CI image,
   `ghcr.io/everest/everest-ci/build-kit-base:v1.6.0`, pinned by digest
   (Debian 12, GCC 12, Boost 1.74: the ABI of the Apps' Debian 12 base).
   CMake Release with `EVEREST_INCLUDE_MODULES` set to `MODULES`, so only
   those modules and the libraries they need are configured; tests,
   applications, run scripts and the Rust and JavaScript bindings are off.
   `ninja install/strip` installs to `/ext/dist`. The result keeps only the
   installed tree, the EVerest licence and the licence files of the
   CPM-fetched dependencies, in the everest-demo image layout.
2. **Extract** with the unchanged `everest_runtime/Dockerfile`
   (`EVEREST_IMAGE` = the compile result, `MODULES` = `MODULES`): the same
   module selection, shared-library closure, data pruning, `strip` and
   `FROM scratch` output as the 2025.10.0 runtime.
   `.github/scripts/everest_runtime_source.sh` runs this step and checks the
   contents (manager, every module, everestpy, Josev, libocpp's component
   configs and DER migration under `share/everest/modules/OCPP201`, the
   grid_support interface, licences, no private keys).

`MODULES` lists the V2G App's modules with OCPPmulti (OCPP 1.6, 2.0.1 and
2.1 with DER control) instead of OCPP201, plus OCPP201 itself, so that the
extraction keeps libocpp's share directory (`modules/OCPP201`), which
OCPPmulti reads.

## Workflows

| Workflow | When | What |
|---|---|---|
| `everest-runtime-source-build.yml` | Called by the two below | Per architecture, natively (`ubuntu-24.04`, `ubuntu-24.04-arm`): compile (cached in the Actions cache per architecture, so an unchanged `Dockerfile` and `MODULES` do not recompile), extract, check, upload `everest-runtime-source-<arch>` (kept 7 days). Never publishes. |
| `everest-v2g.yml` (`runtime-source` job) | Pull requests, while the App pins a runtime that is not yet published by digest, or when this directory changes | Builds the runtime, then each architecture's App image job loads it and runs the image checks |
| `everest-runtime-source-publish.yml` | Tag `everest_runtime_source-v<VERSION>`, or a manual run with `version` and `target` | Tag or version must match `VERSION`; refuses to overwrite or move a tag; builds, pushes `<VERSION>-amd64`, `<VERSION>-aarch64`, then the index `<VERSION>` with a provenance attestation |

A cold compile takes much longer than the extract-only 2025.10.0 runtime
build (the job allows 5 hours); a cache hit takes minutes.

There is no identical-file check for this runtime: it is the first build of
2026.10, so there is no earlier image to be identical to. Its evidence is
the V2G App's image checks and acceptance scenarios run on it.
`.github/scripts/everest_identical_files.sh` skips Apps pinned to another
EVerest version than `everest_runtime/VERSION` and says so.

## Publishing (each step is a separate approval)

1. Approve publication of a public image with the Apache-2.0 EVerest
   runtime, Josev and the third-party licence files.
2. Run **Publish EVerest runtime image (built from source)** with the
   version and the reviewed commit sha. The run publishes, then creates the
   annotated tag `everest_runtime_source-v<VERSION>` on the commit it built.
   Pushing that tag on the reviewed commit yourself does the same:

   ```bash
   git tag -a everest_runtime_source-v$(cat everest_runtime_source/VERSION) \
     -m "EVerest runtime $(cat everest_runtime_source/VERSION) (from source)" <commit>
   git push origin everest_runtime_source-v$(cat everest_runtime_source/VERSION)
   ```

3. The image goes to the existing `everest-runtime` GHCR package (public).
4. Pin `ARG EVEREST_RUNTIME=ghcr.io/purcell-lab/everest-runtime:<VERSION>@sha256:<index digest>`
   in `everest_v2g_simulator/Dockerfile` (the run summary prints it) and
   re-run the checks.

To move to a new EVerest tag (for example 2026.10.0 final), change
`EVEREST_CORE_TAG` and `EVEREST_CORE_COMMIT` in the `Dockerfile`, bump
`VERSION` (`2026.10.0-1`), and re-check the App's upstream pins
(`everest_v2g_simulator/UPSTREAM.md`). Published versions are never
overwritten.
