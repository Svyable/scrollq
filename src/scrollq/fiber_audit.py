"""Fiber trace continuity diagnostics."""
from __future__ import annotations
import argparse, csv, hashlib, json
from pathlib import Path
import numpy as np

def audit_rows(rows, gap_factor=4.0, turn_degrees=60.0):
    traces, errors = {}, []
    for i, row in enumerate(rows, 2):
        try:
            p = [float(row[k]) for k in ("x","y","z")]
            if not np.all(np.isfinite(p)): raise ValueError("non-finite coordinate")
            traces.setdefault(str(row["trace_id"]), []).append(p)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({"row": i, "error": str(exc)})
    findings=[]; total=0.0; gaps=turns=0; steps=[]
    for tid, raw in traces.items():
        pts=np.asarray(raw,float)
        if len(pts)<2:
            findings.append({"trace_id":tid,"kind":"short_trace","points":len(pts)}); continue
        vec=np.diff(pts,axis=0); seg=np.linalg.norm(vec,axis=1); steps.extend(seg.tolist()); total+=float(seg.sum())
        pos=seg[seg>0]; baseline=float(np.median(pos)) if pos.size else 0.0
        if baseline:
            for j in np.flatnonzero(seg > gap_factor*baseline):
                gaps+=1; findings.append({"trace_id":tid,"kind":"gap","segment":int(j),"ratio":float(seg[j]/baseline)})
        if len(vec)>=2:
            a,b=vec[:-1],vec[1:]; den=np.linalg.norm(a,axis=1)*np.linalg.norm(b,axis=1); valid=den>0
            angles=np.zeros(len(den)); angles[valid]=np.degrees(np.arccos(np.clip(np.sum(a[valid]*b[valid],axis=1)/den[valid],-1,1)))
            for j in np.flatnonzero(angles>turn_degrees):
                turns+=1; findings.append({"trace_id":tid,"kind":"sharp_turn","vertex":int(j+1),"degrees":float(angles[j])})
    status="fail" if errors else ("caution" if findings else "pass")
    return {"diagnostic":"fiber-trace-audit","schema_version":1,"status":status,
      "counts":{"rows":len(rows),"valid_traces":len(traces),"parse_errors":len(errors),"gaps":gaps,"sharp_turns":turns},
      "total_trace_length":total,"findings":findings,"errors":errors,
      "interpretation":"Flags discontinuities and abrupt direction changes in ordered fiber traces; it does not prove sheet identity."}

def audit_csv(path, **kwargs):
    path=Path(path)
    with path.open(newline="",encoding="utf-8") as fh: rows=list(csv.DictReader(fh))
    out=audit_rows(rows,**kwargs); out["input"]={"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}; return out

def main():
    ap=argparse.ArgumentParser(description="Audit ordered CSV fiber traces (trace_id,x,y,z).")
    ap.add_argument("csv"); ap.add_argument("--gap-factor",type=float,default=4.0); ap.add_argument("--turn-degrees",type=float,default=60.0); ap.add_argument("--out")
    a=ap.parse_args(); result=audit_csv(a.csv,gap_factor=a.gap_factor,turn_degrees=a.turn_degrees); s=json.dumps(result,indent=2)
    Path(a.out).write_text(s+"\n",encoding="utf-8") if a.out else print(s)
    raise SystemExit(2 if result["status"]=="fail" else 0)
