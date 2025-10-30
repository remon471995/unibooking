# fix_indent.py
import io, sys, py_compile

path = "core/views.py"

def normalize_file(p):
    with open(p, "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1256", errors="replace")
    # 1) استبدال التابات بـ 4 مسافات
    text = text.replace("\t", "    ")
    # 2) توحيد نهاية السطور لـ CRLF (Windows)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    with open(p, "wb") as f:
        f.write(text.encode("utf-8"))
    print("Done: tabs -> 4 spaces and normalized line endings in", p)

def py_syntax_check(p):
    try:
        py_compile.compile(p, doraise=True)
        print("Python syntax check: OK")
        return True
    except py_compile.PyCompileError as e:
        print("Python syntax error detected:")
        print(e.msg)
        return False

if __name__ == "__main__":
    print("Fixer started for core/views.py")
    try:
        normalize_file(path)
    except FileNotFoundError:
        print("ERROR: file not found:", path)
        sys.exit(2)
    ok = py_syntax_check(path)
    if not ok:
        print("There are still syntax/indentation errors. Open the file and inspect around the reported lines.")
    else:
        print("All good — try: python manage.py runserver")
