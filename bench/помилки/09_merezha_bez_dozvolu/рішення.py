import urllib.request
print(urllib.request.urlopen('http://example.com').read()[:10])
