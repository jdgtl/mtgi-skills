#!/usr/bin/env python3
"""
MTGI drive MPN enrichment — decoder-first, ICEcat fallback.
Pipeline per row: extract MPN(s) from blob -> capacity-from-text
  -> vendor decoder -> ICEcat Live API -> unresolved flag -> cache write-back.
Conservative: a field is only emitted when the pattern is unambiguous.
Contradictions between text-capacity and decoder-capacity are flagged, not hidden.
"""
import csv, re, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

ICECAT_USER  = os.environ.get("ICECAT_USER", "openIcecat")

# ── Config resolvers (lazy, skill-aware) ──────────────────────────────────────
# Resolved at call time so the rfq-normalizer skill's workspace + credential
# store are picked up. The engine stays runnable standalone (pure stdlib): the
# skill imports below are optional.

def _icecat_token():
    return os.environ.get("ICECAT_TOKEN") or _cred("icecat_token") or ""

def _brave_key():
    # Engine's own env name first, then the skill's stored Brave key.
    return os.environ.get("BRAVE_API_KEY") or _cred("brave_search_api_key") or ""

def _cred(name):
    try:
        from credentials import get as _get
        return _get(name)
    except Exception:
        return None

def _cache_path():
    explicit = os.environ.get("MPN_CACHE")
    if explicit:
        return explicit
    try:
        from workspace import workspace_dir
        d = workspace_dir() / ".rfq-cache"
        d.mkdir(parents=True, exist_ok=True)
        return str(d / "mpn_cache.json")
    except Exception:
        return "mpn_cache.json"

def load_cache():
    try:
        with open(_cache_path()) as f: return json.load(f)
    except Exception: return {}
def save_cache(c):
    try:
        with open(_cache_path(), "w") as f: json.dump(c, f, indent=2)
    except OSError:
        pass  # caching is best-effort

def _now(): return datetime.now(timezone.utc).isoformat()
def _fresh(entry, ttl_days):
    ts = entry.get("cached_at")
    if not ts: return False
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return False
    return datetime.now(timezone.utc) - dt < timedelta(days=ttl_days)

# ---------- MPN extraction ----------
MPN_PATTERNS = [
    ("seagate", r"\bST\d{3,6}[A-Z]{2}\d{3,4}\b"),
    ("seagate", r"\bST9\d{3,5}\d*(?:SS|NS)\b"),
    ("seagate", r"\bST3\d{4,6}[A-Z]{2}\b"),
    ("seagate", r"\bST\d{5,8}(?:SS|NS|AS)\b"),
    ("seagate", r"\bST\d{3,4}(?:LM|LX|VN|VX|VM|NX|DM|DX|NM)\d{2,4}\b"),
    ("hgst",    r"\bH[US][A-Z]?\d{6,9}[A-Z]{2,4}\d{0,3}\b"),
    ("hgst",    r"\bHTS\d{6}[A-Z0-9]{4,8}\b"),
    ("hgst",    r"\b[57]K\d{3,4}-\d{3,4}\b"),                 # 7K1000-1000
    ("hitachi", r"\bH[DT][ES]\d{6}[A-Z]{3}\d{3}\b"),          # HDE721010SLA330
    ("toshiba_hde", r"\bHDE[A-Z]{2}\d{2}[A-Z]{3}\d{2}\b"),    # HDEPM40DAB51
    ("toshiba", r"\bMB[A-F]\d{4}RC\b"),                       # MBD2300RC (Fujitsu/Toshiba SAS)
    ("toshiba", r"\b(?:MG|MQ|MK|DT|AL)[0-9A-Z]{6,12}\b"),
    ("hp_oem",  r"\b(?:EG|EH|MB|MM|MO|VK|MK)\d{4}[A-Z]{2,5}\b"),  # EG0300FAWHV, MB1000GCWCV
    ("wd",      r"\bWDS?\d{2,4}[A-Z]\d?[A-Z0-9]{2,6}\b"),
    ("wd",      r"\bWD\d{3,4}(?:BKHG|BLHX)\b"),
    ("samsung", r"\bM[ZK][- ]?[0-9A-Z]{6,14}\b"),
    ("micron",  r"\bMTFD[A-Z0-9]{8,18}\b"),
    ("crucial", r"\bCT\d{3,4}[A-Z0-9]{4,10}\b"),
]
PAREN = re.compile(r"\(([^)]+)\)")

def extract_mpns(brand, model):
    found = []; seen = set()
    for chunk in PAREN.findall(model) + [model]:
        for vguess, pat in MPN_PATTERNS:
            for m in re.findall(pat, chunk, flags=re.I):
                mm = m if isinstance(m, str) else m[0]
                key = mm.upper().replace(" ", "")
                if key not in seen:
                    seen.add(key); found.append((vguess, mm.strip()))
    return found

# ---------- capacity from text ----------
CAP_TB = re.compile(r"(\d+(?:\.\d+)?)\s*TB\b", re.I)
CAP_GB = re.compile(r"(\d{2,5})\s*GB\b", re.I)
CAP_G  = re.compile(r"(\d{2,4})G\b")          # 120G, 240G, 256G (no space)
def capacity_from_text(s):
    m = CAP_TB.search(s)
    if m:
        tb=float(m.group(1)); return f"{int(tb*1000)} GB" if tb<10 else f"{int(tb)} TB"
    m = CAP_GB.search(s)
    if m: return f"{int(m.group(1))} GB"
    m = CAP_G.search(s)
    if m:
        v=int(m.group(1))
        if 16<=v<=2000: return f"{v} GB"
    return ""

SSD_TOKENS = ("REALSSD","SSD","EVO","MX300","MX500","MX100"," 320 ","S3500","S3700",
              "S3520","S3510","5200","5100","1100"," 520 ","860 ","850 ","870 ",
              "PM87","PM86","SM84","SM86","P400E","CS900","SA400","SUV","SDSSD",
              "VI550","CV3","SL3N","420K","X400","DC S3")
def looks_ssd(blob):
    u=" "+blob.upper()+" "
    return any(t in u for t in SSD_TOKENS)

# ---------- decoders ----------
SEAGATE_FAMILY = {
    "DM":("3.5\"","SATA","HDD","7200"),"DX":("3.5\"","SATA","SSHD","7200"),
    "NM":("3.5\"","SATA","HDD","7200"),"MM":("2.5\"","SAS","HDD","10000"),
    "MP":("2.5\"","SAS","HDD","15000"),"LM":("2.5\"","SATA","HDD","5400"),
    "LX":("2.5\"","SATA","SSHD","5400"),"VN":("3.5\"","SATA","HDD","5900"),
    "VX":("3.5\"","SATA","HDD","5900"),"VM":("2.5\"","SATA","HDD","5400"),
    "NX":("2.5\"","SATA","HDD","7200"),
}
def decode_seagate(mpn):
    u=mpn.upper(); out={}
    m=re.match(r"ST(\d+)(DM|DX|NM|MM|MP|LM|LX|VN|VX|VM|NX)(\d+)?",u)
    if m:
        digits=m.group(1); fam=m.group(2)
        # leading 9 on a 2.5" family code is a form-factor marker, not capacity
        if digits.startswith("9") and len(digits)>3: digits=digits[1:]
        cap=int(digits)
        if 100<=cap<=20000: out["capacity"]=f"{cap} GB" if cap<1000 else f"{cap//1000} TB"
        ff,iface,typ,spd=SEAGATE_FAMILY[fam]
        out.update(form_factor=ff,interface=iface,type=typ,speed=spd); return out
    m=re.match(r"ST9(\d{3,4})\d*(SS|NS)",u)
    if m:
        digits=m.group(1)
        # legacy 2.5 capacity is the 3-digit value (e.g. ST9500620NS = 500GB, ST91000640SS = 1000GB)
        if digits.startswith("1") and len(digits)>=4: cap=int(digits[:4])   # 1000
        else: cap=int(digits[:3])                                            # 300, 500, 600, 900
        out["capacity"]=f"{cap} GB" if cap<1000 else f"{cap//1000} TB"
        out.update(form_factor="2.5\"",type="HDD",
                   interface="SAS" if m.group(2)=="SS" else "SATA"); return out
    m=re.match(r"ST3(1000|2000|3000|4000|6000|8000|750|500|320|250|160)\d*(AS|NS|SS)",u)
    if m:
        cap=int(m.group(1)); out["capacity"]=f"{cap} GB" if cap<1000 else f"{cap//1000} TB"
        out.update(form_factor="3.5\"",type="HDD",
                   interface="SAS" if m.group(2)=="SS" else "SATA"); return out
    m=re.match(r"ST3\d{4,6}(AS|NS|SS)",u)   # 3.5 legacy, no clean capacity
    if m:
        out.update(form_factor="3.5\"",type="HDD",
                   interface="SAS" if m.group(1)=="SS" else "SATA"); return out
    return out

WD_SUFFIX_FORM = {
    "EZEX":("3.5\"","SATA"),"EZRZ":("3.5\"","SATA"),"EZRX":("3.5\"","SATA"),
    "EARS":("3.5\"","SATA"),"EURX":("3.5\"","SATA"),"EFRX":("3.5\"","SATA"),
    "EFZX":("3.5\"","SATA"),"PURZ":("3.5\"","SATA"),"FYYZ":("3.5\"","SATA"),
    "FYPS":("3.5\"","SATA"),"FBYX":("3.5\"","SATA"),"FAEX":("3.5\"","SATA"),
    "FALS":("3.5\"","SATA"),"FASS":("3.5\"","SATA"),"FZWX":("3.5\"","SATA"),
    "FZBX":("3.5\"","SATA"),"FZEX":("3.5\"","SATA"),"FYYS":("3.5\"","SATA"),
    "JPVX":("2.5\"","SATA"),"JPLX":("2.5\"","SATA"),"SPVX":("2.5\"","SATA"),
    "SPZX":("2.5\"","SATA"),"NPVZ":("2.5\"","SATA"),"NPVX":("2.5\"","SATA"),
    "BKHG":("2.5\"","SATA"),"BLHX":("2.5\"","SATA"),
}
def decode_wd(mpn):
    u=mpn.upper(); out={"type":"HDD"}
    m=re.match(r"WDS(\d+)(T|G)",u)
    if m:
        n=int(m.group(1)); out["capacity"]=(f"{n//100} TB" if m.group(2)=="T" else f"{n} GB")
        out.update(type="SSD"); return out
    m=re.match(r"WD(\d{3,4})(BKHG|BLHX)",u)
    if m:
        s=m.group(1); cap=300 if s.startswith("3") else (600 if s.startswith("6") else None)
        if cap: out["capacity"]=f"{cap} GB"
        out.update(form_factor="2.5\"",interface="SATA",speed="10000"); return out
    m=re.match(r"WD(\d{2,3})([A-Z])",u)
    if m and int(m.group(1))<=120:
        n=int(m.group(1)); out["capacity"]=f"{n//10} TB" if n>=10 else f"{n*100} GB"
    for suf,(ff,iface) in WD_SUFFIX_FORM.items():
        if u.endswith(suf) or suf in u: out.update(form_factor=ff,interface=iface); break
    return out

TOSHIBA_FAMILY = {"MG":("3.5\"","SATA","HDD"),"MQ":("2.5\"","SATA","HDD"),
                  "MK":("2.5\"","SATA","HDD"),"DT":("3.5\"","SATA","HDD"),
                  "AL":("2.5\"","SAS","HDD")}
def decode_toshiba(mpn):
    u=mpn.upper(); out={}
    m=re.match(r"MB[A-F](\d)(\d{3})RC",u)   # Fujitsu/Toshiba enterprise SAS 2.5
    if m:
        out.update(form_factor="2.5\"",interface="SAS",type="HDD",
                   capacity=f"{int(m.group(2))} GB"); return out
    pre=u[:2]
    if pre in TOSHIBA_FAMILY:
        ff,iface,typ=TOSHIBA_FAMILY[pre]; out.update(form_factor=ff,interface=iface,type=typ)
    return out

def decode_toshiba_hde(mpn):
    # Toshiba enterprise HDE** = 3.5" enterprise; capacity not reliably in code -> leave blank
    return {"form_factor":"3.5\"","type":"HDD","interface":"SAS"}

def decode_hgst(mpn):
    u=mpn.upper(); out={"type":"HDD"}
    m=re.match(r"([57])K\d{3,4}-(\d{3,4})",u)   # 7K1000-1000
    if m:
        cap=int(m.group(2)); out["capacity"]=f"{cap} GB" if cap<1000 else f"{cap//1000} TB"
        out["speed"]="7200" if m.group(1)=="7" else "5400"; return out
    if "CSS" in u or u.endswith(("SS600","SS204","SS200")): out["interface"]="SAS"
    elif "CLA" in u or "ALA" in u or "ALN" in u or "ALE" in u or "SLA" in u: out["interface"]="SATA"
    if u.startswith(("HUC","HTS","HUSMM","HUSMR")): out["form_factor"]="2.5\""
    elif u.startswith(("HUA","HUH","HUS72","HDS","HDE7")): out["form_factor"]="3.5\""
    return out

def decode_hitachi(mpn):
    u=mpn.upper(); out={"type":"HDD"}
    # Deskstar HDE/HDS 7210xx = 7200rpm; capacity from the 10/15/20 after 7210
    m=re.match(r"H[DT][ES]72(\d{2})(\d{2})",u)
    if m:
        capmap={"10":"1 TB","15":"1.5 TB","20":"2 TB","05":"500 GB","32":"320 GB"}
        c=capmap.get(m.group(2))
        if c: out["capacity"]=c
    out.update(form_factor="3.5\"",interface="SATA",speed="7200"); return out

HP_OEM = {"EG":("2.5\"","SAS","HDD","10000"),"EH":("2.5\"","SAS","HDD","15000"),
          "MB":("3.5\"","SATA","HDD","7200"),"MM":("2.5\"","SAS","HDD",""),
          "MO":("2.5\"","","SSD",""),"VK":("2.5\"","SATA","SSD",""),
          "MK":("2.5\"","SATA","SSD","")}
def decode_hp_oem(mpn):
    u=mpn.upper(); out={}
    m=re.match(r"(EG|EH|MB|MM|MO|VK|MK)(\d{4})",u)
    if not m: return out
    pre=m.group(1); cap=int(m.group(2))
    ff,iface,typ,spd=HP_OEM[pre]
    out.update(form_factor=ff,type=typ)
    if iface: out["interface"]=iface
    if spd: out["speed"]=spd
    if 100<=cap<=20000: out["capacity"]=f"{cap} GB" if cap<1000 else f"{cap/1000:g} TB"
    return out

DECODERS={"seagate":decode_seagate,"wd":decode_wd,"toshiba":decode_toshiba,
          "toshiba_hde":decode_toshiba_hde,"hgst":decode_hgst,"hitachi":decode_hitachi,
          "hp_oem":decode_hp_oem}

# ---------- ICEcat ----------
def icecat_lookup(brand, code):
    token=_icecat_token()
    if not token: return None,"NO_TOKEN"
    u=("https://live.icecat.biz/api?UserName="+urllib.parse.quote(ICECAT_USER)
       +"&Language=en&Brand="+urllib.parse.quote(brand)
       +"&ProductCode="+urllib.parse.quote(code)+"&api_token="+token)
    try:
        r=urllib.request.urlopen(u,timeout=15).read(); d=json.loads(r); feats={}
        for g in d.get("data",{}).get("FeaturesGroups",[]):
            for f in g.get("Features",[]):
                n=f.get("Feature",{}).get("Name",{}).get("Value","")
                feats[n.lower()]=f.get("PresentationValue","")
        out={}
        for k in("hdd capacity","ssd capacity","storage capacity","capacity"):
            if feats.get(k): out["capacity"]=feats[k]; break
        for k in("hdd size","ssd form factor","form factor"):
            if feats.get(k): out["form_factor"]=feats[k]; break
        if feats.get("interface"): out["interface"]=feats["interface"]
        if feats.get("type"): out["type"]=feats["type"]
        if feats.get("hdd speed"): out["speed"]=feats["hdd speed"]
        return (out or None),"OK"
    except urllib.error.HTTPError as e: return None,f"HTTP{e.code}"
    except Exception as e: return None,type(e).__name__

# ---------- web search tier (Brave Search API; fills type/interface/form ONLY, never capacity) ----------

def _scan_fields(text):
    """Conservative field extraction from free text. Returns dict; only unambiguous signals."""
    t = " " + text.lower() + " "
    out = {}
    # type
    is_ssd = ("solid state" in t) or (" ssd " in t)
    is_hdd = ("hard drive" in t) or (" hdd " in t) or (" rpm" in t)
    is_sshd = ("sshd" in t) or ("hybrid drive" in t)
    if is_sshd: out["type"]="SSHD"
    elif is_ssd and not is_hdd: out["type"]="SSD"
    elif is_hdd and not is_ssd: out["type"]="HDD"
    # interface (blank if both present -> ambiguous)
    has_sas = " sas " in t or "serial attached scsi" in t
    has_sata = " sata" in t or "serial ata" in t
    has_nvme = "nvme" in t or "pcie" in t
    ifaces=[x for x,p in (("SAS",has_sas),("SATA",has_sata),("NVMe",has_nvme)) if p]
    if len(ifaces)==1: out["interface"]=ifaces[0]
    # form factor (blank if multiple present -> ambiguous)
    ffs=[]
    if "2.5" in t: ffs.append("2.5\"")
    if "3.5" in t: ffs.append("3.5\"")
    if "m.2" in t or "m2 2280" in t: ffs.append("M.2")
    if "1.8" in t: ffs.append("1.8\"")
    if len(ffs)==1: out["form_factor"]=ffs[0]
    return out

def search_lookup(brand, model):
    """Query Brave, aggregate top results, return only fields the sources AGREE on. Never capacity."""
    key=_brave_key()
    if not key: return None,"NO_KEY"
    q=f"{brand} {model} SSD HDD interface form factor specifications"
    u="https://api.search.brave.com/res/v1/web/search?q="+urllib.parse.quote(q)+"&count=8"
    req=urllib.request.Request(u, headers={"X-Subscription-Token":key,
                                           "Accept":"application/json"})
    try:
        r=urllib.request.urlopen(req,timeout=15).read(); d=json.loads(r)
    except Exception as e:
        return None, type(e).__name__
    snippets=[]
    for res in d.get("web",{}).get("results",[])[:8]:
        snippets.append((res.get("title","")+" "+res.get("description","")))
    if not snippets: return None,"NO_RESULTS"
    # vote across snippets; only keep a field if all non-empty votes agree
    from collections import Counter
    votes={"type":Counter(),"interface":Counter(),"form_factor":Counter()}
    for s in snippets:
        for k,v in _scan_fields(s).items(): votes[k][v]+=1
    out={}
    for k,c in votes.items():
        if len(c)==1 and sum(c.values())>=2:   # unanimous AND seen at least twice
            out[k]=next(iter(c))
    return (out or None), "OK"

# ---------- main ----------
def merge(dst,src):
    for k,v in src.items():
        if v and not dst.get(k): dst[k]=v

CORE=("capacity","type","interface","form_factor")

# ── Self-building cross-ref cache key (Change 7) ──────────────────────────────
_PARTNO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{4,}")
_CAPTOK_RE = re.compile(r"^\d+(?:\.\d+)?(?:TB|GB)$", re.I)

def _looks_partno(tok):
    return (any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok)
            and not _CAPTOK_RE.match(tok))

def _search_key(brand, model, mpns):
    """Stable key for the search/cross-ref cache. Prefer the decoded MPN; else
    the longest part-number-looking token in the model — so 'PA33N3T8' and
    'PA33N3T8 3.84TB' share one entry instead of each calling Brave."""
    if mpns:
        return mpns[0][1].upper().replace(" ", "")
    cands = [t for t in _PARTNO_RE.findall(model or "") if _looks_partno(t)]
    if cands:
        return max(cands, key=len).upper()
    return f"{brand} {model}".strip().upper()

def _search_exact_capacity(mpn):
    """Change-2 narrow exception: Brave MAY set capacity ONLY when the exact MPN
    string appears with a single consistent capacity across >=2 results.
    Low-confidence; never from a family/series match."""
    key=_brave_key()
    if not key or not mpn: return ""
    q=f'"{mpn}" capacity specifications'
    u="https://api.search.brave.com/res/v1/web/search?q="+urllib.parse.quote(q)+"&count=8"
    req=urllib.request.Request(u, headers={"X-Subscription-Token":key,"Accept":"application/json"})
    try:
        d=json.loads(urllib.request.urlopen(req,timeout=15).read())
    except Exception:
        return ""
    from collections import Counter
    caps=Counter(); mpn_u=mpn.upper()
    for res in d.get("web",{}).get("results",[])[:8]:
        text=(res.get("title","")+" "+res.get("description",""))
        if mpn_u not in text.upper(): continue   # EXACT MPN must be present
        c=capacity_from_text(text)
        if c: caps[c]+=1
    if len(caps)==1:
        cap,n=next(iter(caps.items()))
        if n>=2: return cap
    return ""


def enrich_row(brand, model, known=None):
    """Decoder-first spec resolution from Brand + Model. Fills only missing
    fields; `known` (contract keys) always wins on conflict (flagged, not
    corrected). Returns: capacity, drive_type, interface, form_factor, speed,
    _mpn, _source, _confidence, _flags."""
    brand=(brand or "").strip(); model=(model or "").strip()
    blob=f"{brand} {model}"
    cache=load_cache()
    res={k:"" for k in CORE}; res["speed"]=""
    sources=[]; flags=[]

    text_cap=capacity_from_text(blob)
    if text_cap: res["capacity"]=text_cap; sources.append("text:cap")
    if looks_ssd(blob) and not res["type"]: res["type"]="SSD"; sources.append("text:ssd")

    mpns=extract_mpns(brand,model); used_mpn=""; dec_cap=""
    for vguess,mpn in mpns:
        ckey=f"{vguess}:{mpn.upper()}"
        if ckey in cache: d=cache[ckey]; sources.append("cache")
        else:
            dec=DECODERS.get(vguess); d=dec(mpn) if dec else {}
            if d: cache[ckey]=d; sources.append(f"decode:{vguess}")
        if d:
            used_mpn=used_mpn or mpn
            if d.get("capacity"): dec_cap=dec_cap or d["capacity"]
            merge(res,d)
        if all(res[k] for k in CORE): break
    if text_cap and dec_cap and text_cap!=dec_cap:
        flags.append(f"CAP_CONFLICT(text={text_cap}/dec={dec_cap})")

    # OEM-relabeled / nonstandard SKU (no decoder match) → flag for review, don't guess.
    if not mpns and any(_looks_partno(t) for t in _PARTNO_RE.findall(model)):
        flags.append("NONSTANDARD_MPN")

    if _icecat_token() and [k for k in CORE if not res[k]] and mpns:
        vguess,mpn=mpns[0]; ckey=f"ice:{vguess}:{mpn.upper()}"
        if ckey in cache: merge(res,cache[ckey]); sources.append("cache")
        else:
            ice,_=icecat_lookup(vguess,mpn)
            if ice: merge(res,ice); cache[ckey]=ice; sources.append("icecat")

    # Search tier (type/interface/form only) — SKU-keyed, TTL'd, guardrailed.
    if not all(res[k] for k in ("type","interface","form_factor")):
        skey="xref:"+_search_key(brand,model,mpns)
        entry=cache.get(skey)
        if entry and _fresh(entry, entry.get("ttl_days",60)):
            merge(res, entry.get("fields",{})); sources.append("cache")
        else:
            sr,_=search_lookup(brand,model)
            if sr:
                sr.pop("capacity",None)               # general rule: search never sets capacity
                merge(res,sr); sources.append("search")
                cache[skey]={"fields":sr,"cached_at":_now(),"ttl_days":60}  # confident (unanimous)
            else:
                cache[skey]={"fields":{},"cached_at":_now(),"ttl_days":7}   # miss: re-verify soon

    # Narrow capacity exception (low-confidence; exact-MPN only).
    if not res["capacity"] and used_mpn:
        xkey="xcap:"+used_mpn.upper()
        entry=cache.get(xkey)
        if entry and _fresh(entry, entry.get("ttl_days",7)):
            if entry.get("capacity"): res["capacity"]=entry["capacity"]; sources.append("cache"); flags.append("CAP_FROM_SEARCH_LOWCONF")
        else:
            cap=_search_exact_capacity(used_mpn)
            cache[xkey]={"capacity":cap,"cached_at":_now(),"ttl_days":7}
            if cap: res["capacity"]=cap; sources.append("search:cap(low)"); flags.append("CAP_FROM_SEARCH_LOWCONF")

    save_cache(cache)

    out={"capacity":res["capacity"],"drive_type":res["type"],"interface":res["interface"],
         "form_factor":res["form_factor"],"speed":res["speed"],
         "_mpn":used_mpn,"_source":";".join(sources) or "none"}

    # Fold `known` LAST: fill blanks, keep existing values, flag disagreements.
    if known:
        for f in ("capacity","drive_type","interface","form_factor","speed"):
            kv=known.get(f)
            if not kv: continue
            cur=out.get(f)
            if cur and str(cur)!=str(kv):
                flags.append(f"KNOWN_CONFLICT({f}:known={kv}/dec={cur})")
            out[f]=kv  # uploaded value wins

    filled=sum(1 for k in ("capacity","drive_type","interface","form_factor") if out[k])
    out["_confidence"]="HIGH" if filled==4 else("MED" if filled>=2 else("LOW" if filled==1 else "NONE"))
    out["_flags"]=";".join(flags)
    return out


def capacity_audit(rows):
    """Count rows per capacity bucket; flag impossible enterprise-drive values.
    Used as a regression guard after any decoder change (catches greedy-match
    phantom capacities like 5TB/9TB from an ST9 prefix)."""
    from collections import Counter
    dist=Counter()
    impossible=[]
    for r in rows:
        cap=(r.get("capacity") or r.get("Capacity") or "").strip()
        dist[cap]+=1
        m=re.match(r"(\d+(?:\.\d+)?)\s*TB", cap, re.I)
        if m and float(m.group(1))>=5:        # >=5TB on a 2.5"/legacy drive is suspect
            impossible.append(cap)
    return {"distribution": dict(dist), "impossible": impossible}


def main(inp,outp):
    cache=load_cache(); rows=list(csv.DictReader(open(inp)))
    stats={"decoder":0,"icecat":0,"text_only":0}
    out_rows=[]
    for r in rows:
        brand=(r.get("Brand") or "").strip(); model=(r.get("Model") or "").strip()
        blob=f"{brand} {model}"
        res={k:"" for k in CORE}; res["speed"]=""
        sources=[]; flags=[]
        text_cap=capacity_from_text(blob)
        if text_cap: res["capacity"]=text_cap; sources.append("text:cap")
        if looks_ssd(blob) and not res["type"]: res["type"]="SSD"; sources.append("text:ssd")
        mpns=extract_mpns(brand,model); used_mpn=""; dec_cap=""
        for vguess,mpn in mpns:
            ckey=f"{vguess}:{mpn.upper()}"
            if ckey in cache: d=cache[ckey]; sources.append("cache")
            else:
                dec=DECODERS.get(vguess); d=dec(mpn) if dec else {}
                if d: cache[ckey]=d; sources.append(f"decode:{vguess}")
            if d:
                used_mpn=used_mpn or mpn
                if d.get("capacity"): dec_cap=dec_cap or d["capacity"]
                merge(res,d)
            if all(res[k] for k in CORE): break
        # contradiction check
        if text_cap and dec_cap and text_cap!=dec_cap:
            flags.append(f"CAP_CONFLICT(text={text_cap}/dec={dec_cap})")
        # ICEcat on gaps
        if [k for k in CORE if not res[k]] and mpns:
            vguess,mpn=mpns[0]; ckey=f"ice:{vguess}:{mpn.upper()}"
            if ckey in cache: merge(res,cache[ckey]); sources.append("cache")
            else:
                ice,code=icecat_lookup(vguess,mpn)
                if ice: merge(res,ice); cache[ckey]=ice; sources.append("icecat")
                time.sleep(0.08)
        # search tier: only for rows still missing type/interface/form (never capacity)
        if not all(res[k] for k in ("type","interface","form_factor")):
            skey="search:"+blob.upper()
            if skey in cache:
                merge(res,cache[skey]); sources.append("cache")
            else:
                sr,scode=search_lookup(brand,model)
                if sr:
                    # guard: search NEVER writes capacity
                    sr.pop("capacity",None)
                    merge(res,sr); cache[skey]=sr; sources.append("search")
                    time.sleep(0.1)
        core=[res[k] for k in CORE]
        if "icecat" in sources: stats["icecat"]+=1
        elif any(s.startswith("decode") for s in sources): stats["decoder"]+=1
        elif sources and all(s.startswith("text") for s in sources): stats["text_only"]+=1
        filled=sum(1 for c in core if c)
        conf="HIGH" if filled==4 else("MED" if filled>=2 else("LOW" if filled==1 else "NONE"))
        out_rows.append({**r,"Capacity":res["capacity"],"Drive Type":res["type"],
            "Interface":res["interface"],"Form Factor":res["form_factor"],
            "Speed":res["speed"],"_mpn":used_mpn,"_source":";".join(sources) or "none",
            "_confidence":conf,"_flags":";".join(flags)})
    cols=list(rows[0].keys())
    for c in ["Speed","_mpn","_source","_confidence","_flags"]:
        if c not in cols: cols.append(c)
    with open(outp,"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for r in out_rows: w.writerow(r)
    save_cache(cache)
    n=len(rows)
    g=lambda c:sum(1 for r in out_rows if r["_confidence"]==c)
    print(f"rows={n}")
    print(f"  HIGH={g('HIGH')}  MED={g('MED')}  LOW={g('LOW')}  NONE={g('NONE')}")
    print(f"  any-data resolved={n-g('NONE')} ({100*(n-g('NONE'))//n}%)")
    print(f"  primary source: decoder={stats['decoder']} icecat={stats['icecat']} text-only={stats['text_only']}")
    cf=[r for r in out_rows if r["_flags"]]
    print(f"  contradiction flags={len(cf)}")
    for r in cf[:12]: print(f"    ! {r['Brand']} {r['Model'][:40]} -> {r['_flags']}")

if __name__=="__main__": main(sys.argv[1],sys.argv[2])
