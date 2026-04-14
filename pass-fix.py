import re

f = 'driver_tool.py'
with open(f, encoding='utf-8') as file:
    content = file.read()

# Replace general exception pass
content = re.sub(r'except Exception:\s+pass', r'except Exception as e:\n            import logging\n            logging.debug(f\"[SILENT EXCEPTION] {e}\")', content)

# Check and fix open( missing encoding
content = re.sub(r'open\(([^,]+?),\s*([\'\"][wrba+]+[\'\"])\)', r'open(\1, \2, encoding=\"utf-8\")', content)
content = re.sub(r'open\(([^,]+?),\s*([\'\"][wrba]b[\'\"]),\s*encoding=[\'\"]utf-8[\'\"]\)', r'open(\1, \2)', content)

# Fix open CONOUT without encoding issues (remove encoding for them)
content = re.sub(r'open\([\'\"]CONIN\$[\'\"], [^\)]+\)', r'open(\"CONIN$\", \"r\")', content)
content = re.sub(r'open\([\'\"]CONOUT\$[\'\"], [^\)]+\)', r'open(\"CONOUT$\", \"w\")', content)

# Write back
with open(f, 'w', encoding='utf-8') as file:
    file.write(content)
