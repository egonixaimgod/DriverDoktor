import os

with open('driver_tool.py', 'r', encoding='utf-8') as f:
    text = f.read()

idx_init = text.find('    def __init__(self):')
idx_offline = text.find('    def get_offline_drivers(self, all_drivers=False):')
idx_wu = text.find('    def check_wu_status(self):')
idx_rp = text.find('    def create_restore_point(self):')

part1_str = part1
part2_str = part2

if idx_init != -1 and idx_offline != -1:
    text = text[:idx_init] + part1_str + '\n' + text[idx_offline:]

idx_wu = text.find('    def check_wu_status(self):')
idx_rp = text.find('    def create_restore_point(self):')

if idx_wu != -1 and idx_rp != -1:
    text = text[:idx_wu] + part2_str + '\n' + text[idx_rp:]

with open('driver_tool.py', 'w', encoding='utf-8') as f:
    f.write(text)
