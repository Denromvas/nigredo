import hashlib, json, sys

path = sys.argv[1]
rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
r = rows[1]
want = r["хеш"]
body = {k: v for k, v in r.items() if k != "хеш"}
cands = {
    "dumps": json.dumps(body, ensure_ascii=False),
    "dumps_sort": json.dumps(body, ensure_ascii=False, sort_keys=True),
    "dumps_ascii": json.dumps(body),
    "dumps_ascii_sort": json.dumps(body, sort_keys=True),
    "dumps_compact": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    "dumps_compact_sort": json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
}
body2 = {k: v for k, v in body.items() if k != "попередній"}
for k in list(cands):
    pass
extra = {}
for name, s in cands.items():
    for pre in ["", r["попередній"]]:
        for algo in ["sha256", "sha1", "md5", "blake2b", "sha512"]:
            h = hashlib.new(algo, (pre + s).encode()).hexdigest()
            if h[:16] == want:
                print("ЗБІГ", name, algo, "з попереднім" if pre else "без")
print("шукали", want)
