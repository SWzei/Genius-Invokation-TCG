# KB versions (D34)

`GITCG_KB` v1.0 is read-only and lives outside this repo (`$GITCG_KB_DIR`). Each later
version is a patch on its parent:

| file | content |
|---|---|
| `version.toml` | `parent`, `layer` (`rules` / `strategy`), `date`, `summary` |
| `changes.patch` | unified diff, paths relative to the KB root (`git apply`) |
| `CHANGELOG.md` | what changed, the evidence (engine checks / train games), the session |

Build: `python -m reps.kb_versions build <version>` (needs `GITCG_KB_DIR`, `GITCG_DATA_RELEASE`);
the result goes to `$GITCG_DATA_DIR/kb_versions/<version>` and must pass the KB's own
`tools/validate_kb.py` with no issue. A knowledge profile selects it with `kb_version = "<version>"`.

Rules: a `rules` version only touches `rules/` and only fixes technical problems (boundary
conditions, cross references, short rule cards); every stated fact is checked with
`python -m bench.kb_engine_check`. A `strategy` version only touches `strategy/` and is
accepted only through the model-vs-model gate (`reports/review/2026-11_kb_d34_prereg.md` §5).
Versions are append-only: never edit a version that has been played.
