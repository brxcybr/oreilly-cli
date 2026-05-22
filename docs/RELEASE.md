# Release Process

This project currently ships as a source repository and GitHub release. It is
not packaged for PyPI yet, so releases are tags plus checked-in documentation.

## Version Source

- `VERSION` is the single source of truth for the release version.
- `python oreilly_cli.py --version` reads from `VERSION`.
- `CHANGELOG.md` must contain a matching `## [x.y.z] - YYYY-MM-DD` entry before tagging.

Use semantic versioning:

- Patch: bug fixes and documentation-only release work.
- Minor: new user-visible CLI/MCP behavior that remains backward compatible.
- Major: breaking CLI, config, output, or API changes.

## Pre-Release Checklist

1. Confirm `git status --short` is clean except for the intended release changes.
2. Update `VERSION`.
3. Move entries from `CHANGELOG.md` `Unreleased` into a dated release section.
4. Run the local gate:

   ```bash
   .venv/bin/python scripts/release_check.py --allow-dirty
   ```

5. If fresh O'Reilly cookies are available, run the live gate:

   ```bash
   .venv/bin/python scripts/release_check.py \
     --allow-dirty \
     --live \
     --cookies-file ~/.oreilly-cli/cookies.json \
     --live-book-id 9781098120672
   ```

6. Review `README.md`, `docs/CLI_AND_MCP.md`, and this file for changed commands or output fields.
7. Commit the release prep.

## Tag And Publish

From a clean `main` checkout:

```bash
version=$(cat VERSION)
.venv/bin/python scripts/release_check.py
git tag -a "v${version}" -m "Release v${version}"
git push origin main
git push origin "v${version}"
```

Create the GitHub release from the tag and use the matching `CHANGELOG.md`
section as the release notes. Do not attach generated book exports, cookies,
playlist captures, or other restricted content.

## Live Validation Scope

The optional live gate validates the parts most likely to drift:

- cookie/session status;
- format discovery;
- source resolution for a known book ID;
- metadata fetch for the same book;
- chunks export with `--skip-images`;
- post-export `repair-links` idempotency.

The live gate writes to a temporary directory and deletes it unless
`--keep-smoke-output` is provided.
