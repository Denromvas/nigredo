import json, sys, urllib.request
r = urllib.request.Request(f'http://127.0.0.1:{sys.argv[1]}/report', method='POST',
                           data=json.dumps({'сума': 42, 'валюта': 'грн'}).encode(),
                           headers={'Content-Type': 'application/json'})
v = json.load(urllib.request.urlopen(r))
print(f'прийнято №{v["№"]}, сума {v["отримано"]}')
