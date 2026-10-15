from decimal import Decimal, ROUND_HALF_UP
s = sum([Decimal('0.1'), Decimal('0.2'), Decimal('19.99')])
k = Decimal('0.01')
print('без ПДВ:', s.quantize(k))
print('з ПДВ:', (s * Decimal('1.2')).quantize(k, ROUND_HALF_UP))
