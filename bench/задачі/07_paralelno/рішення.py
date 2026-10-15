import sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
get = lambda n: urllib.request.urlopen(f'http://127.0.0.1:{sys.argv[1]}/slow/{n}').read().decode()
with ThreadPoolExecutor(5) as ex:
    for r in ex.map(get, range(1, 6)):
        print(r)
