#!/usr/bin/env python3
"""Streaming/SQLite conversion pipeline for large historical FM datasets."""
from __future__ import annotations
import csv, json, re, sqlite3, unicodedata, difflib
from pathlib import Path
from datetime import datetime
from typing import Iterable, Iterator

ATTRIBUTE_COLUMNS = {
    "pace","acceleration","agility","balance","jumping","natural_fitness","stamina","strength",
    "finishing","first_touch","heading","passing","technique","dribbling","tackling","marking",
    "anticipation","composure","concentration","decisions","determination","flair","leadership",
    "off_the_ball","positioning","teamwork","vision","work_rate","crossing","long_shots","penalties",
    "free_kicks","corners","throw_ins","handling","reflexes","one_on_ones","aerial_reach",
    "command_of_area","eccentricity","communication","kicking","passing_gk","influence","bravery",
    "aggression","creativity","left_foot","right_foot","natural_fitness","versatility"
}
ALIASES = {
    "dob":"date_of_birth","birth_date":"date_of_birth","birthdate":"date_of_birth","dateofbirth":"date_of_birth",
    "nation":"nationality","nationality_1":"nationality","country":"nationality","club_name":"club",
    "team":"club","current_ability":"ca","currentability":"ca","potential_ability":"pa","potentialability":"pa",
    "uid":"db_unique_id","unique_id":"db_unique_id","uniqueid":"db_unique_id","player_id":"db_unique_id",
    "first name":"first_name","firstname":"first_name","surname":"last_name","second_nationality_1":"second_nationality",
}

def clean_key(k: str) -> str:
    s = str(k).strip().lower()
    s = re.sub(r"[\s\-/]+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "", s)
    return ALIASES.get(s, s)

def clean_text(v) -> str:
    return "" if v is None else str(v).strip()

def norm_name(s: str) -> str:
    s = clean_text(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def norm_row(row: dict) -> dict:
    out = {}
    for k,v in row.items():
        ck = clean_key(k)
        if not ck: continue
        if isinstance(v,(int,float)):
            out[ck] = v
        else:
            s = clean_text(v)
            if ck in ATTRIBUTE_COLUMNS or ck in {"ca","pa","reputation","wage"}:
                try:
                    f = float(s.replace(",", "")) if s else None
                    out[ck] = int(f) if f is not None and f.is_integer() else f
                except Exception:
                    out[ck] = s
            elif ck in {"date_of_birth","contract_expiry"}:
                out[ck] = parse_date(s)
            else:
                out[ck] = s
    if not out.get("name") and (out.get("first_name") or out.get("last_name")):
        out["name"] = f"{out.get('first_name','')} {out.get('last_name','')}".strip()
    return out

def parse_date(s: str) -> str:
    s = clean_text(s)
    if not s: return ""
    for fmt in ("%Y-%m-%d","%d/%m/%Y","%m/%d/%Y","%d-%m-%Y","%Y/%m/%d"):
        try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError: pass
    return s

def iter_records(path: Path) -> Iterator[dict]:
    ext = path.suffix.lower()
    if ext == ".csv":
        with path.open("r",encoding="utf-8-sig",newline="") as f:
            yield from csv.DictReader(f)
    elif ext == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data,list): yield from data
        elif isinstance(data,dict):
            for key in ("players","people","data","records","items"):
                if isinstance(data.get(key), list):
                    yield from data[key]; return
            yield data
    else:
        raise ValueError(f"Unsupported structured source: {path}")

def init_db(db: Path):
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("""CREATE TABLE IF NOT EXISTS people_raw (
        row_id INTEGER PRIMARY KEY,
        name TEXT, name_norm TEXT, dob TEXT, nationality TEXT, club TEXT,
        raw_json TEXT NOT NULL
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_people_name_norm ON people_raw(name_norm)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_people_dob ON people_raw(dob)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_people_nat ON people_raw(nationality)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_people_club ON people_raw(club)")
    con.commit(); return con

def ingest_structured(path: Path, db: Path, batch_size: int=5000) -> int:
    con=init_db(db); cur=con.cursor(); total=0; batch=[]
    for raw in iter_records(path):
        r=norm_row(raw); name=clean_text(r.get("name"));
        if not name: continue
        batch.append((name,norm_name(name),clean_text(r.get("date_of_birth")),clean_text(r.get("nationality")),clean_text(r.get("club")),json.dumps(r,ensure_ascii=False)))
        if len(batch)>=batch_size:
            cur.executemany("INSERT INTO people_raw(name,name_norm,dob,nationality,club,raw_json) VALUES (?,?,?,?,?,?)",batch)
            total+=len(batch); batch=[]
    if batch:
        cur.executemany("INSERT INTO people_raw(name,name_norm,dob,nationality,club,raw_json) VALUES (?,?,?,?,?,?)",batch); total+=len(batch)
    con.commit(); con.close(); return total

def automatic_mapping(headers: Iterable[str]) -> dict:
    mapping={}
    known=set(ATTRIBUTE_COLUMNS)|{"name","first_name","last_name","date_of_birth","nationality","second_nationality","club","position","role","ca","pa","reputation","contract_expiry","wage","db_unique_id"}
    for h in headers:
        ck=clean_key(h)
        mapping[ck]=ck if ck in known else "(ignore)"
    return mapping

def candidate_matches(source_db: Path, target_db: Path, out_json: Path, threshold: float=.78, max_per_source: int=3) -> int:
    s=sqlite3.connect(source_db); t=sqlite3.connect(target_db)
    # target must have same schema; use exact blocking first, fuzzy only inside small buckets
    trows=t.execute("SELECT row_id,name,name_norm,dob,nationality,club,raw_json FROM people_raw").fetchall()
    idx={}
    for row in trows:
        _, name, nn, dob, nat, club, _ = row
        key=(nn,dob)
        idx.setdefault(key,[]).append(row)
        idx.setdefault((nn,""),[]).append(row)
    results=[]
    for srow in s.execute("SELECT row_id,name,name_norm,dob,nationality,club FROM people_raw"):
        sid,name,nn,dob,nat,club=srow
        candidates=idx.get((nn,dob),[]) or idx.get((nn,""),[])
        if not candidates:
            # surname bucket; avoids O(N*M)
            surname=nn.split()[-1] if nn else ""
            candidates=[r for r in trows if (r[2].split()[-1] if r[2] else "") == surname][:100]
        scored=[]
        for r in candidates:
            _,tn,tnn,tdob,tnat,tclub,_=r
            name_score=difflib.SequenceMatcher(None,nn,tnn).ratio()
            score=.78*name_score
            if dob and tdob and dob==tdob: score+=.15
            if nat and tnat and norm_name(nat)==norm_name(tnat): score+=.04
            if club and tclub: score+=.03*difflib.SequenceMatcher(None,norm_name(club),norm_name(tclub)).ratio()
            scored.append((score,r))
        scored.sort(key=lambda x:x[0],reverse=True)
        for score,r in scored[:max_per_source]:
            if score>=threshold:
                results.append({"source_row_id":sid,"source_name":name,"target_row_id":r[0],"target_name":r[1],"score":round(score,4)})
    out_json.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    s.close();t.close(); return len(results)
