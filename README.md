# Retro FM Database Workbench v0.3

A Windows-friendly workbench for converting large historical Football Manager / Championship Manager datasets into Football Manager 2024 or Football Manager 2026 workflows **without manually entering hundreds of thousands of players**.

## What is new in v0.3

- Legacy source discovery for FM/CM database folders.
- Version detection heuristics for older FM installations (including FM12-style `1200`/`1220` layouts) and CM06-style `club.dat` layouts.
- Database inventory with SHA-256 hashes, file roles, and sizes.
- Forensic binary string/name-carving fallback for legacy `.dat` files.
- Stable external-parser contract for a **real semantic extractor**: the parser receives `--input` and `--output` and writes `people.json` and/or `people.csv`.
- SQLite-backed ingestion so very large datasets do not have to live entirely in RAM.
- Automatic field normalization and mapping.
- Indexed player matching that uses blocking/exact keys before fuzzy comparisons; this avoids the old O(N×M) all-to-all comparison problem.
- Validation and exception reporting.
- FM24/FM26 target selection and FMME-oriented export from the earlier workbench.
- CLI suitable for automation/AI-agent orchestration.

## Important format limitation

The stock desktop FM12 database is a proprietary binary dataset. A SteamDB snapshot confirms that an FM12 installation contains files including `data/db/1200/people_db.dat`, `lang_db.dat`, and the player-history files; the newer games keep the same broad family of binary database components. The workbench therefore does **not** claim that scanning arbitrary bytes can reconstruct every field correctly.

The fallback extractor is intentionally forensic: it recovers plausible text fragments and their byte offsets, but it labels them `name_candidate_only` and does not invent attributes, DOBs, clubs, CA/PA, or IDs.

For complete structured extraction, plug in a version-specific parser. The app can then consume the parser's output automatically and continue through mapping, matching, validation, and export. This is the safe way to get to hundreds of thousands of actual player rows without manual entry.

## External parser contract

A parser plugin can be an `.exe`, `.bat`, or `.py` file. The workbench calls:

```text
parser --input <legacy-source> --output <output-folder>
```

For Python plugins it automatically invokes the current Python interpreter.

The plugin should write:

```text
people.json   # list of player/person records OR {"players": [...]} / {"people": [...]}
```

and/or:

```text
people.csv
```

Use normalized or obvious headers such as:

`name, first_name, last_name, date_of_birth, nationality, second_nationality, club, position, ca, pa, pace, acceleration, ...`

The workbench handles normalization and downstream processing.

## Example

### 1. Inspect/extract a legacy source

```powershell
python retro_fm_extractor.py "C:\Program Files (x86)\Steam\steamapps\common\Football Manager 2012\data\db\1200" -o "C:\RetroFM\FM12_extract"
```

This produces `source_inventory.json`, `people.json`, and `people.csv`.

### 2. Use a full parser when available

```powershell
python retro_fm_extractor.py "C:\...\data\db\1200" -o "C:\RetroFM\FM12_extract" --parser "C:\RetroFM\parsers\fm12_parser.exe"
```

### 3. Ingest large structured output into SQLite

```powershell
python -c "from pathlib import Path; from large_pipeline import ingest_structured; print(ingest_structured(Path('C:/RetroFM/FM12_extract/people.json'), Path('C:/RetroFM/FM12.db')))"
```

## Why this architecture matters

The pipeline is:

```text
FM/CM legacy files
       ↓
 source detector + inventory
       ↓
 version-specific extractor
       ↓
 normalized records
       ↓
 SQLite staging database
       ↓
 automatic mapping
       ↓
 indexed matching / deduplication
       ↓
 validation + exception queue
       ↓
 FM24 / FM26 FMME CSV/JSON
       ↓
 FMME version-specific XML
       ↓
 FM Pre-Game Editor
```

The only component that fundamentally needs a reverse-engineered, version-specific implementation is the **full legacy binary parser**. Everything around it is automated and reusable.

## Evidence used while designing the source adapters

- FM12 Steam depot manifests show `people_db.dat`, `lang_db.dat`, `pl_hist_dt.dat`, `pl_hist_id.dat`, and related database files in `data/db/1200`.
- The FM2012 official editor depot exposes version-specific database XML schemas such as `person.xml`, `player.xml`, `club.xml`, `nation.xml`, and `comp.xml`, which is useful reference material when mapping extracted records.
- FMME supports CSV/JSON/XLSX imports and version-specific YAML/XML templates, making it suitable as the final mass-export layer.
- Community tools demonstrate that structured player exports from older FM versions are possible, but their documentation does not establish a complete official binary-to-CSV contract for FM12; the workbench therefore keeps the source parser modular rather than guessing at the proprietary format.
