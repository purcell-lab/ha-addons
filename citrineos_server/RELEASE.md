# Release

Images are built and published only by
`.github/workflows/citrineos-server-publish.yml` (GitHub Actions, amd64 and
aarch64, CitrineOS built from source by `Dockerfile`). It never overwrites an
image or moves a tag. Each step is a separate approval:

1. Bump `version` in `config.yaml`, the `io.hass.version` label in
   `Dockerfile` and `CHANGELOG.md`; PR CI must pass (`citrineos.yml`: tests,
   the patched upstream source, the from-source image build,
   `tests/ci_image_checks.sh` and the private stack on both architectures).
2. Run **Publish CitrineOS Isolated Lab App image** with the version and the
   reviewed commit SHA (or push the tag `citrineos_server-v<version>`). A
   manual run publishes, then tags the commit it built.
3. Check the new packages can be pulled anonymously; make them public if not.
4. Re-run the PR checks until `published-image` is green, then merge.

Verify: `docker manifest inspect ghcr.io/purcell-lab/aarch64-citrineos-server:<version>`
and `gh attestation verify oci://ghcr.io/purcell-lab/aarch64-citrineos-server:<version> --owner purcell-lab`.

To move to a new CitrineOS release, change the commit in `Dockerfile` and
`compatibility-lock.json`, refresh `patches/` and their test fixtures,
regenerate `rootfs/metadata-operator.json` and
`tests/fixtures/citrineos-routes.<release>.json`, and release this App and the
Operator UI App together.
