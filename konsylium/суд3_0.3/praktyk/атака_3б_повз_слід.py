from ngrpy import *
import sys
seal("дія повз слід", ["файл.читати:дані"])
# tool/print фіксуються у сліді. А прямий запис у stdout — ні.
sys.stdout.write("це НЕ потрапить у слід як 'вивід'\n")
sys.stderr.write("і це теж повз слід\n")
