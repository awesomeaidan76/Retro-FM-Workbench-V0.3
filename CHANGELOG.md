# Changelog

## 0.3.0

- Added legacy extractor subsystem.
- Added automatic FM/CM source-folder detection and file inventory.
- Added SHA-256 source manifest generation for reproducibility.
- Added forensic `.dat` text/name carving fallback with explicit `name_candidate_only` status.
- Added external full-parser plugin contract (`--input`, `--output`, `people.json`/`people.csv`).
- Added SQLite staging for large source and target datasets.
- Replaced all-to-all player matching with indexed/blocking matching to avoid catastrophic scaling on hundreds of thousands of records.
- Added integrated Extract → Map → Match → Validate → Export workflow.
- Retained FM24/FM26 target selection.
- Added CLI extractor (`retro_fm_extractor.py`) for automation and AI-agent orchestration.
