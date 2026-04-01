import os

with open('fix.py', 'r', encoding='utf-8-sig') as f:
    code = f.read()

exec_env = {}
exec(code.split("import re")[0], exec_env)

part1 = exec_env['part1']
part2 = exec_env['part2']

with open('driver_tool.py', 'r', encoding='utf-8-sig') as f:
    text = f.read()

idx_init = text.find('    def __init__(self):')
idx_offline = text.find('    def get_offline_drivers(self, all_drivers=False):')

if idx_init != -1 and idx_offline != -1:
    text = text[:idx_init] + part1 + '\n    def get_offline_drivers(self, all_drivers=False):\n' + text[idx_offline+len('    def get_offline_drivers(self, all_drivers=False):'):]

idx_wu = text.find('    def check_wu_status(self):')
idx_rp = text.find('    def create_restore_point(self):')

if idx_wu != -1 and idx_rp != -1:
    text = text[:idx_wu] + part2 + '\n    def create_restore_point(self):\n' + text[idx_rp+len('    def create_restore_point(self):'):]

with open('driver_tool.py', 'w', encoding='utf-8') as f:
    f.write(text)
