#!/usr/bin/env python3
"""Retro FM Database Workbench v0.3.

Designed around a large-data pipeline: legacy extraction -> normalized structured rows ->
SQLite staging -> automatic mapping/matching/validation -> FM24/FM26 FMME-oriented export.
"""
from __future__ import annotations
import csv, json, os, re, sqlite3, threading, traceback
from pathlib import Path
from tkinter import Tk, StringVar, END, BOTH, LEFT, RIGHT, X, Y, W, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from legacy_extractors import extract_source
from large_pipeline import ingest_structured, automatic_mapping, norm_row, norm_name, candidate_matches

APP_TITLE="Retro FM Database Workbench"; APP_VERSION="0.3.0"
TARGETS=("FM24","FM26")
ATTRIBUTE_COLUMNS={"pace","acceleration","agility","balance","jumping","natural_fitness","stamina","strength","finishing","first_touch","heading","passing","technique","dribbling","tackling","marking","anticipation","composure","concentration","decisions","determination","flair","leadership","off_the_ball","positioning","teamwork","vision","work_rate","crossing","long_shots","penalties","free_kicks","corners","throw_ins","handling","reflexes","one_on_ones","aerial_reach","command_of_area","eccentricity","communication","kicking","influence","bravery","aggression","creativity","left_foot","right_foot","versatility"}

def read_structured(path:Path):
    ext=path.suffix.lower()
    if ext=='.csv':
        with path.open('r',encoding='utf-8-sig',newline='') as f: yield from csv.DictReader(f)
        return
    if ext=='.json':
        data=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data,list): yield from data; return
        if isinstance(data,dict):
            for k in ('players','people','data','records','items'):
                if isinstance(data.get(k),list): yield from data[k]; return
            yield data; return
    raise RuntimeError(f'Unsupported structured file: {path}')

def write_mapped_csv(src:Path,dst:Path,mapping:dict):
    rows=read_structured(src); first=None; headers=[]
    with dst.open('w',encoding='utf-8-sig',newline='') as f:
        writer=None
        for raw in rows:
            r=norm_row(raw); out={}
            for k,v in r.items():
                target=mapping.get(k,k)
                if target and target!='(ignore)': out[target]=v
            if writer is None:
                headers=list(out.keys()); writer=csv.DictWriter(f,fieldnames=headers,extrasaction='ignore'); writer.writeheader()
            writer.writerow(out)
    return dst

def validate_structured(path:Path):
    issues=[]; seen={}; count=0
    for raw in read_structured(path):
        count+=1; r=norm_row(raw); name=str(r.get('name','')).strip()
        if not name: issues.append(('ERROR',count,'Missing player name'))
        dob=str(r.get('date_of_birth','')).strip()
        if dob and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',dob): issues.append(('ERROR',count,f'Unrecognized DOB: {dob}'))
        for a in ATTRIBUTE_COLUMNS|{'ca','pa','reputation'}:
            if a in r and r[a] not in ('',None):
                try: n=float(r[a])
                except: issues.append(('ERROR',count,f'{a} is not numeric: {r[a]}')); continue
                if n<0 or n>200: issues.append(('WARN',count,f'{a} outside expected 0-200: {n}'))
        key=(norm_name(name),dob)
        if key!=("",""): seen.setdefault(key,[]).append(count)
    for key, ids in seen.items():
        if len(ids)>1: issues.append(('WARN',ids[0],f'Possible duplicate: {key[0]} ({len(ids)} records)'))
    return count,issues

class App(ttk.Frame):
    def __init__(self,master):
        super().__init__(master); self.pack(fill=BOTH,expand=True); self.master=master
        self.source_file=''; self.target_file=''; self.extract_dir=''; self.mapping={}; self.issues=[]; self.target='FM26'; self._build()
    def _build(self):
        top=ttk.Frame(self,padding=8); top.pack(fill=X)
        ttk.Label(top,text=APP_TITLE,font=('TkDefaultFont',18,'bold')).pack(side=LEFT)
        ttk.Label(top,text=f'v{APP_VERSION}',foreground='#666').pack(side=LEFT,padx=8)
        ttk.Button(top,text='Open Project',command=self.open_project).pack(side=RIGHT,padx=3); ttk.Button(top,text='Save Project',command=self.save_project).pack(side=RIGHT,padx=3)
        self.nb=ttk.Notebook(self); self.nb.pack(fill=BOTH,expand=True,padx=8,pady=4)
        self.tabs={k:ttk.Frame(self.nb,padding=10) for k in ('extract','map','match','validate','export')}
        for k,t in [('extract','1. Extract Legacy'),('map','2. Mapping'),('match','3. Matching'),('validate','4. Validate'),('export','5. Export')]: self.nb.add(self.tabs[k],text=t)
        self._extract_tab(); self._map_tab(); self._match_tab(); self._validate_tab(); self._export_tab()
        self.status=StringVar(value='Ready.'); ttk.Label(self,textvariable=self.status,relief='sunken',anchor='w').pack(fill=X,padx=8,pady=(0,8))
    def set_status(self,msg): self.status.set(msg); self.update_idletasks()
    def _extract_tab(self):
        t=self.tabs['extract']
        f=ttk.Frame(t); f.pack(fill=X)
        ttk.Label(f,text='Legacy database / folder:').grid(row=0,column=0,sticky=W,padx=3,pady=4); self.src_var=StringVar(); ttk.Entry(f,textvariable=self.src_var,width=85).grid(row=0,column=1,sticky='ew'); ttk.Button(f,text='Browse',command=self.pick_source).grid(row=0,column=2,padx=4)
        ttk.Label(f,text='Output folder:').grid(row=1,column=0,sticky=W,padx=3,pady=4); self.out_var=StringVar(value=str(Path.cwd()/'retro_extract')); ttk.Entry(f,textvariable=self.out_var,width=85).grid(row=1,column=1,sticky='ew'); ttk.Button(f,text='Browse',command=self.pick_output).grid(row=1,column=2,padx=4)
        ttk.Label(f,text='Full parser plugin (optional):').grid(row=2,column=0,sticky=W,padx=3,pady=4); self.parser_var=StringVar(); ttk.Entry(f,textvariable=self.parser_var,width=85).grid(row=2,column=1,sticky='ew'); ttk.Button(f,text='Browse',command=self.pick_parser).grid(row=2,column=2,padx=4)
        f.columnconfigure(1,weight=1)
        btn=ttk.Frame(t); btn.pack(fill=X,pady=8); ttk.Button(btn,text='Run Legacy Extractor',command=self.run_extract).pack(side=LEFT); ttk.Button(btn,text='Load Extracted people.json',command=self.load_extracted).pack(side=LEFT,padx=6)
        self.extract_log=ScrolledText(t,height=25,wrap='word'); self.extract_log.pack(fill=BOTH,expand=True)
        self.extract_log.insert('1.0',"The extractor auto-detects legacy FM/CM folder layouts, inventories files, and can run a supplied full binary parser.\nWithout a verified parser, it performs a forensic text/name recovery and labels those rows as candidate-only.\n")
    def pick_source(self):
        p=filedialog.askdirectory(title='Select legacy database folder')
        if p: self.src_var.set(p)
    def pick_output(self):
        p=filedialog.askdirectory(title='Select output folder')
        if p: self.out_var.set(p)
    def pick_parser(self):
        p=filedialog.askopenfilename(title='Select parser plugin',filetypes=[('Parser','*.exe *.bat *.py'),('All files','*.*')])
        if p: self.parser_var.set(p)
    def run_extract(self):
        src=Path(self.src_var.get().strip()); out=Path(self.out_var.get().strip()); parser=Path(self.parser_var.get().strip()) if self.parser_var.get().strip() else None
        if not src.exists(): messagebox.showerror(APP_TITLE,'Select a valid legacy source.'); return
        self.set_status('Extracting…'); self.extract_log.delete('1.0',END)
        def work():
            try:
                r=extract_source(src,out,parser)
                self.source_file=r.output_json; self.extract_dir=str(out); self.src_var.set(str(src));
                msg={"detected_version":r.source_version,"recovered_records":r.recovered_records,"people_json":r.output_json,"people_csv":r.output_csv,"inventory":r.inventory_json,"warnings":r.warnings}
                self.after(0,lambda:self._extract_done(msg))
            except Exception as e:
                self.after(0,lambda:self._extract_error(e))
        threading.Thread(target=work,daemon=True).start()
    def _extract_done(self,msg): self.extract_log.insert('1.0',json.dumps(msg,indent=2,ensure_ascii=False)); self.set_status(f"Extraction complete: {msg['recovered_records']:,} records.")
    def _extract_error(self,e): self.extract_log.insert('1.0','ERROR\n'+traceback.format_exc()); self.set_status('Extraction failed.'); messagebox.showerror(APP_TITLE,str(e))
    def load_extracted(self):
        p=filedialog.askopenfilename(filetypes=[('JSON','*.json'),('CSV','*.csv')])
        if not p:return
        self.load_source(Path(p))
    def load_source(self,path:Path):
        self.source_file=str(path)
        try:
            # Index large sources in SQLite for matching/validation without keeping all rows in RAM.
            db=path.with_suffix('.sqlite'); count=ingest_structured(path,db); self.extract_dir=str(path.parent)
            sample=[]
            for raw in list(read_structured(path))[:10]: sample.append(norm_row(raw))
            headers=list(sample[0].keys()) if sample else []
            self.mapping=automatic_mapping(headers); self._refresh_map()
            self.set_status(f'Loaded {count:,} records into {db.name}.')
            self.extract_log.insert(END,f"\nLoaded structured source: {path}\nStaging DB: {db}\nRecords: {count:,}\n")
        except Exception as e: messagebox.showerror(APP_TITLE,str(e))
    def _map_tab(self):
        t=self.tabs['map']; b=ttk.Frame(t); b.pack(fill=X); ttk.Button(b,text='Recalculate automatic mapping',command=self.auto_map).pack(side=LEFT); ttk.Button(b,text='Save Mapping',command=self.save_mapping).pack(side=LEFT,padx=5); ttk.Button(b,text='Load Mapping',command=self.load_mapping).pack(side=LEFT)
        frame=ttk.Frame(t); frame.pack(fill=BOTH,expand=True,pady=7); self.map_tree=ttk.Treeview(frame,columns=('source','target'),show='headings'); self.map_tree.heading('source',text='Source field'); self.map_tree.heading('target',text='Normalized/FMME field'); self.map_tree.column('source',width=300); self.map_tree.column('target',width=350); self.map_tree.pack(side=LEFT,fill=BOTH,expand=True); sb=ttk.Scrollbar(frame,command=self.map_tree.yview); sb.pack(side=RIGHT,fill=Y); self.map_tree.configure(yscrollcommand=sb.set)
        self.map_tree.bind('<Double-1>',self.edit_map)
    def _refresh_map(self):
        if not hasattr(self,'map_tree'): return
        self.map_tree.delete(*self.map_tree.get_children());
        for k,v in self.mapping.items(): self.map_tree.insert('',END,iid=k,values=(k,v))
    def edit_map(self,e):
        item=self.map_tree.identify_row(e.y); col=self.map_tree.identify_column(e.x)
        if not item or col!='#2': return
        x,y,w,h=self.map_tree.bbox(item,col); ent=ttk.Entry(self.map_tree); ent.place(x=x,y=y,width=w,height=h); ent.insert(0,self.mapping.get(item,'(ignore)')); ent.focus_set()
        def done(_=None): self.mapping[item]=ent.get().strip() or '(ignore)'; ent.destroy(); self._refresh_map()
        ent.bind('<Return>',done); ent.bind('<FocusOut>',done)
    def auto_map(self):
        if not self.source_file: messagebox.showinfo(APP_TITLE,'Load/extract a source first.'); return
        sample=[]
        for raw in list(read_structured(Path(self.source_file)))[:50]: sample.append(norm_row(raw))
        self.mapping=automatic_mapping(sample[0].keys() if sample else []); self._refresh_map(); self.set_status('Automatic mapping recalculated.')
    def save_mapping(self):
        p=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')]);
        if p: Path(p).write_text(json.dumps(self.mapping,indent=2),encoding='utf-8')
    def load_mapping(self):
        p=filedialog.askopenfilename(filetypes=[('JSON','*.json')]);
        if p: self.mapping=json.loads(Path(p).read_text(encoding='utf-8')); self._refresh_map()
    def _match_tab(self):
        t=self.tabs['match']; b=ttk.Frame(t); b.pack(fill=X); ttk.Button(b,text='Import Target Roster',command=self.import_target).pack(side=LEFT); ttk.Button(b,text='Run Indexed Matching',command=self.run_match).pack(side=LEFT,padx=6); ttk.Label(b,text='Threshold').pack(side=LEFT,padx=(15,3)); self.threshold=StringVar(value='0.78'); ttk.Entry(b,textvariable=self.threshold,width=6).pack(side=LEFT); self.match_info=StringVar(value='No target loaded'); ttk.Label(t,textvariable=self.match_info).pack(anchor=W,pady=5)
        fr=ttk.Frame(t); fr.pack(fill=BOTH,expand=True); self.match_tree=ttk.Treeview(fr,columns=('source','target','score'),show='headings');
        for c,lab,w in [('source','Source player',260),('target','Target player',260),('score','Score',80)]: self.match_tree.heading(c,text=lab); self.match_tree.column(c,width=w)
        self.match_tree.pack(side=LEFT,fill=BOTH,expand=True); sb=ttk.Scrollbar(fr,command=self.match_tree.yview); sb.pack(side=RIGHT,fill=Y); self.match_tree.configure(yscrollcommand=sb.set)
    def import_target(self):
        p=filedialog.askopenfilename(filetypes=[('CSV/JSON','*.csv *.json')]);
        if not p:return
        self.target_file=p; db=Path(p).with_suffix('.sqlite'); n=ingest_structured(Path(p),db); self.match_info.set(f'Target roster staged: {n:,} records ({Path(p).name})'); self.set_status('Target roster staged.')
    def run_match(self):
        if not self.source_file or not self.target_file: messagebox.showinfo(APP_TITLE,'Load a source and target roster first.'); return
        try: th=float(self.threshold.get())
        except: th=.78
        sdb=Path(self.source_file).with_suffix('.sqlite'); tdb=Path(self.target_file).with_suffix('.sqlite'); out=sdb.with_name('match_suggestions.json')
        try:
            n=candidate_matches(sdb,tdb,out,threshold=th); data=json.loads(out.read_text(encoding='utf-8')); self.match_tree.delete(*self.match_tree.get_children())
            for r in data[:5000]: self.match_tree.insert('',END,values=(r['source_name'],r['target_name'],r['score']))
            self.set_status(f'Indexed matching produced {n:,} candidate matches; report saved to {out.name}.')
        except Exception as e: messagebox.showerror(APP_TITLE,str(e))
    def _validate_tab(self):
        t=self.tabs['validate']; b=ttk.Frame(t); b.pack(fill=X); ttk.Button(b,text='Run Validation',command=self.run_validation).pack(side=LEFT); ttk.Button(b,text='Export Issue Report',command=self.export_issues).pack(side=LEFT,padx=6); self.val_sum=StringVar(value='Not run'); ttk.Label(b,textvariable=self.val_sum).pack(side=LEFT,padx=10)
        fr=ttk.Frame(t); fr.pack(fill=BOTH,expand=True,pady=6); self.issue_tree=ttk.Treeview(fr,columns=('sev','row','msg'),show='headings');
        for c,l,w in [('sev','Severity',80),('row','Row',70),('msg','Issue',850)]: self.issue_tree.heading(c,text=l); self.issue_tree.column(c,width=w)
        self.issue_tree.pack(side=LEFT,fill=BOTH,expand=True); sb=ttk.Scrollbar(fr,command=self.issue_tree.yview); sb.pack(side=RIGHT,fill=Y); self.issue_tree.configure(yscrollcommand=sb.set)
    def run_validation(self):
        if not self.source_file: messagebox.showinfo(APP_TITLE,'Load a source first.'); return
        try:
            n,self.issues=validate_structured(Path(self.source_file)); self.issue_tree.delete(*self.issue_tree.get_children())
            for x in self.issues[:10000]: self.issue_tree.insert('',END,values=x)
            e=sum(1 for x in self.issues if x[0]=='ERROR'); w=sum(1 for x in self.issues if x[0]=='WARN'); self.val_sum.set(f'{n:,} records · {e} errors · {w} warnings'); self.set_status('Validation completed.')
        except Exception as e: messagebox.showerror(APP_TITLE,str(e))
    def export_issues(self):
        if not self.issues:self.run_validation()
        p=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')]);
        if p:
            with open(p,'w',encoding='utf-8-sig',newline='') as f: w=csv.writer(f); w.writerow(['severity','row','message']); w.writerows(self.issues)
    def _export_tab(self):
        t=self.tabs['export']; ttk.Label(t,text='Target',font=('TkDefaultFont',13,'bold')).pack(anchor=W); r=ttk.Frame(t); r.pack(fill=X,pady=5); self.target=StringVar(value='FM26'); ttk.Combobox(r,textvariable=self.target,values=list(TARGETS),state='readonly',width=10).pack(side=LEFT); ttk.Label(r,text='  Export preserves the normalized schema; use the matching FMME version/profile to create final XML.').pack(side=LEFT,padx=8)
        b=ttk.Frame(t); b.pack(fill=X,pady=8); ttk.Button(b,text='Export FMME CSV',command=self.export_fmme).pack(side=LEFT); ttk.Button(b,text='Export JSON',command=self.export_json).pack(side=LEFT,padx=6); ttk.Button(b,text='Run ALL (map → validate → export)',command=self.run_all).pack(side=LEFT,padx=6)
        self.export_note=ScrolledText(t,height=18,wrap='word'); self.export_note.pack(fill=BOTH,expand=True); self.export_note.insert('1.0','For large historical databases, this application intentionally avoids requiring a human to type each record.\n\nThe legacy binary parser is version-specific. Supply a parser plugin when available; the workbench then handles the entire downstream pipeline automatically.\n\nFM24 and FM26 are supported as output targets through target-neutral normalized data and version-specific FMME profiles/templates.')
    def export_fmme(self):
        self._export_csv(kind='fmme')
    def export_json(self):
        if not self.source_file: messagebox.showinfo(APP_TITLE,'Load a source first.'); return
        p=filedialog.asksaveasfilename(defaultextension='.json',initialfile=f'retro_{self.target.get().lower()}_normalized.json',filetypes=[('JSON','*.json')]);
        if not p:return
        rows=[]
        for raw in read_structured(Path(self.source_file)):
            r=norm_row(raw); out={}
            for k,v in r.items():
                target=self.mapping.get(k,k)
                if target!='(ignore)': out[target]=v
            rows.append(out)
        Path(p).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8'); self.set_status(f'JSON exported: {p}')
    def _export_csv(self,kind='fmme'):
        if not self.source_file: messagebox.showinfo(APP_TITLE,'Load a source first.'); return
        p=filedialog.asksaveasfilename(defaultextension='.csv',initialfile=f'retro_{self.target.get().lower()}_fmme.csv',filetypes=[('CSV','*.csv')]);
        if not p:return
        write_mapped_csv(Path(self.source_file),Path(p),self.mapping); self.set_status(f'CSV exported: {p}')
    def run_all(self):
        if not self.source_file: messagebox.showinfo(APP_TITLE,'Extract/load a source first.'); return
        self.auto_map(); self.run_validation(); self.export_fmme()
    def save_project(self):
        p=filedialog.asksaveasfilename(defaultextension='.rfmproj',filetypes=[('Retro FM Project','*.rfmproj')]);
        if not p:return
        Path(p).write_text(json.dumps({'version':APP_VERSION,'source_file':self.source_file,'target_file':self.target_file,'extract_dir':self.extract_dir,'mapping':self.mapping,'target':self.target.get()},indent=2),encoding='utf-8')
    def open_project(self):
        p=filedialog.askopenfilename(filetypes=[('Retro FM Project','*.rfmproj')]);
        if not p:return
        d=json.loads(Path(p).read_text(encoding='utf-8')); self.source_file=d.get('source_file',''); self.target_file=d.get('target_file',''); self.extract_dir=d.get('extract_dir',''); self.mapping=d.get('mapping',{}); self.target.set(d.get('target','FM26')); self._refresh_map(); self.set_status(f"Project loaded: {Path(p).name}")

def main():
    root=Tk(); root.title(APP_TITLE); root.geometry('1200x760'); App(root); root.mainloop()
if __name__=='__main__': main()
