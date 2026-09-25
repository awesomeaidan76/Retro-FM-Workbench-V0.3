#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from legacy_extractors import extract_source


def main():
    p=argparse.ArgumentParser(description="Retro FM legacy database extractor")
    p.add_argument("source", help="Legacy database file or folder")
    p.add_argument("-o","--output",default="retro_extract",help="Output folder")
    p.add_argument("--parser",help="External full parser (.exe/.bat/.py) implementing --input/--output contract")
    p.add_argument("--max-candidates",type=int,default=50000)
    args=p.parse_args()
    source=Path(args.source); out=Path(args.output)
    if not source.exists():
        raise SystemExit(f"Source does not exist: {source}")
    result=extract_source(source,out,Path(args.parser) if args.parser else None,args.max_candidates)
    print(json.dumps({
        "source_version":result.source_version,
        "source_path":result.source_path,
        "recovered_records":result.recovered_records,
        "people_json":result.output_json,
        "people_csv":result.output_csv,
        "inventory":result.inventory_json,
        "warnings":result.warnings,
    },indent=2,ensure_ascii=False))

if __name__ == "__main__": main()
