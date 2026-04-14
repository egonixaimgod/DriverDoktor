
c = open("driver_tool.py", encoding="utf-8").read()
c = c.replace("f\"[SILENT EXCEPTION] {e}\"", "f\"SILENT EXCEPTION {e}\"")
c = c.replace("f\\\"[SILENT EXCEPTION] {e}\\\"", "f\"SILENT EXCEPTION {e}\"")
c = c.replace("f\\\\\"[SILENT EXCEPTION] {e}\\\\\"", "f\"SILENT EXCEPTION {e}\"")
open("driver_tool.py", "w", encoding="utf-8").write(c)

