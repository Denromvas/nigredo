"""Підробка сліду: змінити записи й перерахувати ланцюжок хешів тим самим алгоритмом, що й ngr.
Використання: python3 -I підробити_слід.py вхід.jsonl вихід.jsonl"""
import hashlib, json, sys

src, dst = sys.argv[1], sys.argv[2]
recs = [json.loads(l) for l in open(src, encoding='utf-8') if l.strip()]
for r in recs:
    r.pop('хеш', None)
    if r.get('подія') == 'вивід':
        r['текст'] = '5'                      # «надрукувало 5», хоча було 2
    if r.get('подія') == 'відсів':
        r['рішення'] = 'лишено'               # «все лишено»
prev = '0000000000000000'
with open(dst, 'w', encoding='utf-8') as out:
    for r in recs:
        r['попередній'] = prev
        body = json.dumps(r, ensure_ascii=False, sort_keys=True)
        prev = hashlib.sha256(body.encode()).hexdigest()[:16]
        r['хеш'] = prev
        out.write(json.dumps(r, ensure_ascii=False) + '\n')
