import sqlite3
db = sqlite3.connect('file:дані/склад.db?mode=ro', uri=True)
rows = db.execute('''SELECT т.назва, COALESCE(SUM(CASE р.тип WHEN 'прихід' THEN р.кількість ELSE -р.кількість END), 0)
                     FROM товари т LEFT JOIN рухи р ON р.товар_id = т.id GROUP BY т.id''').fetchall()
for n, b in sorted((r for r in rows if r[1] < 0), key=lambda r: (r[1], r[0])):
    print(f'{n}: {b}')
print('Нульових:', sum(1 for r in rows if r[1] == 0))
