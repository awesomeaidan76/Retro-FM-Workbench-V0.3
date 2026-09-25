#!/usr/bin/env python3
"""Legacy Football Manager / Championship Manager source extraction layer.

This module deliberately separates *format discovery* from *authoritative parsing*.
The commercial legacy .dat formats are proprietary and version-sensitive. For formats
without a verified parser, the workbench can still inspect the source, carve text
strings for forensic review, and invoke an external parser that emits the normalized
JSON/CSV contract used by the conversion pipeline.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator, Optional

SUPPORTED_EXTS = {".dat", ".dbc", ".edt", ".ddt", ".lnc", ".xml", ".csv", ".json", ".xlsx", ".xls"}

FM_SIGNATURES = {
    "FM12": {"people_db.dat", "lang_db.dat", "pl_hist_dt.dat", "pl_hist_id.dat"},
    "FM11": {"people_db.dat", "lang_db.dat", "pl_hist_dt.dat"},
    "FM10": {"people_db.dat", "lang_db.dat"},
    "FM09": {"people_db.dat", "lang_db.dat"},
    "FM08": {"people_db.dat", "lang_db.dat"},
    "FM07": {"people_db.dat"},
    "FM06": {"people_db.dat"},
    "CM06": {"club.dat"},
}

PLAYERISH_WORDS = {
    "fc", "afc", "united", "city", "town", "rovers", "wanderers", "athletic",
    "real", "sporting", "olympique", "internacional", "deportivo", "county",
    "england", "scotland", "wales", "ireland", "france", "germany", "italy", "spain",
    "brazil", "argentina", "portugal", "netherlands", "belgium", "denmark", "sweden",
}

@dataclass
class FileInventory:
    path: str
    size: int
    extension: str
    sha256: str
    likely_role: str

@dataclass
class ExtractionResult:
    source_version: str
    source_path: str
    output_json: str
    output_csv: str
    inventory_json: str
    recovered_records: int
    warnings: list[str]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def detect_version(root: Path) -> tuple[str, float, list[str]]:
    """Detect likely legacy version from folder/file naming.

    Returns (version, confidence, evidence). It never claims an exact parser match;
    this is a source routing decision.
    """
    evidence: list[str] = []
    names = {p.name.lower() for p in root.rglob("*") if p.is_file()}
    path_text = str(root).lower()
    for token, version in [("1200", "FM12"), ("1220", "FM12"), ("1100", "FM11"),
                           ("1000", "FM10"), ("900", "FM09"), ("800", "FM08"),
                           ("700", "FM07")]:
        if token in path_text:
            evidence.append(f"path contains database version token {token}")
            return version, 0.95, evidence
    best = ("UNKNOWN", 0.0, [])
    for version, sig in FM_SIGNATURES.items():
        hits = sorted(sig.intersection(names))
        if not hits:
            continue
        confidence = min(0.55 + 0.12 * len(hits), 0.96)
        ev = [f"found {x}" for x in hits]
        if confidence > best[1]:
            best = (version, confidence, ev)
    # CM06 frequently exposes Club.dat in its editable database layout; we route it
    # as CM06 but still require an external/full parser for complete semantics.
    if "club.dat" in names and best[1] < 0.6:
        best = ("CM06", 0.65, ["found club.dat"])
    return best


def infer_role(name: str) -> str:
    n = name.lower()
    if n == "people_db.dat": return "people"
    if n == "basic_people_db.dat": return "basic_people"
    if n == "lang_db.dat" or n == "lang_update_db.dat": return "language"
    if "pl_hist" in n: return "player_history"
    if "non_pl_hist" in n: return "non_player_history"
    if "club" in n: return "clubs"
    if "comp" in n: return "competitions"
    if "nation" in n: return "nations"
    if n.endswith(".lnc"): return "licensing"
    if n.endswith(".dbc"): return "editor_data"
    if n.endswith(".edt") or n.endswith(".ddt"): return "rules_or_script"
    return "unknown"


def inventory(root: Path) -> tuple[str, float, list[FileInventory]]:
    version, confidence, _ = detect_version(root)
    files: list[FileInventory] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            size = p.stat().st_size
            ext = p.suffix.lower()
            if ext not in SUPPORTED_EXTS and p.name.lower() not in {
                "people_db.dat", "lang_db.dat", "pl_hist_dt.dat", "pl_hist_id.dat",
                "pl_hist_index.dat", "non_pl_hist_dt.dat", "non_pl_hist_id.dat",
                "non_pl_hist_index.dat", "client_db.dat", "server_db.dat", "club.dat",
            }:
                continue
            files.append(FileInventory(str(p), size, ext, sha256_file(p), infer_role(p.name)))
        except OSError:
            pass
    return version, confidence, files


def _utf8_strings(data: bytes, min_len: int) -> Iterator[tuple[int, str]]:
    start = None
    buf = bytearray()
    for i, b in enumerate(data):
        printable = (32 <= b <= 126) or b in (9,)
        if printable:
            if start is None:
                start = i
                buf = bytearray()
            buf.append(b)
        else:
            if start is not None and len(buf) >= min_len:
                try:
                    s = buf.decode("utf-8", "ignore").strip()
                    if s:
                        yield start, s
                except Exception:
                    pass
            start = None
            buf = bytearray()
    if start is not None and len(buf) >= min_len:
        try:
            s = buf.decode("utf-8", "ignore").strip()
            if s:
                yield start, s
        except Exception:
            pass


def _utf16le_strings(data: bytes, min_len: int) -> Iterator[tuple[int, str]]:
    # Heuristic scan for UTF-16LE printable runs.
    i = 0
    n = len(data)
    while i + 2 * min_len <= n:
        if data[i] == 0 and data[i + 1] == 0:
            i += 2
            continue
        start = i
        chars = []
        while i + 1 < n:
            lo, hi = data[i], data[i + 1]
            if hi == 0 and (32 <= lo <= 126 or lo in (9,)):
                chars.append(lo)
                i += 2
            else:
                break
        if len(chars) >= min_len:
            try:
                yield start, bytes(chars).decode("ascii", "ignore").strip()
            except Exception:
                pass
        i = max(i + 1, start + 2)


def carve_strings(path: Path, min_len: int = 4, max_records: int = 250_000) -> Iterator[dict]:
    """Yield text fragments with file offsets. This is forensic recovery, not a semantic parser."""
    # Stream in chunks but retain overlap so strings crossing boundaries aren't lost.
    chunk = 4 * 1024 * 1024
    overlap = 4096
    carry = b""
    base = 0
    with path.open("rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            block = carry + data
            base_offset = base - len(carry)
            for off, text in _utf8_strings(block, min_len):
                yield {
                    "file": str(path), "offset": base_offset + off, "encoding": "utf-8", "text": text
                }
                if max_records <= 1:
                    return
            for off, text in _utf16le_strings(block, min_len):
                yield {
                    "file": str(path), "offset": base_offset + off, "encoding": "utf-16le", "text": text
                }
            if len(block) > overlap:
                carry = block[-overlap:]
            else:
                carry = block
            base += len(data)
            # max_records is an upper bound on the iterator consumer responsibility.


def _looks_like_name(text: str) -> bool:
    s = text.strip()
    if not (2 <= len(s) <= 80):
        return False
    if any(ch.isdigit() for ch in s):
        return False
    if not re.search(r"[A-Za-zÀ-ÿ]", s):
        return False
    words = re.findall(r"[A-Za-zÀ-ÿ'’-]+", s)
    if not words:
        return False
    lower = {w.lower() for w in words}
    if len(lower) == 1 and next(iter(lower)) in PLAYERISH_WORDS:
        return False
    return len(words) <= 7


def forensic_player_candidates(path: Path, max_candidates: int = 50_000) -> list[dict]:
    """Extract plausible person-name fragments as candidates for human/AI review.

    This intentionally does not synthesize attributes, DOBs, clubs or IDs from random bytes.
    """
    candidates = []
    seen = set()
    for rec in carve_strings(path, min_len=3):
        text = rec["text"]
        if not _looks_like_name(text):
            continue
        key = re.sub(r"\s+", " ", text.casefold())
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "name": text,
            "forensic_source_file": rec["file"],
            "forensic_offset": rec["offset"],
            "forensic_encoding": rec["encoding"],
            "forensic_confidence": 0.35,
            "extraction_status": "name_candidate_only",
        })
        if len(candidates) >= max_candidates:
            break
    return candidates


def write_records(records: Iterable[dict], json_path: Path, csv_path: Path) -> int:
    # Materialize only the JSON side if the caller passes a bounded candidate set.
    rows = list(records)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    headers: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k); headers.append(k)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader(); w.writerows(rows)
    return len(rows)


def invoke_external_parser(parser: Path, source: Path, out_dir: Path, timeout: int = 1800) -> dict:
    """Invoke an external full parser under a small stable contract.

    Contract: parser receives --input <source> --output <directory>. It should write
    people.json and/or people.csv using normalized field names. Additional files are allowed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(parser), "--input", str(source), "--output", str(out_dir)]
    if parser.suffix.lower() == ".py":
        import sys
        cmd = [sys.executable] + cmd
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"External parser failed with code {proc.returncode}.\nSTDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-4000:]}"
        )
    result = {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "people_json": str(out_dir / "people.json") if (out_dir / "people.json").exists() else "",
        "people_csv": str(out_dir / "people.csv") if (out_dir / "people.csv").exists() else "",
    }
    if not result["people_json"] and not result["people_csv"]:
        raise RuntimeError("External parser completed but produced neither people.json nor people.csv.")
    return result


def extract_source(source: Path, out_dir: Path, parser: Optional[Path] = None, max_candidates: int = 50_000) -> ExtractionResult:
    source = source.resolve(); out_dir = out_dir.resolve(); out_dir.mkdir(parents=True, exist_ok=True)
    version, confidence, files = inventory(source) if source.is_dir() else ("UNKNOWN", 0.0, [])
    if not source.is_dir():
        version = "SINGLE_FILE"
        files = [FileInventory(str(source), source.stat().st_size, source.suffix.lower(), sha256_file(source), infer_role(source.name))]
    inv_path = out_dir / "source_inventory.json"
    inv_path.write_text(json.dumps({
        "detected_version": version, "confidence": confidence,
        "files": [asdict(x) for x in files]
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    warnings: list[str] = []
    people_json = out_dir / "people.json"
    people_csv = out_dir / "people.csv"
    recovered = 0

    if parser:
        res = invoke_external_parser(parser, source, out_dir)
        warnings.append("Structured extraction came from external parser plugin.")
        src_json = Path(res["people_json"]) if res["people_json"] else None
        src_csv = Path(res["people_csv"]) if res["people_csv"] else None
        if src_json and src_json.exists() and src_json != people_json:
            shutil.copy2(src_json, people_json)
        if src_csv and src_csv.exists() and src_csv != people_csv:
            shutil.copy2(src_csv, people_csv)
        if people_json.exists():
            try:
                data = json.loads(people_json.read_text(encoding="utf-8"))
                recovered = len(data) if isinstance(data, list) else len(data.get("players", data.get("people", [])))
            except Exception:
                recovered = 0
    else:
        # Heuristic layer: locate likely people_db.dat / club.dat and carve names.
        people_candidates = []
        preferred = [Path(x.path) for x in files if x.likely_role in {"people", "basic_people", "clubs"}]
        if not preferred and source.is_file():
            preferred = [source]
        for fp in preferred:
            if not fp.exists():
                continue
            try:
                cand = forensic_player_candidates(fp, max_candidates=max_candidates - len(people_candidates))
                people_candidates.extend(cand)
                if len(people_candidates) >= max_candidates:
                    break
            except Exception as exc:
                warnings.append(f"Forensic scan failed for {fp.name}: {exc}")
        recovered = write_records(people_candidates, people_json, people_csv)
        warnings.append(
            "No full legacy binary parser was supplied. Output is a forensic name-candidate extract, not a complete semantic database. "
            "Use an external parser plugin to obtain attributes, IDs, DOBs, clubs and staff reliably."
        )

    return ExtractionResult(version, str(source), str(people_json), str(people_csv), str(inv_path), recovered, warnings)
