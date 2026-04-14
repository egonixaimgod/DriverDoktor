import re
f = "driver_tool.py"
c = open(f, encoding="utf-8").read()
c = c.replace(
    r'f\'/for={os.environ.get(\"SystemDrive\", \"C:\")}\', f\'/on={os.environ.get(\"SystemDrive\", \"C:\")}\'',
    "f'/for={os.environ.get(\"SystemDrive\", \"C:\")}', f'/on={os.environ.get(\"SystemDrive\", \"C:\")}'"
)
open(f, "w", encoding="utf-8").write(c)
