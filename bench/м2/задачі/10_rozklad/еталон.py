from datetime import date, timedelta
d = date(2026, 10, 1)
while d <= date(2026, 12, 31):
    if d.isoformat() not in ('2026-11-12', '2026-12-24'): print(d)
    d += timedelta(days=14)
