"""List primary TIFXYZ mesh dirs (<scroll>/segments/<seg>/mesh/<name>.tifxyz/) with delimiter listings."""
import sys, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
B = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
def ls(prefix):
    out, tok = ([], []), None
    while True:
        q = {"list-type": "2", "prefix": prefix, "delimiter": "/"}
        if tok: q["continuation-token"] = tok
        for a in range(5):
            try:
                with urllib.request.urlopen(B + "/?" + urllib.parse.urlencode(q), timeout=60) as r:
                    root = ET.fromstring(r.read()); break
            except Exception as e:
                time.sleep(2 ** a)
        else:
            raise RuntimeError(f"listing failed: {prefix}")
        out[0].extend(p.text for p in root.iter(NS + "Prefix") if p.text and p.text != prefix)
        out[1].extend(k.text for k in root.iter(NS + "Key"))
        t = root.find(NS + "NextContinuationToken")
        if t is None: return out
        tok = t.text
scrolls = [p for p in ls("")[0] if not p.startswith("_")]
for s in scrolls:
    segs = ls(s + "segments/")[0]
    print(f"# {s} {len(segs)} segments", file=sys.stderr, flush=True)
    for seg in segs:
        dirs, _ = ls(seg + "mesh/")
        for d in dirs:
            if d.rstrip("/").endswith(".tifxyz"):
                print(d, flush=True)
