# 主备切换裁决：双源去重、来源可追回、重试幂等、写入原子
import json, csv, io, sqlite3
from pathlib import Path
import pytest
from app.pipeline import run, sample_text
from app.modules.m3_leases.rules import failover_merge
from app.modules.m1_sessions.rules import fields_for, FIELDS
from app.timeops import instant
from app.errors import BusinessError
from app import store
from app.exporter import evidence_csv

@pytest.fixture
def failover_text():
    return (Path(__file__).parent.parent/"sample_data"/"failover.csv").read_text(encoding="utf-8-sig")

@pytest.fixture
def failover(failover_text):
    return run(failover_text)

def at(text):
    return float(instant(text))

def ev(lid,source,a,b,user="u",kind="online",qty=1,rev=1,line=1):
    return {"lease_id":lid,"source":source,"a":a,"b":b,"user":user,"kind":kind,"quantity":qty,"rev":rev,"line":line,"canonical":"CAD"}

# ---- 裁决规则单元边界 ----

def test_merge_requires_cross_source():
    out=failover_merge([ev("A","primary",0,10,line=1),ev("B","primary",0,10,line=2)],[{"a":0,"b":10}])
    assert len(out)==2

def test_merge_requires_declared_window():
    pair=[ev("A","primary",0,10,line=1),ev("B","standby",0,10,line=2)]
    assert len(failover_merge(pair,[]))==2
    assert len(failover_merge(pair,[{"a":20,"b":30}]))==2
    assert len(failover_merge(pair,[{"a":0,"b":10}]))==1

def test_merge_requires_same_usage():
    assert len(failover_merge([ev("A","primary",0,10,qty=1,line=1),ev("B","standby",0,10,qty=2,line=2)],[{"a":0,"b":10}]))==2
    assert len(failover_merge([ev("A","primary",0,10,user="u1",line=1),ev("B","standby",0,10,user="u2",line=2)],[{"a":0,"b":10}]))==2
    assert len(failover_merge([ev("A","primary",0,10,rev=1,line=1),ev("B","standby",0,10,rev=2,line=2)],[{"a":0,"b":10}]))==2

def test_merge_unions_interval_and_prefers_primary_id():
    out=failover_merge([ev("B","standby",2,8,line=4),ev("A","primary",0,5,line=3)],[{"a":0,"b":10}])
    assert len(out)==1
    assert out[0]["a"]==0 and out[0]["b"]==8 and out[0]["source"]=="both"
    assert out[0]["lease_id"]=="A"
    assert [o["line"] for o in out[0]["origins"]]==[3,4]

def test_merge_transitive_through_shared_side():
    out=failover_merge([ev("A","primary",0,6,line=1),ev("B","standby",0,3,line=2),ev("C","standby",3,6,line=3)],[{"a":0,"b":10}])
    assert len(out)==1 and len(out[0]["origins"])==3

def test_source_column_optional(failover_text):
    assert len(fields_for(failover_text))==len(FIELDS)+1
    assert fields_for(sample_text())==FIELDS

# ---- 样例结论：来源可见、真实超用 ----

def test_failover_balance(failover):
    assert failover["balance"]=={"input":13,"accepted":11,"quarantined":2,"blank":0}

def test_failover_same_lease_id_both_sides_survive_intake(failover):
    assert len([r for r in failover["raw"] if r["lease_id"]=="L01"])==2

def test_failover_merge_groups(failover):
    groups=failover["failover"]["groups"]
    assert [g["id"] for g in groups]==["L01","L02"]
    assert all(g["seats"]==1 for g in groups)
    l02=[g for g in groups if g["id"]=="L02"][0]
    assert [(s["lease_id"],s["source"],s["line"]) for s in l02["sources"]]==[("L02","primary",6),("L09","standby",7)]

def test_failover_merged_counts_once(failover):
    leases=failover["leases"]
    assert len(leases)==6
    assert sum(l["lease_id"]=="L01" for l in leases)==1
    assert {l["source"] for l in leases if l["lease_id"] in {"L01","L02"}}=={"both"}

def test_failover_standby_only_user_kept(failover):
    l03=[l for l in failover["leases"] if l["lease_id"]=="L03"]
    assert len(l03)==1 and l03[0]["source"]=="standby"

def test_failover_outside_window_not_merged(failover):
    ids={l["lease_id"] for l in failover["leases"]}
    assert {"L05","L10"}<=ids

def test_failover_release_matches_across_sources(failover):
    l02=[l for l in failover["leases"] if l["lease_id"]=="L02"][0]
    assert float(l02["b"])==at("2026-11-19T04:00:00+00:00")

def test_failover_real_vs_inflated_peak(failover):
    assert failover["peaks"]=={"CAD":{"real":3,"inflated":4}}
    assert failover["reports"][3]["metrics"]["名义峰值"]==4

def test_failover_segment_source_breakdown(failover):
    seg=[s for s in failover["segments"] if float(s["a"])==at("2026-11-19T02:30:00+00:00")][0]
    assert (seg["count"],seg["primary"],seg["standby"],seg["both"])==(3,0,1,2)

def test_failover_real_excess_flagged(failover):
    over=[u for u in failover["usage"] if u["excess"]>0]
    assert len(over)==2
    flagged=[u for u in over if u["failover"]]
    assert len(flagged)==1 and float(flagged[0]["a"])==at("2026-11-19T02:30:00+00:00")
    assert failover["reports"][4]["metrics"]["切换期超用"]==1

def test_failover_audit_trail(failover):
    assert sum(r["reason"]=="FAILOVER_MERGED" for r in failover["lease_audit"])==2
    assert failover["reports"][6]["metrics"]["切换合并"]==2

def test_failover_invalid_source_quarantined(failover):
    assert failover["reasons"].get("SOURCE")==1

def test_failover_window_required_otherwise_conflict(failover_text):
    text="\n".join(l for l in failover_text.splitlines() if not l.startswith("FW01"))
    r=run(text)
    assert r["failover"]["groups"]==[]
    assert r["reasons"].get("LEASE_CONFLICT")==1
    assert r["peaks"]["CAD"]["real"]==4

# ---- 重试幂等：同批切换事件不新增占用 ----

def test_failover_retry_inside_file_no_new_occupancy(failover):
    assert failover["reasons"].get("DUPLICATE_EVENT")==1
    assert len(failover["leases"])==6 and failover["peaks"]["CAD"]["real"]==3

def test_failover_retry_again_still_no_new_occupancy(failover_text):
    row="L03,CAD,userC,2026-11-19T02:30:00+00:00,2026-11-19T06:00:00+00:00,online,1,1,standby"
    r=run(failover_text+row+"\n")
    assert r["reasons"].get("DUPLICATE_EVENT")==2
    assert len(r["leases"])==6 and r["peaks"]["CAD"]["real"]==3

def test_failover_deterministic(failover_text):
    a,b=run(failover_text),run(failover_text)
    assert a["failover"]["groups"]==b["failover"]["groups"] and a["peaks"]==b["peaks"]

def test_failover_rerun_reuses_same_batch(failover_text):
    a=store.save(failover_text,run(failover_text))
    b=store.save(failover_text,run(failover_text))
    assert a["id"]==b["id"] and a["revision"]==b["revision"]
    assert sum(h["id"]==a["id"] for h in store.history())==1

# ---- 证据导出与工作台同一结论 ----

def test_failover_export_matches_result(failover_text):
    saved=store.save(failover_text,run(failover_text))
    rows=list(csv.reader(io.StringIO(evidence_csv(saved).lstrip("\ufeff"))))
    manifest=json.loads([r for r in rows if r[3]=="manifest"][0][6])
    assert manifest["failover"]["peaks"]=={"CAD":{"real":3,"inflated":4}}
    assert manifest["failover"]["merged"]==2 and manifest["failover"]["windows"]==1
    merges=[json.loads(r[6]) for r in rows if r[3]=="failover_merge"]
    assert merges==saved["result"]["failover"]["groups"]
    windows=[json.loads(r[6]) for r in rows if r[3]=="failover_window"]
    assert windows==saved["result"]["failover"]["windows"]
    over=[json.loads(r[6]) for r in rows if r[3]=="result"]
    assert any(o.get("failover") for o in over)

def test_failover_export_traces_original_lines(failover_text):
    saved=store.save(failover_text,run(failover_text))
    rows=list(csv.reader(io.StringIO(evidence_csv(saved).lstrip("\ufeff"))))
    merges=[json.loads(r[6]) for r in rows if r[3]=="failover_merge"]
    lines={s["line"] for m in merges for s in m["sources"]}
    assert lines=={4,5,6,7}

# ---- 写入失败保留旧版 ----

def test_store_write_failure_keeps_old_version(monkeypatch):
    text="store-probe-写入失败保留旧版"
    saved=store.save(text,run(sample_text()))
    def broken():
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(store,"connect",broken)
    with pytest.raises(BusinessError) as caught:
        store.save(text+"-retry",run(sample_text()))
    assert caught.value.code=="STORE" and caught.value.status==500
    monkeypatch.undo()
    kept=store.get(saved["id"])
    assert kept["revision"]==saved["revision"] and kept["digest"]==saved["digest"]
    assert kept["result"]["balance"]==saved["result"]["balance"]

def test_store_unserializable_result_never_touches_db():
    before={h["id"] for h in store.history()}
    with pytest.raises(TypeError):
        store.save("store-probe-序列化失败",{"bad":object()})
    assert {h["id"] for h in store.history()}==before
