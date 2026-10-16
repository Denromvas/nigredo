import sqlite3
for m, s in sqlite3.connect('дані/база.db').execute('SELECT місто, SUM(сума) s FROM продажі GROUP BY місто ORDER BY s DESC LIMIT 2'):
    print(f'{m}: {s}')
