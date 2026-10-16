# Releasing microocpp_simulator16

Home Assistant installs `ghcr.io/purcell-lab/{arch}-microocpp-simulator16:<version>`
(`image:` in `config.yaml`). Each step is a separate operator decision.

1. **Approve publication** of a public container image with
   MicroOcppSimulator (GPL-3.0-only; the corresponding source is in the
   image at `/usr/share/microocpp/`) and this App's packaging.
2. **Start publication** on the reviewed commit (the PR head), either:
   - Actions → *Publish MicroOCPP App image* → Run workflow, with `app`
     `microocpp_simulator16`, `version` (from `config.yaml`) and `target` (the PR head
     sha). The run publishes both architectures, then tags
     `microocpp_simulator16-v<version>` on the exact commit it built; or
   - push the annotated tag `microocpp_simulator16-v<version>` yourself.

   Per architecture (native runners): version check, no overwrite, build,
   the same image checks as PR CI, push `<version>` only (never
   `latest`), build provenance attestation.
3. **Make the package public** the first time (new GHCR packages start
   private), so Home Assistant and the PR `published-image` gate can pull it
   anonymously.
4. **Merge** once `published-image` is green, then update the App in
   Home Assistant.
