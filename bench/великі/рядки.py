def krok(a, i):
    return a + len('док-' + str(i))


s = 0
for i in range(1, 200001):
    s = krok(s, i)
print(s)
