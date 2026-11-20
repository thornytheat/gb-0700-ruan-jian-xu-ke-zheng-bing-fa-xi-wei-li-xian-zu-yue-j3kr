from app.report import report

def sweep(leases):
    points=sorted({r[k] for r in leases for k in ("a","b")});out=[]
    for a,b in zip(points,points[1:]):
        active=[r for r in leases if r["a"]<=a<r["b"]]
        if active:out.append({"a":a,"b":b,"count":sum(r["quantity"] for r in active),"ids":sorted(r["lease_id"] for r in active),
            "primary":sum(r["quantity"] for r in active if r.get("source")=="primary"),
            "standby":sum(r["quantity"] for r in active if r.get("source")=="standby"),
            "both":sum(r["quantity"] for r in active if r.get("source")=="both")})
    return out

def apply(ctx):
    out=[];by_product={}
    for product in sorted({r["canonical"] for r in ctx["leases"]}):
        segments=sweep([r for r in ctx["leases"] if r["canonical"]==product]);by_product[product]=segments
        out.extend(dict(r,product=product) for r in segments)
    peaks={}
    for product in sorted(set(by_product)|{r["canonical"] for r in ctx["leases_inflated"]}):
        peaks[product]={"real":max((r["count"] for r in by_product.get(product,[])),default=0),
            "inflated":max((r["count"] for r in sweep([r for r in ctx["leases_inflated"] if r["canonical"]==product])),default=0)}
    ctx["segments"]=out;ctx["peaks"]=peaks;ctx["failover"]["peaks"]=peaks
    return report(out,峰值=max((r["count"] for r in out),default=0),名义峰值=max((p["inflated"] for p in peaks.values()),default=0),区间=len(out))
