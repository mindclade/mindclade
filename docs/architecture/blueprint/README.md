# Architecture blueprint sources

The ordered files in `manifest.yaml` are the editable authority for MC-ARCH-001
v3.4.2. The manifest uses JSON syntax, which is valid YAML 1.2, so the
renderer has deterministic parsing and the validator can enforce its committed
JSON Schema through the locked `jsonschema` dependency. Edit a section or
appendix source, regenerate the combined document, and commit both changes.

```bash
python3.12 tools/docs/render_architecture_blueprint.py
python3.12 tools/docs/validate_blueprint_sources.py
python3.12 -m unittest discover -s tools/docs/tests -p 'test_*.py'
```

Do not edit `generated/MINDCLADE_MONOREPO_BLUEPRINT_FULL.md`. Do not edit the
generated region in Appendix A6.
`docs/architecture/repository-path-manifest.yaml` is the sole active path
database; `tools/repo/render_repository_tree.py` replaces the region bounded
by the `repository-path-manifest` markers before the full blueprint is
rendered.

## Provenance and v3.4.2 reconciliation

`provenance/MINDCLADE_MONOREPO_BLUEPRINT_v3.4.0_OPTIMIZED.md` and
`provenance/MONOREPO_TREE.md` are byte-preserved inputs. Their SHA-256 digests
are fixed in `manifest.yaml` and checked on every validation run. They are
evidence, not editable or competing authorities.

Version 3.4.2 applies the document's own precedence rules:

- Section 14's seven long ADR filenames replace the short filenames embedded
  in the supplied tree.
- The sole repository-path manifest adds the mandatory Bazel workspace lock
  plus Wave 0 schema, test, golden, blueprint-source, and provenance paths
  omitted by the supplied tree.
- The manifest-first Wave 1 precursor reclassifies 36 existing durability and
  integration paths, adds eight missing durability/release paths, and declares
  five native package authorities for generated bindings. All 386 Wave 1 paths
  remain `target` and absent until implementation, targets, tests, and evidence
  are delivered together.
- The connected-ratification schema is declared as an active Wave 0 requirement.
  Its missing source is reported explicitly; this precursor does not claim the
  schema or connected ratification is implemented.
- The canonical remote and Go module are lowercase
  `github.com/mindclade/mindclade`.
- Owner-selected deployment inputs are development/staging/production,
  `us-central1` primary, `us-east4` recovery, Google Identity Platform for
  initial application-user authentication, and proprietary internal-use
  licensing.
- Repository-evidence statements describe the inspected greenfield and
  operational sources without claiming connected or production qualification.
- Appendix A31 follows the dependency ordering in Section 15; agents,
  distributed execution, and product work cannot enter earlier phases through
  the local guidance.

The corrected A6 render is generated only from the repository-path manifest.
This README records why it differs from the preserved input; it is not a
second list of target paths.
