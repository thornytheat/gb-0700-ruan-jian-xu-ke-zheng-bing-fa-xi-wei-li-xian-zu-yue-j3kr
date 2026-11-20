from app.report import report,quarantine

def close_time(kind,start,end,releases):
    if kind=="offline":return end
    times=[t for t in releases if start<=t<end]
    return min(times) if times else end

def overlaps(x,y):
    return x["a"]<y["b"] and y["a"]<x["b"]

def in_window(x,y,windows):
    a,b=max(x["a"],y["a"]),min(x["b"],y["b"])
    return any(w["a"]<b and a<w["b"] for w in windows)

def same_usage(x,y):
    return x["user"]==y["user"] and x["kind"]==y["kind"] and x["quantity"]==y["quantity"] and x["rev"]==y["rev"]

def origin(r):
    return {"line":r["line"],"lease_id":r["lease_id"],"source":r["source"],"a":r["a"],"b":r["b"]}

def merge_group(group):
    ordered=sorted(group,key=lambda r:(r["source"]!="primary",r["lease_id"],r["line"]))
    merged=dict(ordered[0])
    merged["a"]=min(r["a"] for r in group);merged["b"]=max(r["b"] for r in group)
    merged["source"]="both";merged["line"]=min(r["line"] for r in group)
    merged["origins"]=sorted((origin(r) for r in group),key=lambda o:o["line"])
    return merged

def failover_merge(events,windows):
    parent=list(range(len(events)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i in range(len(events)):
        for j in range(i+1,len(events)):
            x,y=events[i],events[j]
            if x["source"]!=y["source"] and same_usage(x,y) and overlaps(x,y) and in_window(x,y,windows):
                a,b=find(i),find(j)
                if a!=b:parent[b]=a
    groups={}
    for i in range(len(events)):groups.setdefault(find(i),[]).append(events[i])
    out=[]
    for g in groups.values():
        if len(g)>1:out.append(merge_group(g))
        else:
            x=dict(g[0]);x["origins"]=[origin(g[0])];out.append(x)
    return out

def adjudicate(entity,releases,sink):
    chosen={};audit=[]
    for r in entity:
        key=(r["canonical"],r["lease_id"])
        if key not in chosen or r["rev"]>chosen[key]["rev"]:
            if key in chosen:audit.append({"id":chosen[key]["lease_id"],"reason":"SUPERSEDED"})
            chosen[key]=r
        elif r["rev"]==chosen[key]["rev"]:sink(r,"LEASE_CONFLICT")
        else:audit.append({"id":r["lease_id"],"reason":"SUPERSEDED"})
    out=[]
    for key,r in chosen.items():
        ids={o["lease_id"] for o in r.get("origins",[])}|{r["lease_id"]}
        times=[x["a"] for x in releases if x["canonical"]==key[0] and x["lease_id"] in ids and x["rev"]==r["rev"]]
        x=dict(r);x["b"]=close_time(r["kind"],r["a"],r["b"],times);out.append(x)
        if r["kind"]=="offline" and times:audit.append({"id":r["lease_id"],"reason":"OFFLINE_UNTIL_EXPIRY"})
    return out,audit

def apply(ctx):
    normalized=ctx["normalized"]
    entity=[r for r in normalized if r["kind"] in {"online","offline"}]
    releases=[r for r in normalized if r["kind"]=="release"]
    windows=[r for r in normalized if r["kind"]=="failover"]
    merged=[]
    for product in sorted({r["canonical"] for r in entity}):
        merged.extend(failover_merge([r for r in entity if r["canonical"]==product],[w for w in windows if w["canonical"]==product]))
    leases,audit=adjudicate(merged,releases,lambda r,reason:quarantine(ctx,r,reason))
    inflated,_=adjudicate(entity,releases,lambda r,reason:None)
    for r in merged:
        if len(r["origins"])>1:audit.append({"id":r["lease_id"],"reason":"FAILOVER_MERGED"})
    for r in normalized:
        if r["kind"]=="heartbeat":audit.append({"id":r["lease_id"],"reason":"HEARTBEAT_NO_SEAT"})
    ctx["leases"]=leases;ctx["leases_inflated"]=inflated;ctx["lease_audit"]=audit
    ctx["failover"]={"windows":[dict(product=w["canonical"],a=w["a"],b=w["b"],line=w["line"],id=w["lease_id"]) for w in sorted(windows,key=lambda w:(w["canonical"],w["a"],w["line"]))],
        "groups":[dict(id=r["lease_id"],product=r["canonical"],user=r["user"],kind=r["kind"],seats=r["quantity"],rev=r["rev"],a=r["a"],b=r["b"],sources=r["origins"]) for r in merged if len(r["origins"])>1]}
    ctx["failover"]["groups"].sort(key=lambda g:(g["product"],g["a"],g["id"]))
    return report(leases,在线=sum(r["kind"]=="online" for r in leases),离线=sum(r["kind"]=="offline" for r in leases),切换合并=len(ctx["failover"]["groups"]),切换窗口=len(windows))
