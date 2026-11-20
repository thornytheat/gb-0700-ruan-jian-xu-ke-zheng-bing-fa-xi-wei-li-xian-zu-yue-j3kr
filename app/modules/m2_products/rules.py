from app.timeops import instant
from app.report import report,quarantine
from app.errors import BusinessError
from app.numbers import number
ALIASES={"CAD-Pro":"CAD","cad":"CAD","CAD":"CAD","Render":"RENDER","RENDER":"RENDER"}
SOURCES={"primary":"primary","standby":"standby"}
KINDS={"online","offline","heartbeat","release","capacity","failover"}
def product(text):
    if text not in ALIASES:raise BusinessError("PRODUCT","产品未登记")
    return ALIASES[text]

def seats(text):
    value=number(text)
    if value<=0 or value!=value.to_integral_value():raise BusinessError("SEATS","席位须为正整数")
    return int(value)

def source(text):
    value=str(text or "").strip().lower()
    if not value:return "primary"
    if value not in SOURCES:raise BusinessError("SOURCE","来源须为primary或standby")
    return SOURCES[value]

def apply(ctx):
    out=[]
    for r in ctx["raw"]:
        try:
            x=dict(r);x["canonical"]=product(r["product"]);x["a"]=instant(r["start"]);x["b"]=instant(r["end"]) if r["end"] else x["a"];x["rev"]=int(r["version"]);x["quantity"]=seats(r["seats"]);x["source"]=source(r.get("source",""))
            if x["rev"]<1:raise BusinessError("VERSION","版本须为正")
            if r["kind"] not in KINDS:raise BusinessError("KIND","事件类型无效")
            if r["kind"] in {"online","offline","capacity","failover"} and x["b"]<=x["a"]:raise BusinessError("INTERVAL","租约区间无效")
            out.append(x)
        except (BusinessError,ValueError) as e:quarantine(ctx,r,getattr(e,"code","VERSION"))
    ctx["normalized"]=out;return report(out,产品=len({r["canonical"] for r in out}),有效事件=len(out),备源事件=sum(r["source"]=="standby" for r in out),切换窗口=sum(r["kind"]=="failover" for r in out))
