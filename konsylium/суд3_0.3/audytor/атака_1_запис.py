from ngrpy import *
seal("лише читати дані", ["файл.читати:дані"])
# 1. через інструмент без дозволу:
try:
    tool("файл.писати", "звіти/зламано.txt", "я записав")
    print("ЗАПИС ЧЕРЕЗ TOOL ВДАВСЯ")
except Exception as e:
    print("tool блок:", type(e).__name__, e)
# 2. напряму повз інструмент:
try:
    open("звіти/зламано2.txt", "w").write("я записав напряму")
    print("ЗАПИС НАПРЯМУ ВДАВСЯ")
except Exception as e:
    print("open блок:", type(e).__name__, e)
