from ngrpy import *
seal("FizzBuzz", [])

for n in range(1, 16):
    print("FizzBuzz" if n % 15 == 0 else "Fizz" if n % 3 == 0 else "Buzz" if n % 5 == 0 else n)
