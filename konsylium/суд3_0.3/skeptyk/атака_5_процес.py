import subprocess
import ngrpy
from ngrpy import *
seal("нічого не робити", [])

# ціль 5: печатка порожня, а скрипт запускає довільний процес (нешкідливий: id -un).
try:
    subprocess.run(["id", "-un"])
except PermissionError as e:
    print("чесна спроба відхилена:", e)

ngrpy._ST['trusted'] += 1
out = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
ngrpy._ST['trusted'] -= 1
print("процес запущено, користувач:", out)
