# EVerest runtime image (build input)

`ghcr.io/purcell-lab/everest-runtime:<VERSION>` is a multi-arch (amd64,
arm64) image that holds only the stripped EVerest 2025.10.0 runtime the
EVerest Apps copy: `manager`, shared libraries, `share/everest`, the
upstream demo certificates (AC App only), Josev (V2G App only), the union
of both Apps' modules, and the licence files. It is `FROM scratch` and is
never run. It is not a Home Assistant App (there is no `config.yaml`).

## Why

The upstream `everest-demo/manager:2025.10.0-single-phase` image is about
4.3 GB compressed per architecture. Its compile layers (about 2.7 GB and
0.7 GB) are build tree, sources and toolchain. The Apps use about 30 MB
(AC) and 45 MB (V2G) of it, compressed. Before this image, every App CI
job and every release pulled the full 4.3 GB. Now only a runtime build
does, once per runtime version. The images HA installs are unchanged.

## What proves it changes nothing

`.github/scripts/everest_identical_files.sh` builds each App from the
runtime image and compares it with the published release image of the
same version (AC 0.1.0, V2G 0.1.2), built from the upstream image
directly. Type, mode, owner and SHA-256 content (or link target) must match
for every path under `/opt/everest`, `/usr/share/doc/everest`,
`/opt/ha-everest` and `/usr/local/lib/python3.11`. Timestamps are not
compared. Differences elsewhere (Debian packages resolved by apt at build
time) are listed for information. It runs in `everest-runtime.yml` on pull
requests and again as the release gate in `everest-runtime-publish.yml`.

This proves file identity with the released images. It does not test
behaviour; the App workflows still run their full image checks.

## How App builds choose the runtime

`.github/scripts/everest_runtime.sh` uses the Dockerfile's
`ARG EVEREST_RUNTIME` when it is pinned by digest and pullable, and the
pull request does not change `everest_runtime/`. Otherwise CI builds the
runtime locally from this directory first. Release workflows accept only
the pinned, public runtime. The App `published-image` merge gate fails
until the runtime is pinned and public.

## Publishing (each step is a separate approval)

1. Approve publication of a public image with the Apache-2.0 EVerest
   runtime, Josev and the third-party licence files.
2. Push `everest_runtime-v<VERSION>` on the reviewed commit:

   ```bash
   git tag -a everest_runtime-v$(cat everest_runtime/VERSION) -m "EVerest runtime $(cat everest_runtime/VERSION)" <commit>
   git push origin everest_runtime-v$(cat everest_runtime/VERSION)
   ```

   Per architecture: tag check, no overwrite, build, identical-file gate,
   push `<VERSION>-<arch>`. Then one multi-arch index `<VERSION>` with a
   provenance attestation. The run summary prints the line to pin.
3. Make the `everest-runtime` package public (new GHCR packages start
   private), so anonymous CI and release pulls work.
4. Pin `ARG EVEREST_RUNTIME=ghcr.io/purcell-lab/everest-runtime:<VERSION>@sha256:<index digest>`
   in both App Dockerfiles and re-run the checks.

To move to a new EVerest release, change the upstream image and digest
here, bump `VERSION` (for example `2025.12.1-1`), and expect the
identical-file check to report differences against the old App releases.
Review those differences, then release new App versions.
