with open('driver_tool.py', 'r', encoding='utf-8') as f:
    text = f.read()

js_logger = """
    def js_log(self, level, msg):
        # UI-bol jovo nyers JavaScript logok kozvetitess
        level = str(level).upper()
        if level == 'ERROR': log_lvl = logging.ERROR
        elif level == 'WARN' or level == 'WARNING': log_lvl = logging.WARNING
        elif level == 'DEBUG': log_lvl = logging.DEBUG
        else: log_lvl = logging.INFO
        logging.log(log_lvl, f"[JS_UI] {msg}")

    def get_init_data(self):"""

text = text.replace('    def get_init_data(self):', js_logger)

with open('driver_tool.py', 'w', encoding='utf-8') as f:
    f.write(text)
