import io

with io.open('driver_tool.py', 'r', encoding='utf-8') as f:
    text = f.read()

replacements = {
    'Ăˇ': 'á', 'Ă©': 'é', 'Ă­': 'í', 'Ăł': 'ó', 'Ă¶': 'ö', 'Ĺ‘': 'ő', 
    'Ăş': 'ú', 'ĂĽ': 'ü', 'Ĺ±': 'ű', 'ĂŤ': 'Í', 'Ă“': 'Ó', 'Ă–': 'Ö', 
    'Ĺ\x90': 'Ő', 'Ăš': 'Ú', 'Ăś': 'Ü', 'Ĺ°': 'Ű', 'Ă\xad': 'í', 'Ă\xbc': 'ü',
    'tĂ¶r': 'tör', 'Ă\xA1': 'á', 'Ă\xA9': 'é', 'Ă\xB3': 'ó', 'Ă\xB6': 'ö', 
    'Ĺ\x91': 'ő', 'Ă\xBA': 'ú', 'Ă\xBC': 'ü', 'Ĺ\xB1': 'ű', 'Ă\xAD': 'í',
    'Ă\x81': 'Á', 'Ă‰': 'É', 'Ă“': 'Ó', 'Ă–': 'Ö', 'Ĺ\x90': 'Ő', 'Ăš': 'Ú', 
    'Ăś': 'Ü', 'Ĺ°': 'Ű', 'Ă\x8D': 'Í', 'bg="#4CAF50"': 'bg="#0078D7"',
    'bg="#f0f0f0"': 'bg="#FFFFFF"', 'bg="#e0e0e0"': 'bg="#F3F3F3"',
    'relief=tk.RAISED': 'relief="flat", bd=0, activebackground="#E5F3FF"',
    'relief=tk.SUNKEN': 'relief="flat", bd=0, activebackground="#005A9E"',
    'relief=tk.SUNKEN, bg="#4CAF50"': 'relief="flat", bg="#0078D7", activebackground="#005A9E"',
    'font=("Segoe UI", 11, "bold")': 'font=("Segoe UI", 11)',
    'font=("Segoe UI", 10, "bold")': 'font=("Segoe UI", 10)',
    'font=("Segoe UI", 9, "bold")': 'font=("Segoe UI", 9)',
}

for k, v in replacements.items():
    text = text.replace(k, v)

text = text.replace('Ăllapot', 'Állapot')
text = text.replace('Ăšj', 'Új')
text = text.replace('Ă–sszes', 'Összes')
text = text.replace('Ă‰LĹT', 'ÉLŐT')

text = text.replace('style.theme_use("xpnative") # Or xpnative/clam/vista', 'style.theme_use("clam")\n            style.configure(".", background="#FFFFFF")\n            style.configure("TFrame", background="#FFFFFF")\n            style.configure("TLabel", background="#FFFFFF")\n            style.configure("TButton", background="#0078D7", foreground="white")')

with io.open('driver_tool.py', 'w', encoding='utf-8') as f:
    f.write(text)
