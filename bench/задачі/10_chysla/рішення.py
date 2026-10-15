import math
a, b = 0, 1
for _ in range(90):
    a, b = b, a + b
print(a)
print(math.factorial(30))
