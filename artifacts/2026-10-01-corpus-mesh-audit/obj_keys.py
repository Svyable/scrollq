"""Every *_original.obj under <scroll>/segments/<segment>/mesh/intermediate/ in the pinned bucket index."""
import gzip, json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
idx = os.path.join(HERE, "..", "2026-10-01-bucket-index", "metadata.min.json.gz")
s = json.dumps(json.load(gzip.open(idx)))
pat = r'"([^"/][^"]*/segments/[^"/]+/mesh/intermediate/[^"/]+_original\.obj)"'
for k in sorted(set(re.findall(pat, s))):
    print(k)
