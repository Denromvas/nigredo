import re
print(re.findall(r'(a+)+$', 'a' * 40 + '!'))
