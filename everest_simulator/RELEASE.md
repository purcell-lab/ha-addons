# Publishing the prebuilt image

`config.yaml` sets `image: ghcr.io/purcell-lab/{arch}-everest-simulator`, so
Home Assistant on aarch64 pulls `<image>:<version>` (about 310 to
340 MB) instead of building locally from the 4.3 GB EVerest build image.
The App build itself copies EVerest from the small pinned runtime image
(`everest_runtime/README.md`), not the 4.3 GB upstream image.
Only aarch64 is published. amd64 hosts add the store entry
`https://github.com/purcell-lab/ha-addons#local-build` (generated from `main` by
`local-build-mirror.yml`, without `image:`), so Supervisor builds the same
Dockerfile on the host.
Each step below is a separate operator decision; none happens automatically.

## Steps

1. **Approve publication** of the Apache-2.0 EVerest runtime and this App's
   packaging as a public container image.
2. **Push the release tag** on the reviewed commit (the PR head):

   ```bash
   git tag -a everest_simulator-v0.1.0 -m "EVerest OCPP test charger 0.1.0" <commit>
   git push origin everest_simulator-v0.1.0
   ```

   `everest-publish.yml` then, on an aarch64 runner: checks the tag matches
   `config.yaml`, refuses to overwrite an existing version, builds, runs the
   same release gate as PR CI (`tests/ci_image_checks.sh`: no V2G modules;
   2.1, fallback, pinned 2.0.1 and offline acceptance; listeners; clean
   shutdown), pushes only the version tag (no `latest`) and adds a build
   provenance attestation. The run summary records each digest.
3. **Make the package public** (new GHCR packages start private):
   GitHub, purcell-lab profile, Packages, `aarch64-everest-simulator`, Package
   settings, Change visibility, Public. Optionally link it to this
   repository.
4. **Re-run the PR checks.** The `published-image` job confirms the anonymous
   aarch64 pull. It fails until steps 2 and 3 are done, which
   prevents merging a manifest that HA cannot install.
5. **Merge** only after explicit approval. Install, start and connection
   remain separate approvals.

## Rules

- A published version is never replaced. Fixes need a version bump and a
  new tag.
- Only tags matching `everest_simulator-v*` publish. Pull requests and
  branch pushes never do; the job token can write only this repository's
  packages.
- Verify a pull independently: `docker manifest inspect
  ghcr.io/purcell-lab/aarch64-everest-simulator:0.1.0` (no login).
- Attestation check: `gh attestation verify
  oci://ghcr.io/purcell-lab/aarch64-everest-simulator:0.1.0 --owner purcell-lab`.
