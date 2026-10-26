# Release

Images are built and published only by `.github/workflows/operator-ui-publish.yml`
(GitHub Actions, aarch64 only). It never overwrites an image or moves a
tag. Each step is a separate approval:

1. Bump `version` in `config.yaml` and `CHANGELOG.md`; PR CI must pass
   (`operator-ui.yml`: tests, image build and `tests/ci_image_checks.sh` on
   amd64 and aarch64).
2. Run **Publish CitrineOS Operator UI App image** with the version and the
   reviewed commit SHA (or push the tag `citrineos_operator_ui-v<version>`).
   A manual run publishes, then tags the commit it built.
3. Check the new packages can be pulled anonymously; make them public if not.
4. Re-run the PR checks until `published-image` is green, then merge.

Verify: `docker manifest inspect ghcr.io/purcell-lab/aarch64-citrineos-operator-ui:<version>`
and `gh attestation verify oci://ghcr.io/purcell-lab/aarch64-citrineos-operator-ui:<version> --owner purcell-lab`.

To move to a new CitrineOS release, change `CORE_COMMIT` (and the server's
pinned release together), refresh `operator-ui.patch`, regenerate the
server's `metadata-operator.json`, and release both Apps.
