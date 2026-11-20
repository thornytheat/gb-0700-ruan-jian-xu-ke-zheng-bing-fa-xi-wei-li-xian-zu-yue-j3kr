import csv, io
from app.reader import read_rows
from app.report import report,quarantine
FIELDS="lease_id product user start end kind version seats".split()
SOURCE_FIELD="source"

def header_cells(text):
    lines=text.lstrip("\ufeff").splitlines() if text else []
    if not lines:return []
    try:return [c.strip() for c in next(csv.reader(io.StringIO(lines[0])))]
    except (csv.Error,StopIteration):return []

def fields_for(text):
    cells=header_cells(text)
    if len(cells)==len(FIELDS)+1 and set(cells)==set(FIELDS)|{SOURCE_FIELD}:return FIELDS+[SOURCE_FIELD]
    return FIELDS

def source_key(row):
    return row.get("source","").strip().lower()

def apply(ctx):
    rows,bad,blank=read_rows(ctx["text"],fields_for(ctx["text"]));ctx["quarantine"].extend(bad);ctx["blank_rows"]=blank;ctx["input_count"]=len(rows)+len(bad)+blank
    out=[];seen=set()
    for r in rows:
        key=(r["product"],r["lease_id"],r["kind"],r["version"],r["start"],source_key(r))
        if not r["lease_id"]:quarantine(ctx,r,"ID_REQUIRED");continue
        if key in seen:quarantine(ctx,r,"DUPLICATE_EVENT");continue
        seen.add(key);out.append(r)
    ctx["raw"]=out;return report(out,会话事件=len(out),隔离=len(ctx["quarantine"]))
