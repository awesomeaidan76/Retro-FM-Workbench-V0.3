#!/usr/bin/env python3
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--input',required=True); p.add_argument('--output',required=True); a=p.parse_args()
out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
rows=[
 {'name':'Demo Historical Player','date_of_birth':'1988-05-12','nationality':'England','club':'Demo FC','position':'ST','ca':140,'pa':155,'finishing':15,'pace':14},
 {'name':'Another Historical Player','date_of_birth':'1987-09-02','nationality':'France','club':'Demo FC','position':'MC','ca':130,'pa':150,'passing':16,'technique':15},
]
(out/'people.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding='utf8')
