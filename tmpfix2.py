with open('driver_tool.py', 'r', encoding='utf-8') as f:
    lines = f.read().split('\n')

for i, l in enumerate(lines):
    if 'status = api.check_wu_status()' in l:
        if 'print("""' in lines[i+1]:
            lines[i+1] = lines[i+1].replace('print("""', 'print(f"""')

with open('driver_tool.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
