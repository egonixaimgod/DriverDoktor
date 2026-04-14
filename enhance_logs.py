import re

with open('driver_tool.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update DriverToolApi._run() to log FULL stdout and stderr (truncated to 4000 chars instead of hard 500 drop)
driver_tool_run_old = """            if result.returncode != 0:
                logging.warning(f"[CMD] Visszatérési kód: {result.returncode} ({elapsed:.1f}s)")
                if result.stderr:
                    logging.warning(f"[CMD] stderr: {result.stderr[:500]}")
            else:
                logging.debug(f"[CMD] OK ({elapsed:.1f}s)")
            # Log stdout ha van és rövid
            if result.stdout and len(result.stdout) < 500:
                logging.debug(f"[CMD] stdout: {result.stdout.strip()[:300]}")
            return result"""

driver_tool_run_new = """            if result.returncode != 0:
                logging.warning(f"[CMD] Visszatérési kód: {result.returncode} ({elapsed:.1f}s)")
                if result.stderr:
                    logging.warning(f"[CMD] stderr: {result.stderr[:4000]}")
            else:
                logging.debug(f"[CMD] OK ({elapsed:.1f}s)")
            
            # Log teljes kimenet 4000 karakterig
            if result.stdout:
                out_txt = result.stdout.strip()
                if len(out_txt) > 4000: out_txt = out_txt[:4000] + '... [TRUNCATED]'
                logging.debug(f"[CMD] stdout: {out_txt}")
            return result"""

content = content.replace(driver_tool_run_old, driver_tool_run_new)


# 2. Update CliApi._run() to log absolutely everything!
cli_run_old = """    def _run(self, cmd, **kwargs):
        \"\"\"Parancs futtatás (GUI verzióból).\"\"\"
        try:
            return subprocess.run(cmd, capture_output=True, text=True, errors='replace',
                                  startupinfo=self._si, creationflags=self._nw, **kwargs)
        except Exception as e:
            class DummyRes:
                returncode = 1
                stdout = ""
                stderr = str(e)
            return DummyRes()"""

cli_run_new = """    def _run(self, cmd, **kwargs):
        \"\"\"Parancs futtatás (CLI verzió).\"\"\"
        cmd_str = cmd if isinstance(cmd, str) else ' '.join(str(c) for c in cmd)
        logging.debug(f"[CMD_CLI] Futtatás: {cmd_str[:300]}")
        start = time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, errors='replace',
                                  startupinfo=self._si, creationflags=self._nw, **kwargs)
            elapsed = time.time() - start
            if result.returncode != 0:
                logging.warning(f"[CMD_CLI] Visszatérési kód: {result.returncode} ({elapsed:.1f}s)")
                if result.stderr:
                    logging.warning(f"[CMD_CLI] stderr: {result.stderr[:4000]}")
            else:
                logging.debug(f"[CMD_CLI] OK ({elapsed:.1f}s)")
            
            if result.stdout:
                out_txt = result.stdout.strip()
                if len(out_txt) > 4000: out_txt = out_txt[:4000] + '... [TRUNCATED]'
                logging.debug(f"[CMD_CLI] stdout: {out_txt}")
            return result
        except Exception as e:
            logging.error(f"[CMD_CLI] Kivétel: {e}")
            class DummyRes:
                returncode = 1
                stdout = ""
                stderr = str(e)
            return DummyRes()"""

content = content.replace(cli_run_old, cli_run_new)

with open('driver_tool.py', 'w', encoding='utf-8') as f:
    f.write(content)
