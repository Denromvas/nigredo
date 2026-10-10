import hashlib, sys
for p in sys.argv[1:]:
    print(hashlib.sha256(open(p, 'rb').read()).hexdigest(), p)
