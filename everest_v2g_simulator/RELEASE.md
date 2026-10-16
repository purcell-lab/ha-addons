# Publishing the prebuilt image

`config.yaml` sets
`image: ghcr.io/purcell-lab/{arch}-everest-v2g-simulator`, so Home Assistant pulls `<image>:<version>` for its architecture (about 560 to
585 MB) instead of building locally from the 4.3 GB EVerest build image.
The App build itself copies EVerest from the small pinned runtime image
(`everest_runtime/README.md`), not the 4.3 GB upstream image.
Each step below is a separate operator decision; none happens automatically.

## Steps

1. **Approve publication** of a public container image with the EVerest
   runtime and Josev (Apache-2.0), Debian's OpenJDK 17 (GPLv2 with the
   Classpath Exception, copyright files under `/usr/share/doc/`) and this
   App's packaging.
2. **Start publication** on the reviewed commit (the PR head), one of two ways:

   - **Manual run (preferred).** Actions, *Publish EVerest V2G App image*,
     Run workflow, with `version` (e.g. `0.1.5`) and `target` (the PR head
     commit sha). A Claude session can start the same run through the GitHub
     API. After the image is pushed and attested, the run creates the
     annotated tag `everest_v2g_simulator-v<version>` on the exact commit it
     built. This is the pattern used by `nem_pd7day` and `localvolts_v2`.
   - **Tag push**, for example by publishing a GitHub release with a new tag:

     ```bash
     git tag -a everest_v2g_simulator-v<version> -m "EVerest DC V2G test charger <version>" <commit>
     git push origin everest_v2g_simulator-v<version>
     ```

   `everest-v2g-publish.yml` then, per architecture: checks the tag or the
   requested version matches `config.yaml` (a manual run also refuses a
   version whose tag already exists), refuses to overwrite an existing version, builds, runs the
   same release gate as PR CI (`tests/ci_image_checks.sh`: DC V2G modules
   and no private keys; V2G, fallback, pinned 2.0.1 and offline acceptance;
   fail-closed without NET_ADMIN; listeners; external firewall probe with
   negative control; clean shutdown), pushes only the version tag (no
   `latest`) and adds a build provenance attestation. The run summary records each digest.
3. **Make both packages public** (new GHCR packages start private):
   GitHub, purcell-lab profile, Packages, `amd64-everest-v2g-simulator`,
   Package settings, Change visibility, Public. Repeat for
   `aarch64-everest-v2g-simulator`. Optionally link each package to this
   repository.
4. **Re-run the PR checks.** The `published-image` job confirms anonymous
   pulls for both architectures. It fails until steps 2 and 3 are done, which
   prevents merging a manifest that HA cannot install.
5. **Merge** only after explicit approval. Install, start and connection
   remain separate approvals.

## Rules

- A published version is never replaced. Fixes need a version bump and a
  new tag.
- Only a tag matching `everest_v2g_simulator-v*` or a manual run publishes.
  Pull requests and branch pushes never do. A manual run never moves an
  existing tag, and its tag is made with the workflow token, so it does not
  start a second publication; the job token can write only this repository's
  packages.
- Verify a pull independently: `docker manifest inspect
  ghcr.io/purcell-lab/amd64-everest-v2g-simulator:0.1.0` (no login).
- Attestation check: `gh attestation verify
  oci://ghcr.io/purcell-lab/amd64-everest-v2g-simulator:0.1.0 --owner purcell-lab`.
