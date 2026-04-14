import re
with open('driver_tool.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(r"\`/f\`".replace('`', "'"), r"'/f'")

# Also fix any remaining '/' that was not replaced due to spacing? Wait, earlier they were '/'
text = re.sub(r"'\/'", r"'/f'", text)

# Now fix the ones that got messed up with \' /f \'
text = text.replace("\\'/f\\'", "'/f'")

with open('driver_tool.py', 'w', encoding='utf-8') as f:
    f.write(text)
