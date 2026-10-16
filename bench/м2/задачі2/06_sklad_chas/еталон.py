import json
st = json.load(open('дані/початок.json', encoding='utf-8'))
first = {}
for e in json.load(open('дані/рух.json', encoding='utf-8')):
    st[e['товар']] = st.get(e['товар'], 0) + e['зміна']
    if st[e['товар']] < 0 and e['товар'] not in first:
        first[e['товар']] = e['час']
for t in sorted(first):
    print(f'{t}: {first[t]}')
if not first:
    print('усе гаразд')
