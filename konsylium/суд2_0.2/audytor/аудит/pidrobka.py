"""Аудит: підробити слід Nigredo так, щоб `ngr --перевірити-слід` сказав «✓».
Ланцюжок хешів без ключа — його може перерахувати будь-хто."""
import hashlib, json, sys

src, dst = sys.argv[1], sys.argv[2]
lines = open(src, encoding='utf-8').readlines()
if len(sys.argv) > 3:                      # режим «обрізати»: лишити перші N записів як є
    open(dst, 'w', encoding='utf-8').writelines(lines[:int(sys.argv[3])])
    sys.exit()
recs = [json.loads(l) for l in lines]
# залишити лише «чисті» події: викинути все про інструменти й делегування
keep = [r for r in recs if r['подія'] not in ('інструмент', 'делегування', 'субагент повернув')]
prev, out = '0' * 16, []
for i, r in enumerate(keep, 1):
    r.pop('хеш', None)
    r['№'], r['попередній'] = i, prev
    if r['подія'] == 'печатка':
        r['намір'], r['дозволи'] = 'лише порахувати', {}
    body = json.dumps(r, ensure_ascii=False, sort_keys=True)
    r['хеш'] = prev = hashlib.sha256(body.encode()).hexdigest()[:16]
    out.append(json.dumps(r, ensure_ascii=False))
open(dst, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
