# Releasing open_dynamic_export

Home Assistant installs `ghcr.io/purcell-lab/{arch}-open-dynamic-export:<version>`
(`image:` in `config.yaml`). Each step is a separate operator decision.

1. **Approve publication** of a public container image with Open Dynamic
   Export (MIT; licence, upstream commit and patch under
   `/usr/share/doc/open-dynamic-export/`), its npm dependencies and this
   App's packaging.
2. **Start publication** on the reviewed commit (the PR head), either:
   - Actions → *Publish Open Dynamic Export App image* → Run workflow, with
     `version` (from `config.yaml`) and `target` (the PR head sha). The run
     publishes both architectures, then tags `open_dynamic_export-v<version>`
     on the exact commit it built; or
   - push the annotated tag `open_dynamic_export-v<version>` yourself.

   Per architecture (native runners): version check, no overwrite, build,
   the same image checks as PR CI, push `<version>` only (never `latest`),
   build provenance attestation.
3. **Make the package public** the first time (new GHCR packages start
   private), so Home Assistant and the PR `published-image` gate can pull it
   anonymously.
4. **Merge** once `published-image` is green, then install or update the App.

To move to a newer ODE release, change `ARG ODE_COMMIT`, check that
each patch still applies (the build runs `git apply --check`; drop
`ramp-tms.patch` once upstream includes #138), update
`UPSTREAM.md`, bump `version` and release as above.
