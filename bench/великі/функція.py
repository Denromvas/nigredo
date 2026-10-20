def krok(a, i):
    return a + (i * i + i) % 7


s = 0
for i in range(1, 200001):
    s = krok(s, i)
print(s)
