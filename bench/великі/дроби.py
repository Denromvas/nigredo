from decimal import Decimal   # точні дроби, як у Nigredo (float дав би інші копійки)

PDV = Decimal('0.2')


def krok(a, i):
    return a + PDV * (i % 7)


s = Decimal(0)
for i in range(1, 200001):
    s = krok(s, i)
print(round(s, 2))
