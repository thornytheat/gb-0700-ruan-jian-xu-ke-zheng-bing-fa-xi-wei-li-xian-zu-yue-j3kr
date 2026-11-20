import csv,io,json

def evidence_csv(run):
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(["run_id","sha256","rule_version","kind","line","reason","evidence"])
    failover=run["result"].get("failover",{})
    summary={"windows":len(failover.get("windows",[])),"merged":len(failover.get("groups",[])),"peaks":failover.get("peaks",{})}
    writer.writerow([run["id"],run["digest"],run["rule_version"],"manifest","","",json.dumps({"balance":run["result"]["balance"],"decision":run["decision"],"revision":run["revision"],"failover":summary},ensure_ascii=False)])
    for row in failover.get("windows",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"failover_window",row.get("line",""),"FAILOVER_WINDOW",json.dumps(row,ensure_ascii=False)])
    for row in failover.get("groups",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"failover_merge",row["sources"][0]["line"] if row.get("sources") else "","FAILOVER_MERGED",json.dumps(row,ensure_ascii=False)])
    for row in run["result"].get("final",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"result",row.get("line",""),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in run["result"].get("quarantine",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"quarantine",row.get("line",""),row["reason"],json.dumps(row,ensure_ascii=False)])
    return "\ufeff"+out.getvalue()
