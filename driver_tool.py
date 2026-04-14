BUILD_NUMBER = 71

import os
import sys
import ctypes
import subprocess
import re
import threading
import time
import logging
import shutil
import json
import glob
import traceback
import winreg
import queue
from datetime import datetime

try:
    import webview
except ImportError:
    print("HIBA: pywebview nem található! Telepítsd: pip install pywebview")
    sys.exit(1)

# pywebview 6.x deprecation compat
try:
    _FOLDER_DIALOG = webview.FileDialog.FOLDER
    _OPEN_DIALOG = webview.FileDialog.OPEN
except AttributeError:
    _FOLDER_DIALOG = webview.FOLDER_DIALOG
    _OPEN_DIALOG = webview.OPEN_DIALOG

# WebView2 init state (watchdog)
_webview_ready = threading.Event()
_webview_error = threading.Event()

# WebView2 minimum verzió ellenőrzés (ICoreWebView2Environment10 interface min v109 kell)
MIN_WEBVIEW2_MAJOR = 109

def check_webview2_runtime():
    """
    Ellenőrzi, hogy a WebView2 Runtime telepítve van-e és megfelelő verzió-e.
    Visszatérési értékek:
        (True, verzió_string) - OK
        (False, hibaüzenet) - Hiba
    """
    version = None
    
    # 1. Önálló WebView2 Runtime telepítések (EdgeUpdate registry)
    edgeupdate_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    ]
    for hive, path in edgeupdate_paths:
        try:
            with winreg.OpenKey(hive, path) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
                if version and version != "0.0.0.0":
                    break
        except (FileNotFoundError, OSError):
            continue
    
    # 2. Edge beépített WebView2 (Windows 11 / Edge-be integrált)
    if not version:
        edge_webview_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeWebView\BLBeacon"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeWebView\BLBeacon"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeWebView\BLBeacon"),
        ]
        for hive, path in edge_webview_paths:
            try:
                with winreg.OpenKey(hive, path) as key:
                    version, _ = winreg.QueryValueEx(key, "version")
                    if version:
                        break
            except (FileNotFoundError, OSError):
                continue
    
    # 3. Edge böngésző verzió (fallback - ha WebView2 nincs külön regisztrálva)
    if not version:
        edge_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Edge\BLBeacon"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Edge\BLBeacon"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Edge\BLBeacon"),
        ]
        for hive, path in edge_paths:
            try:
                with winreg.OpenKey(hive, path) as key:
                    version, _ = winreg.QueryValueEx(key, "version")
                    if version:
                        break
            except (FileNotFoundError, OSError):
                continue
    
    # 4. Utolsó esély: GetAvailableCoreWebView2BrowserVersionString (ha van WebView2Loader.dll)
    if not version:
        try:
            import ctypes
            wv2_loader = ctypes.windll.LoadLibrary("WebView2Loader.dll")
            buf = ctypes.create_unicode_buffer(256)
            hr = wv2_loader.GetAvailableCoreWebView2BrowserVersionString(None, ctypes.byref(buf))
            if hr == 0 and buf.value:
                version = buf.value
        except Exception:
            pass
    
    if not version:
        return (False, "WebView2 Runtime nem található!\n\n"
                       "A program működéséhez telepíteni kell:\n"
                       "https://go.microsoft.com/fwlink/p/?LinkId=2124703\n\n"
                       "(Evergreen Bootstrapper)")
    
    # Verzió parsing: pl. "109.0.1518.61" -> 109
    try:
        major = int(version.split('.')[0])
    except (ValueError, IndexError):
        major = 0
    
    if major < MIN_WEBVIEW2_MAJOR:
        return (False, f"WebView2 Runtime túl régi! (v{version})\n\n"
                       f"Minimum v{MIN_WEBVIEW2_MAJOR}.x szükséges.\n\n"
                       "Frissítsd itt:\n"
                       "https://go.microsoft.com/fwlink/p/?LinkId=2124703")
    
    return (True, version)


def show_webview2_error(message):
    """MessageBox megjelenítése WebView2 hibáról, majd program kilépés."""
    try:
        import webbrowser
        MB_OK = 0x0
        MB_ICONERROR = 0x10
        MB_TOPMOST = 0x40000
        result = ctypes.windll.user32.MessageBoxW(
            None,
            message + "\n\nMegnyissam a letöltési oldalt?",
            "DriverDoktor - WebView2 hiba",
            0x4 | MB_ICONERROR | MB_TOPMOST  # MB_YESNO
        )
        if result == 6:  # IDYES
            webbrowser.open("https://go.microsoft.com/fwlink/p/?LinkId=2124703")
    except Exception:
        pass
    sys.exit(1)


# Suppress noisy PIL/Pillow debug logging
logging.getLogger('PIL').setLevel(logging.WARNING)
logging.getLogger('PIL.PngImagePlugin').setLevel(logging.WARNING)


# ================================================================
# PROGRESS ABLAK HTML (software rendering-hez)
# ================================================================
PROGRESS_HTML = '''<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<title>DriverDoktor - Progress</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg-primary:#0d1a14;--bg-secondary:#152820;
  --glass:rgba(20,60,40,0.45);--glass-border:rgba(50,255,120,0.35);
  --accent:#3dff6e;--accent2:#00ff88;--accent-glow:rgba(61,255,110,0.6);
  --green:#3dff6e;--red:#ff6b5b;--yellow:#ffe066;
  --text:rgba(255,255,255,1);--text2:rgba(220,255,230,0.9);--text3:rgba(180,220,195,0.7);
  --r:14px;--r-sm:8px;--t:0.25s ease;
  --font:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
  --mono:'Cascadia Code','Fira Code','Consolas',monospace;
}
html,body{height:100%;overflow:hidden;font-family:var(--font);color:var(--text);font-size:13px;line-height:1.5}
body{
  background:linear-gradient(145deg,#0a1510 0%,#0d1f18 25%,#102a1f 50%,#0d2218 75%,#0a1812 100%);
  display:flex;align-items:center;justify-content:center;padding:20px;
}
body::before{content:'';position:fixed;width:600px;height:600px;background:radial-gradient(circle,rgba(50,255,120,0.12) 0%,transparent 60%);top:-200px;right:-150px;pointer-events:none}
body::after{content:'';position:fixed;width:500px;height:500px;background:radial-gradient(circle,rgba(0,255,150,0.08) 0%,transparent 60%);bottom:-150px;left:-100px;pointer-events:none}
.modal-box{
  width:100%;max-width:700px;max-height:95vh;display:flex;flex-direction:column;
  background:rgba(15,35,28,0.98);backdrop-filter:blur(40px);
  border:2px solid rgba(50,255,120,0.35);border-radius:18px;
  box-shadow:0 30px 90px rgba(0,0,0,0.6),0 0 40px rgba(50,255,120,0.15);
  overflow:hidden;
}
.modal-header{padding:20px 24px;border-bottom:1px solid var(--glass-border);display:flex;align-items:center;gap:10px;background:rgba(20,50,38,0.5)}
.modal-header h3{flex:1;font-size:16px;font-weight:700}
.modal-phase{color:var(--accent);font-size:14px;font-weight:700}
.modal-body{padding:18px 24px;flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:14px}
.modal-counter{text-align:center;font-size:18px;font-weight:700;color:var(--green)}
.modal-status{color:var(--text2);font-size:14px;text-align:center}
.modal-time{color:var(--text3);font-size:12px;text-align:center;margin-top:4px}
.progress{height:10px;background:rgba(50,255,120,0.15);border-radius:5px;overflow:hidden;width:100%;border:1px solid rgba(50,255,120,0.2);margin:10px 0}
.progress-fill{height:100%;background:linear-gradient(90deg,#2dd45a,var(--green));border-radius:5px;transition:width 0.4s ease;box-shadow:0 0 12px var(--accent-glow);width:0%}
.progress-indeterminate .progress-fill{width:30%!important;animation:indeterminate 1.5s ease-in-out infinite}
@keyframes indeterminate{0%{margin-left:-30%}100%{margin-left:100%}}
.modal-log{
  flex:1;min-height:200px;max-height:400px;overflow-y:auto;
  background:rgba(5,15,12,0.8);border-radius:var(--r-sm);padding:14px;
  font-family:var(--mono);font-size:12px;color:var(--accent);line-height:1.8;
  white-space:pre-wrap;word-break:break-all;
  scrollbar-width:thin;scrollbar-color:rgba(50,255,120,0.3) transparent;
  border:1px solid rgba(50,255,120,0.2);
}
.modal-log::-webkit-scrollbar{width:6px}
.modal-log::-webkit-scrollbar-thumb{background:rgba(50,255,120,0.3);border-radius:3px}
.footer-info{
  padding:12px 24px;border-top:1px solid var(--glass-border);
  text-align:center;color:var(--text3);font-size:11px;
  background:rgba(20,50,38,0.3);
}
</style>
</head>
<body>
<div class="modal-box">
  <div class="modal-header">
    <h3 id="title">⚡ 1 Kattintásos Driver Fix</h3>
    <span class="modal-phase" id="phase"></span>
  </div>
  <div class="modal-body">
    <div class="modal-counter" id="counter">Inicializálás...</div>
    <div class="progress" id="progress-bar">
      <div class="progress-fill" id="progress-fill"></div>
    </div>
    <div class="modal-status" id="status">Várakozás...</div>
    <div class="modal-time" id="time"></div>
    <pre class="modal-log" id="log"></pre>
  </div>
  <div class="footer-info">
    🖥️ Ez az ablak software renderinggel fut - GPU driver változások nem befolyásolják
  </div>
</div>
<script>
let startTime = Date.now();
let timerInterval = setInterval(() => {
  const s = Math.floor((Date.now() - startTime) / 1000);
  const m = Math.floor(s / 60);
  document.getElementById('time').textContent = '⏱ ' + (m > 0 ? m + ':' + String(s%60).padStart(2,'0') : s + ' mp');
}, 1000);

function update(data) {
  if (data.title) document.getElementById('title').textContent = data.title;
  if (data.phase) document.getElementById('phase').textContent = data.phase;
  if (data.counter) document.getElementById('counter').textContent = data.counter;
  if (data.status) document.getElementById('status').textContent = data.status;
  if (data.log) {
    const el = document.getElementById('log');
    el.textContent += data.log + '\\n';
    el.scrollTop = el.scrollHeight;
  }
  if (data.indeterminate) {
    document.getElementById('progress-bar').classList.add('progress-indeterminate');
    document.getElementById('progress-fill').style.width = '30%';
  } else if (data.total && data.total > 0) {
    document.getElementById('progress-bar').classList.remove('progress-indeterminate');
    const pct = Math.min(100, (data.current || 0) / data.total * 100);
    document.getElementById('progress-fill').style.width = pct + '%';
  }
  if (data.complete) {
    clearInterval(timerInterval);
    const s = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(s / 60);
    document.getElementById('time').textContent = 'Teljes idő: ' + (m > 0 ? m + ' perc ' + (s%60) + ' mp' : s + ' mp');
    document.getElementById('progress-bar').classList.remove('progress-indeterminate');
    document.getElementById('progress-fill').style.width = '100%';
  }
}
window.update = update;
</script>
</body>
</html>'''


def run_progress_window(log_path):
    """Külön processben futtatandó progress ablak (software rendering)."""
    # Software rendering bekapcsolása MIELŐTT a webview betöltődne
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (
        '--disable-gpu '
        '--disable-gpu-compositing '
        '--disable-gpu-vsync '
        '--disable-accelerated-2d-canvas '
        '--disable-accelerated-video-decode '
        '--use-gl=swiftshader '
        '--disable-d3d11 '
        '--disable-features=D3D11,Vulkan '
        '--in-process-gpu '
    )
    
    class ProgressApi:
        def __init__(self):
            self._window = None
            self._log_path = log_path
            self._last_pos = 0
            self._running = True

        def set_window(self, window):
            self._window = window
            threading.Thread(target=self._watch_file, daemon=True).start()

        def _watch_file(self):
            while self._running:
                try:
                    if os.path.exists(self._log_path):
                        with open(self._log_path, 'r', encoding='utf-8') as f:
                            f.seek(self._last_pos)
                            new_content = f.read()
                            self._last_pos = f.tell()
                            if new_content.strip():
                                for line in new_content.strip().split('\n'):
                                    if line.startswith('{'):
                                        try:
                                            data = json.loads(line)
                                            if self._window:
                                                self._window.evaluate_js(f'window.update({json.dumps(data)})')
                                        except json.JSONDecodeError:
                                            pass
                except Exception:
                    pass
                time.sleep(0.1)

        def stop(self):
            self._running = False

    api = ProgressApi()
    window = webview.create_window(
        'DriverDoktor - Autofix Progress',
        html=PROGRESS_HTML,
        width=750,
        height=600,
        min_size=(600, 500),
        on_top=True,
    )
    
    def on_start():
        api.set_window(window)
    
    def on_closing():
        api.stop()
        return True
    
    window.events.closing += on_closing
    webview.start(func=on_start, debug=False)


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class DriverToolApi:
    def __init__(self):
        logging.info("[INIT] DriverToolApi inicializálás...")
        self._window = None
        self.target_os_path = None
        self.sys_drive = os.environ.get('SystemDrive', 'C:') + '\\'
        self.hw_updates_pool = []
        self._hw_installed_devs = []
        self._hw_scanning = False
        self._hw_loaded = False
        self.wu_api_mode = True
        self._cancel_flag = False  # Flag for cancelling long-running tasks
        self._si = subprocess.STARTUPINFO()
        self._si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self._nw = subprocess.CREATE_NO_WINDOW
        # Autofix külön progress ablak
        self._autofix_log_path = None
        self._autofix_log_file = None
        self._autofix_window_proc = None
        logging.info(f"[INIT] sys_drive={self.sys_drive}")
        logging.info("[INIT] DriverToolApi kész.")

    def set_window(self, window):
        global _webview_ready, _webview_error
        logging.info("[WINDOW] WebView ablak beállítása...")
        self._window = window
        # Wait for WebView2 DOM to be ready (max 12s, watchdog: 15s)
        dom_ready = False
        for i in range(120):  # 120 * 0.1s = 12s
            try:
                if self._window and self._window.evaluate_js('1+1') == 2:
                    logging.info(f"[WINDOW] WebView2 DOM kész ({i+1} próba után, {(i+1)*0.1:.1f}s)")
                    dom_ready = True
                    _webview_ready.set()
                    break
            except Exception as e:
                if i == 119:
                    logging.warning(f"[WINDOW] WebView2 DOM nem reagál: {e}")
            time.sleep(0.1)
        if not dom_ready:
            logging.error("[WINDOW] WebView2 init sikertelen, watchdog átveszi...")
            _webview_error.set()

    def emit(self, event, data=None):
        # Log minden emit event-et
        try:
            if isinstance(data, dict):
                log_msg = data.get('log') or data.get('status') or data.get('error') or data.get('phase')
                if log_msg:
                    logging.info(f"[EMIT:{event}] {str(log_msg).strip()}")
                else:
                    # Log egyéb data mezőket is
                    logging.debug(f"[EMIT:{event}] data={json.dumps(data, ensure_ascii=False, default=str)[:200]}")
            else:
                logging.debug(f"[EMIT:{event}] data={data}")
        except Exception as e:
            logging.warning(f"[EMIT] Logging hiba: {e}")

        # Autofix progress ablakba írás (ha fut)
        if self._autofix_log_file and event in ('task_start', 'task_progress', 'task_complete'):
            try:
                if isinstance(data, dict):
                    self._write_progress(data)
            except Exception:
                pass

        # Ablak cím frissítése autofix progress közben (backup megoldás ha a modal eltűnik)
        if self._window and event in ('task_start', 'task_progress', 'task_complete'):
            try:
                if event == 'task_start':
                    title = data.get('title', 'Folyamat...') if isinstance(data, dict) else 'Folyamat...'
                    self._window.set_title(f"DriverDoktor - {title}")
                elif event == 'task_progress' and isinstance(data, dict):
                    counter = data.get('counter', '')
                    status = data.get('status', '')
                    phase = data.get('phase', '')
                    if counter:
                        self._window.set_title(f"DriverDoktor - [{counter}] {status or phase}")
                    elif status:
                        self._window.set_title(f"DriverDoktor - {status}")
                elif event == 'task_complete':
                    self._window.set_title('DriverDoktor')
            except Exception:
                pass  # Ne akadjon el ha a title frissítés nem sikerül

        if self._window:
            payload = None
            try:
                payload = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
                self._window.evaluate_js(f'window.handlePyEvent({payload})')
            except Exception as e:
                if 'NoneType' in str(e) and payload:
                    logging.warning(f"[EMIT:{event}] Window None, újrapróbálás...")
                    time.sleep(0.5)
                    try:
                        self._window.evaluate_js(f'window.handlePyEvent({payload})')
                    except Exception as e2:
                        logging.error(f"[EMIT:{event}] Újrapróbálás sikertelen: {e2}")
                elif payload is None:
                    logging.error(f"[EMIT:{event}] JSON serializálási hiba: {e}")
                else:
                    logging.error(f"[EMIT:{event}] Hiba: {e}")

    def _run(self, cmd, **kwargs):
        # Log minden parancs futtatását
        cmd_str = cmd if isinstance(cmd, str) else ' '.join(str(c) for c in cmd)
        logging.debug(f"[CMD] Futtatás: {cmd_str[:300]}")
        start = time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, errors='replace',
                                  startupinfo=self._si, creationflags=self._nw, **kwargs)
            elapsed = time.time() - start
            # Log eredmény
            if result.returncode != 0:
                logging.warning(f"[CMD] Visszatérési kód: {result.returncode} ({elapsed:.1f}s)")
                if result.stderr:
                    logging.warning(f"[CMD] stderr: {result.stderr[:500]}")
            else:
                logging.debug(f"[CMD] OK ({elapsed:.1f}s)")
            # Log stdout ha van és rövid
            if result.stdout and len(result.stdout) < 500:
                logging.debug(f"[CMD] stdout: {result.stdout.strip()[:300]}")
            return result
        except Exception as e:
            logging.error(f"[CMD] Kivétel: {e}")
            raise

    def _safe_thread(self, task, target):
        def wrapper():
            logging.info(f"[THREAD:{task}] Háttérszál indul...")
            start_time = time.time()
            try:
                target()
                elapsed = time.time() - start_time
                logging.info(f"[THREAD:{task}] Befejezve ({elapsed:.1f}s)")
            except Exception as e:
                elapsed = time.time() - start_time
                logging.error(f"[THREAD:{task}] HIBA ({elapsed:.1f}s): {e}")
                logging.error(f"[THREAD:{task}] Traceback:\n{traceback.format_exc()}")
                self.emit('task_error', {'task': task, 'error': str(e)})
                self.emit('task_complete', {'task': task, 'status': f'❌ Hiba: {e}'})
        threading.Thread(target=wrapper, daemon=True).start()

    # ================================================================
    # GENERAL
    # ================================================================
    def get_init_data(self):
        logging.info(f"[API] get_init_data() hívás - build={BUILD_NUMBER}, target={self.target_os_path}")
        return {'build': BUILD_NUMBER, 'sys_drive': self.sys_drive, 'target_os': self.target_os_path}

    def cancel_task(self):
        """API hívás a hosszan tartó műveletek (pl. törlés) megszakítására."""
        logging.warning("[API] cancel_task() — Felhasználó megszakítást kért!")
        self._cancel_flag = True
        self.emit('toast', {'message': '⚠️ Megszakítás kérve...', 'type': 'warning'})
        return True

    def _check_cancel(self):
        """Ellenőrzi, hogy a felhasználó megszakította-e a műveletet."""
        if self._cancel_flag:
            logging.info("[CANCEL] Megszakítás flag aktiv!")
            return True
        return False

    def change_target_os(self):
        logging.info("[API] change_target_os() hívás")
        result = self._window.create_file_dialog(_FOLDER_DIALOG, allow_multiple=False)
        if result and len(result) > 0:
            d = os.path.abspath(result[0]).replace("/", "\\")
            has_win = os.path.exists(os.path.join(d, "Windows"))
            logging.info(f"[API] change_target_os: kiválasztva={d}, has_windows={has_win}")
            return {'path': d, 'has_windows': has_win}
        logging.info("[API] change_target_os: mégse")
        return None

    def apply_target_os(self, path):
        logging.info(f"[API] apply_target_os({path})")
        self.target_os_path = path
        return True

    def reset_target_os(self):
        logging.info("[API] reset_target_os() - visszatérés jelenlegi rendszerre")
        self.target_os_path = None
        return True

    def select_directory(self, title='Válassz mappát'):
        logging.info(f"[API] select_directory(title={title})")
        result = self._window.create_file_dialog(_FOLDER_DIALOG, allow_multiple=False)
        if result and len(result) > 0:
            logging.info(f"[API] select_directory: kiválasztva={result[0]}")
            return result[0]
        logging.info("[API] select_directory: mégse")
        return None

    def select_file(self, title='Válassz fájlt', file_types=''):
        logging.info(f"[API] select_file(title={title}, types={file_types})")
        ft = (file_types.split('|')[0],) if file_types else ()
        result = self._window.create_file_dialog(_OPEN_DIALOG, allow_multiple=False, file_types=ft)
        if result and len(result) > 0:
            logging.info(f"[API] select_file: kiválasztva={result[0]}")
            return result[0]
        logging.info("[API] select_file: mégse")
        return None

    # ================================================================
    # DRIVER LISTING
    # ================================================================
    def load_drivers(self, all_drivers=False):
        logging.info(f"[API] load_drivers(all_drivers={all_drivers})")
        def worker():
            self.emit('drivers_loading')
            start = time.time()
            try:
                if self.target_os_path:
                    logging.info(f"[DRIVERS] Offline mód: {self.target_os_path}")
                    drivers = self._get_offline_drivers(all_drivers)
                elif all_drivers:
                    logging.info("[DRIVERS] Összes driver lekérdezés (élő rendszer)")
                    drivers = self._get_all_drivers()
                else:
                    logging.info("[DRIVERS] Third-party driverek lekérdezés")
                    drivers = self._get_third_party_drivers()
                elapsed = time.time() - start
                logging.info(f"[DRIVERS] Betöltve: {len(drivers)} driver ({elapsed:.1f}s)")
                self.emit('drivers_loaded', {'drivers': drivers, 'elapsed': round(elapsed, 1)})
            except Exception as e:
                logging.error(f"[DRIVERS] Betöltési hiba: {e}")
                logging.error(traceback.format_exc())
                self.emit('drivers_loaded', {'drivers': [], 'elapsed': 0, 'error': str(e)})
        threading.Thread(target=worker, daemon=True).start()

    def _get_third_party_drivers(self):
        logging.debug("[DRIVERS] pnputil /enum-drivers futtatása...")
        res = self._run(['pnputil', '/enum-drivers'])
        drivers = []
        current = {}
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                if current and "published" in current:
                    drivers.append(current)
                    current = {}
                continue
            parts = line.split(":", 1)
            if len(parts) == 2:
                key, val = parts[0].strip(), parts[1].strip()
                if "Published Name" in key or "Közzétett név" in key:
                    current["published"] = val
                elif "Original Name" in key or "Eredeti név" in key:
                    current["original"] = val
                elif "Provider Name" in key or "Szolgáltató neve" in key:
                    current["provider"] = val
                elif "Class Name" in key or "Osztály neve" in key:
                    current["class"] = val
                elif "Driver Version" in key or "Illesztőprogram verziója" in key:
                    current["version"] = val
        if current and "published" in current:
            drivers.append(current)
        return drivers

    def _get_all_drivers(self):
        logging.debug("[DRIVERS] _get_all_drivers() indult")
        cmd = ['powershell', '-NoProfile', '-Command',
               '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-WindowsDriver -Online -All | Select-Object ProviderName, ClassName, Version, Driver, OriginalFileName | ConvertTo-Json -Depth 2 -WarningAction SilentlyContinue']
        res = self._run(cmd, encoding='utf-8')
        out = res.stdout.strip()
        if not out:
            logging.debug("[DRIVERS] _get_all_drivers: üres kimenet")
            return []
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        parsed_drivers = [{"published": d.get("Driver", ""), "original": d.get("OriginalFileName", ""),
                 "provider": d.get("ProviderName", ""), "class": d.get("ClassName", ""),
                 "version": d.get("Version", "")} for d in data]

        # Filter ghosts (force-deleted inbox drivers)
        valid_drivers = []
        rep = os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), "System32", "DriverStore", "FileRepository")
        for d in parsed_drivers:
            pub = d.get("published", "")
            if not pub:
                continue
            if pub.lower().startswith("oem"):
                valid_drivers.append(d)
                continue
            if glob.glob(os.path.join(rep, f"{pub}_*")):
                valid_drivers.append(d)

        logging.debug(f"[DRIVERS] _get_all_drivers: {len(valid_drivers)} valid driver")
        return valid_drivers

    def _get_offline_drivers(self, all_drivers=False):
        logging.debug(f"[DRIVERS] _get_offline_drivers(all_drivers={all_drivers})")
        cmd = ['dism', f'/Image:{self.target_os_path}', '/Get-Drivers']
        if all_drivers:
            cmd.append('/all')
        res = self._run(cmd)
        drivers = []
        current = {}
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                if current and "published" in current:
                    drivers.append(current)
                    current = {}
                continue
            parts = line.split(":", 1)
            if len(parts) == 2:
                key, val = parts[0].strip(), parts[1].strip()
                if "Published Name" in key or "Közzétett név" in key or "Published name" in key:
                    current["published"] = val
                elif "Original File Name" in key or "Eredeti fájlnév" in key or "Original name" in key:
                    current["original"] = val
                elif "Provider Name" in key or "Szolgáltató neve" in key or "Provider" in key:
                    current["provider"] = val
                elif "Class Name" in key or "Osztálynév" in key:
                    current["class"] = val
                elif "Date and Version" in key or "Dátum és verzió" in key:
                    current["version"] = val
        if current and "published" in current:
            drivers.append(current)

        # Filter ghosts (force-deleted inbox drivers)
        valid_drivers = []
        rep = os.path.join(self.target_os_path, "Windows", "System32", "DriverStore", "FileRepository")
        for d in drivers:
            pub = d.get("published", "")
            if not pub:
                continue
            if pub.lower().startswith("oem"):
                valid_drivers.append(d)
                continue
            if glob.glob(os.path.join(rep, f"{pub}_*")):
                valid_drivers.append(d)

        logging.debug(f"[DRIVERS] _get_offline_drivers: {len(valid_drivers)} valid driver")
        return valid_drivers

    # ================================================================
    # DRIVER DELETION
    # ================================================================
    def delete_drivers(self, published_names, list_all=False, reboot=False):
        logging.info(f"[API] delete_drivers() - {len(published_names)} driver, list_all={list_all}, reboot={reboot}")
        logging.info(f"[DELETE] Törlendő driverek: {published_names}")
        self._cancel_flag = False
        def worker():
            total = len(published_names)
            success = 0
            fail = 0
            logging.info(f"[DELETE] Törlés indulása: {total} db driver")
            self.emit('task_start', {'task': 'delete', 'title': f'Törlés folyamatban... ({total} driver)'})
            self.emit('task_progress', {'task': 'delete', 'log': f'Kijelölt driverek törlése indult ({total} db)'})

            cancelled = False
            for i, pub in enumerate(published_names):
                if self._cancel_flag:
                    self.emit('task_progress', {'task': 'delete', 'log': '❗ Törlés megszakítva a felhasználó által!'})
                    self.emit('task_progress', {'status': '❗ Megszakítva!', 'counter': f'{i} / {total}'})
                    cancelled = True
                    break
                
                self.emit('task_progress', {
                    'task': 'delete', 'current': i, 'total': total,
                    'status': f'Törlés: {pub}', 'counter': f'{i+1} / {total}',
                    'log': f'🗑 Törlés: {pub}'
                })
                try:
                    is_offline = bool(self.target_os_path)
                    is_oem = pub.lower().startswith("oem")

                    if is_offline and is_oem:
                        res = self._run(['dism', f'/Image:{self.target_os_path}', '/Remove-Driver', f'/Driver:{pub}'])
                    elif not is_offline:
                        res = self._run(['pnputil', '/delete-driver', pub, '/uninstall', '/force'])
                    else:
                        class DummyRes:
                            returncode = 1
                            stdout = ""
                        res = DummyRes()

                    if res.returncode == 0 or any(k in res.stdout for k in ["Deleted", "törölve", "successfully"]):
                        success += 1
                        self.emit('task_progress', {'task': 'delete', 'log': f'  ✅ {pub} törölve'})
                    else:
                        if list_all and not is_oem:
                            if is_offline:
                                rep = os.path.join(self.target_os_path, "Windows", "System32", "DriverStore", "FileRepository")
                                inf_dir = os.path.join(self.target_os_path, "Windows", "INF")
                            else:
                                rep = os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), "System32", "DriverStore", "FileRepository")
                                inf_dir = os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), "INF")
                            dirs = glob.glob(os.path.join(rep, f"{pub}_*"))
                            
                            found_any = False
                            if dirs:
                                for d in dirs:
                                    self._run(f'takeown /f "{d}" /r /d y', shell=True)
                                    self._run(f'icacls "{d}" /grant *S-1-5-32-544:F /t', shell=True)
                                    shutil.rmtree(d, ignore_errors=True)
                                    self._run(f'rmdir /s /q "{d}"', shell=True)
                                found_any = True

                            bname = os.path.splitext(pub)[0]
                            for ext in ['.inf', '.pnf', '.INF', '.PNF']:
                                fpath = os.path.join(inf_dir, bname + ext)
                                if os.path.exists(fpath):
                                    self._run(f'takeown /f "{fpath}" /A', shell=True)
                                    self._run(f'icacls "{fpath}" /grant *S-1-5-32-544:F', shell=True)
                                    try:
                                        os.remove(fpath)
                                        found_any = True
                                    except OSError:
                                        self._run(f'del /f /q "{fpath}"', shell=True)
                                        found_any = True

                            if found_any:
                                success += 1
                                self.emit('task_progress', {'task': 'delete', 'log': f'  ✅ {pub} törölve (force)'})
                            else:
                                fail += 1
                                self.emit('task_progress', {'task': 'delete', 'log': f'  ❌ {pub} sikertelen (nem található)'})
                        else:
                            fail += 1
                            self.emit('task_progress', {'task': 'delete', 'log': f'  ❌ {pub} sikertelen'})
                except Exception as e:
                    fail += 1
                    self.emit('task_progress', {'task': 'delete', 'log': f'  ❌ {pub} hiba: {e}'})

            # Post-delete scan
            is_offline = bool(self.target_os_path)
            is_pe = os.environ.get('SystemDrive', 'C:') == 'X:'
            if not is_offline and not is_pe and success > 0:
                self.emit('task_progress', {'task': 'delete', 'log': 'Hardverek újraszkennelése...', 'status': 'Hardverek újraszkennelése...'})
                self._run(['pnputil', '/scan-devices'])
                time.sleep(3)
                self.emit('task_progress', {'task': 'delete', 'log': '✅ Hardverek frissítve!'})

            if cancelled:
                self.emit('task_progress', {'task': 'delete', 'log': f'\n--- MEGSZAKÍTVA! Sikeres: {success}, Sikertelen: {fail} ---', 'current': i, 'total': total})
                self.emit('task_complete', {'task': 'delete', 'success': success, 'fail': fail,
                                            'counter': f'❗ Megszakítva',
                                            'status': f'❗ Megszakítva! Sikeres: {success}, Sikertelen: {fail}'})
            else:
                self.emit('task_progress', {'task': 'delete', 'log': f'\n--- Sikeres: {success}, Sikertelen: {fail} ---', 'current': total, 'total': total})
                self.emit('task_complete', {'task': 'delete', 'success': success, 'fail': fail,
                                            'counter': f'✅ {success} / ❌ {fail}',
                                            'status': f'Kész! Sikeres: {success}, Sikertelen: {fail}'})
                
                # Újraindítás ha kérték
                if reboot and success > 0:
                    self.emit('task_progress', {'task': 'delete', 'log': '\n🔄 Újraindítás 5 másodperc múlva...'})
                    time.sleep(5)
                    self._run(['shutdown', '/r', '/t', '0', '/f'])

        self._safe_thread('delete', worker)

    # ================================================================
    # HARDWARE SCAN
    # ================================================================
    def start_hw_scan(self):
        logging.info("[API] start_hw_scan() hívás")
        if self._hw_scanning:
            logging.warning("[HW_SCAN] Már fut egy scan!")
            return
        self._hw_scanning = True
        logging.info("[HW_SCAN] Hardver scan indítása...")

        def worker():
            try:
                _start = time.time()
                sys_info_text = "Ismeretlen PC / Laptop"
                logging.info("[HW_SCAN] Rendszer info lekérdezése...")
                self.emit('hw_scan_progress', {'status': '⏳ Rendszer információk lekérdezése...'})

                # System info
                try:
                    ps_cmd = (
                        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                        "$cs = Get-WmiObject Win32_ComputerSystem | Select-Object Manufacturer, Model, PCSystemType; "
                        "$bb = Get-WmiObject Win32_BaseBoard | Select-Object Manufacturer, Product; "
                        "$enc = Get-WmiObject Win32_SystemEnclosure | Select-Object ChassisTypes; "
                        "@{CS=$cs; BB=$bb; ENC=$enc} | ConvertTo-Json -Depth 3"
                    )
                    res = self._run(["powershell", "-NoProfile", "-Command", ps_cmd], encoding='utf-8')
                    if res.stdout.strip():
                        data = json.loads(res.stdout.strip())
                        cs = data.get("CS", {}) or {}
                        bb = data.get("BB", {}) or {}
                        enc = data.get("ENC", {}) or {}

                        man = (cs.get("Manufacturer") or "").strip()
                        mod = (cs.get("Model") or "").strip()
                        pct = cs.get("PCSystemType", -1)

                        # Fallback: ha OEM placeholder, használjuk az alaplap infót
                        oem_junk = {"to be filled by o.e.m.", "default string", "system manufacturer",
                                    "system product name", "not applicable", ""}
                        if man.lower() in oem_junk:
                            man = (bb.get("Manufacturer") or "").strip()
                        if mod.lower() in oem_junk:
                            mod = (bb.get("Product") or "").strip()
                        if man.lower() in oem_junk:
                            man = "Ismeretlen gyártó"
                        if mod.lower() in oem_junk:
                            mod = "Ismeretlen modell"

                        # Chassis-alapú laptop/desktop detekció (pontosabb mint PCSystemType)
                        chassis = enc.get("ChassisTypes", []) or []
                        if isinstance(chassis, int):
                            chassis = [chassis]
                        laptop_chassis = {8, 9, 10, 11, 14, 30, 31, 32}  # Portable, Laptop, Notebook, Sub Notebook, etc.
                        is_laptop = pct == 2 or any(c in laptop_chassis for c in chassis)
                        prefix = "💻 Laptop" if is_laptop else "🖥️ Asztali (Desktop)"

                        sys_info_text = f"{prefix} | {man} - {mod}"
                except Exception:
                    pass
                self.emit('hw_scan_progress', {'sys_info': sys_info_text, 'status': '⏳ PnP eszközök lekérdezése...'})

                # PnP devices
                ignored_classes = ['Volume', 'VolumeSnapshot', 'DiskDrive', 'CDROM', 'Monitor', 'Battery',
                                   'SoftwareDevice', 'SoftwareComponent', 'Processor', 'Computer',
                                   'LegacyDriver', 'Endpoint', 'AudioEndpoint', 'PrintQueue', 'Printer', 'WPD']

                pnp_data = []
                try:
                    cmd_pnp = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-WmiObject Win32_PnPEntity | Select-Object Name, PNPClass, PNPDeviceID | ConvertTo-Json -Compress"
                    res = self._run(["powershell", "-NoProfile", "-Command", cmd_pnp], encoding='utf-8')
                    if res.stdout:
                        out = json.loads(res.stdout)
                        pnp_data = out if isinstance(out, list) else [out]
                except Exception as ex:
                    logging.error(f"PNP Query error: {ex}")

                self.emit('hw_scan_progress', {'status': f'📋 {len(pnp_data)} PnP eszköz szűrése...'})

                seen_hwids = set()
                devices_to_check = []
                for d in pnp_data:
                    n = d.get("Name") or "Ismeretlen Eszköz"
                    pid = d.get("PNPDeviceID") or ""
                    pclass = d.get("PNPClass") or ""
                    if not pid:
                        continue
                    if "virtual" in n.lower() or "pseudo" in n.lower() or "vmware" in n.lower():
                        continue
                    if pid.upper().startswith("ROOT\\"):
                        continue
                    if pclass in ignored_classes:
                        continue
                    hwid_clean = self._extract_hwid(pid)
                    if not hwid_clean:
                        continue
                    if hwid_clean in seen_hwids:
                        continue
                    seen_hwids.add(hwid_clean)
                    if pclass == "Display": cat = "🎮 Videókártya (VGA)"
                    elif pclass == "Media": cat = "🎵 Hangkártya (Audio)"
                    elif pclass == "Net": cat = "🌐 Hálózat (LAN/Wi-Fi)"
                    elif pclass == "Bluetooth": cat = "🔵 Bluetooth"
                    elif pclass == "System": cat = "⚙️ Rendszereszköz"
                    elif pclass == "USB": cat = "🔌 USB Vezérlő"
                    elif pclass in ("Camera", "Image"): cat = "📷 Webkamera"
                    elif pclass in ("Mouse", "Keyboard", "HIDClass"): cat = "🖱️ Periféria"
                    elif pclass == "Biometric": cat = "🔒 Ujjlenyomat / Biometria"
                    else: cat = f"🔧 Egyéb ({pclass})"
                    devices_to_check.append({"cat": cat, "name": n, "id": hwid_clean, "pnp_id": pid})

                logging.info(f"PnP szürés: {len(devices_to_check)} eszköz átment")
                total_devs = len(devices_to_check)
                self.emit('hw_scan_progress', {'status': f'✅ {total_devs} eszköz azonosítva, WU keresés indul...',
                                               'sys_info': f'{sys_info_text} | ⏳ Driver keresés...'})

                # WU COM API search
                self.hw_updates_pool = []
                self._hw_installed_devs = []
                self.wu_api_mode = True
                wu_results = self._search_wu_api()
                wu_api_success = wu_results is not None
                if wu_results is None:
                    wu_results = []

                self.emit('hw_scan_progress', {'status': '📋 Eredmények feldolgozása...'})

                matched_hwids = set()
                if wu_results:
                    for wu in wu_results:
                        wu_hwid_raw = (wu.get('HardwareID') or '').upper()
                        wu_title = wu.get('Title', '')
                        for dev in devices_to_check:
                            if dev['id'] in matched_hwids:
                                continue
                            dev_hwid = dev['id'].upper()
                            dev_pnp = dev.get('pnp_id', '').upper()
                            if (dev_hwid and dev_hwid in wu_hwid_raw) or (wu_hwid_raw and wu_hwid_raw in dev_pnp):
                                matched_hwids.add(dev['id'])
                                self.hw_updates_pool.append({
                                    "name": dev['name'], "cat": dev['cat'], "hwid": dev['id'],
                                    "wu_title": wu_title, "pnp_id": dev.get('pnp_id', '')
                                })
                                break
                    # Unmatched WU updates
                    for wu in wu_results:
                        wu_hwid_raw = (wu.get('HardwareID') or '').upper()
                        if not wu_hwid_raw:
                            continue
                        already = any(dev['id'].upper() in wu_hwid_raw or wu_hwid_raw in dev.get('pnp_id', '').upper()
                                      for dev in devices_to_check)
                        if not already:
                            self.hw_updates_pool.append({
                                "name": wu.get('DriverModel', wu.get('Title', 'Ismeretlen')),
                                "cat": "🔄 WU Driver", "hwid": wu_hwid_raw,
                                "wu_title": wu.get('Title', ''), "pnp_id": ''
                            })

                self._hw_installed_devs = [dev for dev in devices_to_check if dev['id'] not in matched_hwids]

                # Catalog fallback if WU API failed
                if not self.hw_updates_pool and not wu_api_success:
                    self.wu_api_mode = False
                    self.emit('hw_scan_progress', {'status': f'🌐 WU API hiba, katalógus keresés ({total_devs} eszköz)...'})
                    self._catalog_search(devices_to_check)

                elapsed = int(time.time() - _start)
                _m, _s = divmod(elapsed, 60)
                time_str = f"{_m} perc {_s} mp" if _m else f"{_s} mp"
                mode = "WU API" if self.wu_api_mode else "Katalógus"
                found = len(self.hw_updates_pool)
                installed = len(self._hw_installed_devs)
                final_sys = f"{sys_info_text} | ✅ Kész ({mode})! {found} frissítés ({total_devs} eszköz)"

                self.emit('hw_scan_result', {
                    'pool': self.hw_updates_pool, 'installed': self._hw_installed_devs,
                    'sys_info': final_sys, 'time': time_str
                })
                self._hw_loaded = True
            except Exception as e:
                logging.error(f"hw_scan crash: {e}")
                logging.error(traceback.format_exc())
                self.emit('hw_scan_progress', {'status': '❌ Hiba történt!'})
                self.emit('hw_scan_result', {'pool': [], 'installed': [], 'sys_info': '❌ Scan hiba', 'time': ''})
            finally:
                self._hw_scanning = False

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as e:
            logging.error(f"[HW_SCAN] Thread indítási hiba: {e}")
            self._hw_scanning = False
            self.emit('hw_scan_result', {'pool': [], 'installed': [], 'sys_info': '❌ Thread hiba', 'time': ''})

    def _extract_hwid(self, pnp_id):
        if not pnp_id:
            return None
        m = re.search(r'(HDAUDIO\\FUNC_[0-9A-F]+&VEN_[0-9A-F]+&DEV_[0-9A-F]+)', pnp_id, re.I)
        if m:
            logging.debug(f"[HWID] {pnp_id} -> {m.group(1)}")
            return m.group(1)
        m = re.search(r'(VEN_[0-9A-F]+&DEV_[0-9A-F]+)', pnp_id, re.I)
        if m:
            logging.debug(f"[HWID] {pnp_id} -> {m.group(1)}")
            return m.group(1)
        m = re.search(r'(HID\\VID_[0-9A-F]+&PID_[0-9A-F]+)', pnp_id, re.I)
        if m:
            logging.debug(f"[HWID] {pnp_id} -> {m.group(1)}")
            return m.group(1)
        m = re.search(r'(USB\\VID_[0-9A-F]+&PID_[0-9A-F]+)', pnp_id, re.I)
        if m:
            logging.debug(f"[HWID] {pnp_id} -> {m.group(1)}")
            return m.group(1)
        m = re.search(r'(VID_[0-9A-F]+&PID_[0-9A-F]+)', pnp_id, re.I)
        if m:
            logging.debug(f"[HWID] {pnp_id} -> {m.group(1)}")
            return m.group(1)
        m = re.search(r'(ACPI\\[A-Z0-9_]+)', pnp_id, re.I)
        if m:
            logging.debug(f"[HWID] {pnp_id} -> {m.group(1)}")
            return m.group(1)
        m = re.search(r'(DISPLAY\\[A-Z0-9]+)', pnp_id, re.I)
        if m:
            logging.debug(f"[HWID] {pnp_id} -> {m.group(1)}")
            return m.group(1)
        logging.debug(f"[HWID] {pnp_id} -> None (no match)")
        return None

    def _search_wu_api(self):
        logging.info("[WU_API] _search_wu_api() indult...")
        try:
            ps_cmd = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    $Session = New-Object -ComObject Microsoft.Update.Session
    $Searcher = $Session.CreateUpdateSearcher()
    try {
        $SM = New-Object -ComObject Microsoft.Update.ServiceManager
        $SM.AddService2("7971f918-a847-4430-9279-4a52d1efe18d", 7, "") | Out-Null
    } catch {}
    $Searcher.ServerSelection = 3
    $Searcher.ServiceID = "7971f918-a847-4430-9279-4a52d1efe18d"
    $Result = $Searcher.Search("IsInstalled=0 and Type='Driver'")
    $updates = @()
    foreach ($U in $Result.Updates) {
        $updates += [PSCustomObject]@{
            Title = $U.Title; DriverModel = $U.DriverModel; HardwareID = $U.DriverHardwareID
            DriverClass = $U.DriverClass; DriverProvider = $U.DriverProvider
            UpdateID = $U.Identity.UpdateID; Size = $U.MaxDownloadSize
        }
    }
    if ($updates.Count -eq 0) { Write-Output "[]" }
    else { $updates | ConvertTo-Json -Depth 2 -Compress }
} catch { Write-Error $_.Exception.Message }
"""
            res = self._run(["powershell", "-NoProfile", "-Command", ps_cmd], timeout=300, encoding='utf-8')
            out = res.stdout.strip()
            if not out and res.stderr:
                logging.warning(f"[WU_API] Stderr: {res.stderr[:200]}")
                return None
            if out:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                logging.info(f"[WU_API] Talált frissítések: {len(data) if isinstance(data, list) else 0}")
                return data if isinstance(data, list) else None
        except subprocess.TimeoutExpired:
            logging.error("[WU_API] WU API timeout (300s)")
        except Exception as e:
            logging.error(f"[WU_API] WU API error: {e}")
        return None

    def _catalog_search(self, devices_to_check):
        logging.info(f"[CATALOG] _catalog_search() - {len(devices_to_check)} eszköz ellenőrzése...")
        import urllib.request, urllib.parse, ssl
        ssl_ctx = ssl.create_default_context()
        lock = threading.Lock()

        def check_one(item):
            try:
                url = 'https://www.catalog.update.microsoft.com/Search.aspx?q=' + urllib.parse.quote(item['id'])
                logging.debug(f"[CATALOG] Keresés: {item['name']} ({item['id']})")
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                html = urllib.request.urlopen(req, context=ssl_ctx, timeout=30).read().decode('utf-8')
                match_ids = re.findall(r"id=['\"]([a-fA-F0-9\-]+)_link['\"]", html)
                if match_ids:
                    best_id = match_ids[0]
                    dl_body = f'updateIDs=[{{"size":0,"languages":"","uidInfo":"{best_id}","updateID":"{best_id}"}}]'
                    dl_req = urllib.request.Request(
                        'https://www.catalog.update.microsoft.com/DownloadDialog.aspx',
                        data=dl_body.encode('utf-8'),
                        headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/x-www-form-urlencoded'})
                    dl_html = urllib.request.urlopen(dl_req, context=ssl_ctx, timeout=30).read().decode('utf-8')
                    cab_link = re.search(r'downloadInformation\[0\]\.files\[0\]\.url\s*=\s*[\"\']([^\"\']+)[\"\']', dl_html)
                    if cab_link:
                        logging.debug(f"[CATALOG] Találat: {item['name']} - {cab_link.group(1)[:50]}...")
                        with lock:
                            self.hw_updates_pool.append({
                                "name": item['name'], "cat": item['cat'], "hwid": item['id'],
                                "url": cab_link.group(1), "pnp_id": item.get('pnp_id', ''),
                                "wu_title": f"MS Katalógus: {item['name']}"
                            })
            except Exception as e:
                logging.debug(f"[CATALOG] Hiba: {item['name']} - {e}")
                pass

        q = queue.Queue()
        for dev in devices_to_check:
            q.put(dev)

        def cat_worker():
            while not q.empty():
                try:
                    dev = q.get_nowait()
                except Exception:
                    break
                check_one(dev)
                q.task_done()

        threads = [threading.Thread(target=cat_worker, daemon=True) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

        catalog_hwids = {drv['hwid'] for drv in self.hw_updates_pool}
        self._hw_installed_devs = [dev for dev in devices_to_check if dev['id'] not in catalog_hwids]
        logging.info(f"[CATALOG] Kész - {len(self.hw_updates_pool)} találat, {len(self._hw_installed_devs)} nem elérhető")

    # ================================================================
    # WU DRIVER INSTALL
    # ================================================================
    def install_selected_wu(self, selected_indices):
        logging.info(f"[API] install_selected_wu() - {len(selected_indices)} index kiválasztva")
        logging.debug(f"[WU_INSTALL] Indexek: {selected_indices}")
        self._cancel_flag = False  # Reset cancel flag
        selected_pool = [self.hw_updates_pool[i] for i in selected_indices if 0 <= i < len(self.hw_updates_pool)]
        if not selected_pool:
            logging.warning("[WU_INSTALL] Nincs érvényes driver kiválasztva!")
            self.emit('toast', {'message': '⚠️ Nincs érvényes driver kiválasztva!', 'type': 'warning'})
            return
        logging.info(f"[WU_INSTALL] {len(selected_pool)} driver telepítése, mód={'WU API' if self.wu_api_mode else 'Katalógus'}")

        if self.wu_api_mode:
            self._install_wu_api(selected_pool)
        else:
            self._install_catalog(selected_pool)

    def _install_wu_api(self, selected_pool):
        logging.info(f"[WU_API] WU API telepítés indítása: {len(selected_pool)} driver")
        def worker():
            self.emit('task_start', {'task': 'wu_install', 'title': f'Driver Telepítés WU Szerverekről ({len(selected_pool)} db)'})
            self.emit('task_progress', {'task': 'wu_install', 'log': 'Windows Update szervereiről történő telepítés indítása...', 'indeterminate': True})

            pool_hwids = [drv.get('hwid', '').upper() for drv in selected_pool if drv.get('hwid')]
            hwid_list_ps = ','.join(f'"{h}"' for h in pool_hwids)

            ps_script = '$TargetHWIDs = @(' + hwid_list_ps + ')\n' + r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    Write-Output "INIT: Windows Update Session létrehozása..."
    $Session = New-Object -ComObject Microsoft.Update.Session
    $Searcher = $Session.CreateUpdateSearcher()
    try { $SM = New-Object -ComObject Microsoft.Update.ServiceManager; $SM.AddService2("7971f918-a847-4430-9279-4a52d1efe18d", 7, "") | Out-Null } catch {}
    $Searcher.ServerSelection = 3
    $Searcher.ServiceID = "7971f918-a847-4430-9279-4a52d1efe18d"
    Write-Output "SEARCH: Driver frissítések keresése..."
    $Result = $Searcher.Search("IsInstalled=0 and Type='Driver'")
    if ($Result.Updates.Count -eq 0) { Write-Output "EMPTY: Nem található elérhető driver frissítés."; return }
    $ToInstall = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($U in $Result.Updates) {
        $matchFound = $false
        if ($TargetHWIDs.Count -eq 0) { $matchFound = $true } else {
            foreach ($hwid in $U.DriverHardwareID) {
                $hUpper = $hwid.ToUpper()
                foreach ($target in $TargetHWIDs) { if ($hUpper.Contains($target) -or $target.Contains($hUpper)) { $matchFound = $true; break } }
                if ($matchFound) { break }
            }
        }
        if (-not $matchFound) { Write-Output "SKIP: $($U.Title)"; continue }
        if (-not $U.EulaAccepted) { $U.AcceptEula() }
        $ToInstall.Add($U) | Out-Null
        Write-Output "FOUND: $($U.Title)"
    }
    if ($ToInstall.Count -eq 0) { Write-Output "EMPTY: Nem található egyező driver."; return }
    $total = $ToInstall.Count; Write-Output "TOTAL: $total"
    $s = 0; $f = 0
    for ($i = 0; $i -lt $total; $i++) {
        $U = $ToInstall.Item($i); $t = $U.Title; $idx = $i + 1
        Write-Output "DLONE: $idx/$total $t"
        $SC = New-Object -ComObject Microsoft.Update.UpdateColl; $SC.Add($U) | Out-Null
        $DL = $Session.CreateUpdateDownloader(); $DL.Updates = $SC
        try { $DR = $DL.Download() } catch { Write-Output "FAIL: [LETÖLTÉS HIBA] $t"; $f++; continue }
        if ($DR.ResultCode -ne 2 -and $DR.ResultCode -ne 3) { Write-Output "FAIL: [LETÖLTÉS HIBA kód=$($DR.ResultCode)] $t"; $f++; continue }
        Write-Output "INSTONE: $idx/$total $t"
        $Inst = $Session.CreateUpdateInstaller(); $Inst.Updates = $SC
        try { $IR = $Inst.Install() } catch { Write-Output "FAIL: [TELEPÍTÉS HIBA] $t"; $f++; continue }
        $rc = $IR.GetUpdateResult(0).ResultCode
        switch ($rc) { 2 { Write-Output "OK: $t"; $s++ } 3 { Write-Output "OK: $t"; $s++ } default { Write-Output "FAIL: [kód=$rc] $t"; $f++ } }
    }
    Write-Output "DONE: Sikeres=$s, Sikertelen=$f"
} catch { Write-Output "ERROR: $($_.Exception.Message)" }
"""
            process = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                startupinfo=self._si, creationflags=self._nw)

            success = 0
            fail = 0
            install_total = 0

            for line in process.stdout:
                if self._check_cancel():
                    process.terminate()
                    process.wait()  # Prevent zombie process
                    self.emit('task_progress', {'task': 'wu_install', 'log': '\n❗ Megszakítva!'})
                    self.emit('task_complete', {'task': 'wu_install', 'status': '❗ Megszakítva!', 'success': success, 'fail': fail})
                    return
                line = line.strip()
                if not line:
                    continue
                if line.startswith("INIT:") or line.startswith("SEARCH:"):
                    self.emit('task_progress', {'task': 'wu_install', 'status': line.split(":", 1)[1].strip(), 'log': line})
                elif line.startswith("FOUND:"):
                    self.emit('task_progress', {'task': 'wu_install', 'log': f'  📦 {line[6:].strip()}'})
                elif line.startswith("SKIP:"):
                    self.emit('task_progress', {'task': 'wu_install', 'log': f'  ⏭ {line[5:].strip()}'})
                elif line.startswith("TOTAL:"):
                    m = re.search(r'(\d+)', line)
                    if m:
                        install_total = int(m.group(1))
                    self.emit('task_progress', {'task': 'wu_install', 'log': f'Összesen {install_total} driver telepítése...',
                                                'total': install_total, 'current': 0, 'counter': f'0 / {install_total}'})
                elif line.startswith("DLONE:"):
                    self.emit('task_progress', {'task': 'wu_install', 'status': f'⬇ Letöltés: {line[6:].strip()}', 'log': f'  ⬇ {line[6:].strip()}'})
                elif line.startswith("INSTONE:"):
                    self.emit('task_progress', {'task': 'wu_install', 'status': f'⚙ Telepítés: {line[8:].strip()}', 'log': f'  ⚙ {line[8:].strip()}'})
                elif line.startswith("OK:"):
                    success += 1
                    done = success + fail
                    self.emit('task_progress', {'task': 'wu_install', 'log': f'  ✅ {line[3:].strip()}',
                                                'current': done, 'total': install_total, 'counter': f'{done}/{install_total} (✅{success} ❌{fail})'})
                elif line.startswith("FAIL:"):
                    fail += 1
                    done = success + fail
                    self.emit('task_progress', {'task': 'wu_install', 'log': f'  ❌ {line[5:].strip()}',
                                                'current': done, 'total': install_total, 'counter': f'{done}/{install_total} (✅{success} ❌{fail})'})
                elif line.startswith("DONE:"):
                    self.emit('task_progress', {'task': 'wu_install', 'log': f'\n--- {line[5:].strip()} ---'})
                elif line.startswith("EMPTY:"):
                    self.emit('task_progress', {'task': 'wu_install', 'log': line[6:].strip()})
                elif line.startswith("ERROR:"):
                    self.emit('task_progress', {'task': 'wu_install', 'log': f'❌ HIBA: {line[6:].strip()}'})
                else:
                    self.emit('task_progress', {'task': 'wu_install', 'log': line})
            process.wait()

            if success > 0:
                self.emit('task_progress', {'task': 'wu_install', 'log': 'Eszközök újraszkennelése...', 'status': 'Aktiválás...'})
                self._run(['pnputil', '/scan-devices'])
                self.emit('task_progress', {'task': 'wu_install', 'log': '✅ Eszközök frissítve!'})

            msg = f'Sikeres: {success}, Sikertelen: {fail}'
            self.emit('task_complete', {'task': 'wu_install', 'success': success, 'fail': fail,
                                        'status': msg, 'counter': msg})

        self._safe_thread('wu_install', worker)

    def _install_catalog(self, selected_pool):
        logging.info(f"[CATALOG_INSTALL] _install_catalog() - {len(selected_pool)} driver")
        def worker():
            logging.info("[CATALOG_INSTALL] Worker indult...")
            import urllib.request, ssl
            ssl_ctx = ssl.create_default_context()
            total = len(selected_pool)
            self.emit('task_start', {'task': 'wu_install', 'title': f'Katalógus Driver Telepítés ({total} db)'})

            temp_dir = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'driverdoktor_wu')
            os.makedirs(temp_dir, exist_ok=True)
            logging.debug(f"[CATALOG_INSTALL] Temp dir: {temp_dir}")
            success = 0
            fail = 0
            skipped = 0

            try:
                for i, drv in enumerate(selected_pool):
                    if self._check_cancel():
                        logging.warning("[CATALOG_INSTALL] Megszakítva!")
                        self.emit('task_progress', {'task': 'wu_install', 'log': '\n❗ Megszakítva!'})
                        self.emit('task_complete', {'task': 'wu_install', 'status': '❗ Megszakítva!', 'success': success, 'fail': fail})
                        return
                    name = drv['name']
                    url = drv.get('url', '')
                    logging.info(f"[CATALOG_INSTALL] [{i+1}/{total}] {name}")
                    if not url:
                        logging.warning(f"[CATALOG_INSTALL] Kihagyás - nincs URL: {name}")
                        self.emit('task_progress', {'task': 'wu_install', 'log': f'  [KIHAGYÁS] {name} - nincs link'})
                        skipped += 1
                        continue

                    cab_path = os.path.join(temp_dir, f"drv_{i}.cab")
                    ext_path = os.path.join(temp_dir, f"drv_ext_{i}")
                    self.emit('task_progress', {'task': 'wu_install', 'current': i, 'total': total,
                                                'status': f'Letöltés: {name}', 'counter': f'{i+1}/{total}',
                                                'log': f'-> {name} letöltése...'})
                    try:
                        logging.debug(f"[CATALOG_INSTALL] Letöltés: {url[:80]}...")
                        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                        with urllib.request.urlopen(req, context=ssl_ctx) as resp, open(cab_path, 'wb') as f:
                            shutil.copyfileobj(resp, f)
                        logging.debug(f"[CATALOG_INSTALL] Letöltve: {cab_path}")
                    except Exception as e:
                        logging.error(f"[CATALOG_INSTALL] Letöltési hiba: {e}")
                        self.emit('task_progress', {'task': 'wu_install', 'log': f'  [HIBA] Letöltés: {e}'})
                        fail += 1
                        continue

                    os.makedirs(ext_path, exist_ok=True)
                    self._run(['expand', cab_path, '-F:*', ext_path])
                    for inner_cab in glob.glob(os.path.join(ext_path, '*.cab')):
                        inner_ext = inner_cab + '_ext'
                        os.makedirs(inner_ext, exist_ok=True)
                        self._run(['expand', inner_cab, '-F:*', inner_ext])

                    self.emit('task_progress', {'task': 'wu_install', 'status': f'Telepítés: {name}', 'log': f'  Telepítés...'})
                    is_offline = bool(self.target_os_path)
                    if is_offline:
                        cmd = ['dism', f'/Image:{self.target_os_path}', '/Add-Driver', f'/Driver:{ext_path}', '/Recurse', '/ForceUnsigned']
                    else:
                        cmd = ['pnputil', '/add-driver', f"{ext_path}\\*.inf", '/subdirs', '/install']
                    res = self._run(cmd)
                    if res.returncode == 0 or any(k in res.stdout for k in ["Added", "sikeres", "successfully"]):
                        success += 1
                        logging.info(f"[CATALOG_INSTALL] ✅ {name} telepítve!")
                        self.emit('task_progress', {'task': 'wu_install', 'log': f'  ✅ {name} telepítve!'})
                    else:
                        fail += 1
                        logging.error(f"[CATALOG_INSTALL] ❌ {name} hiba: {res.stdout[:100]}")
                        self.emit('task_progress', {'task': 'wu_install', 'log': f'  ❌ {name} hiba: {res.stdout[:100]}'})

                if success > 0 and not self.target_os_path:
                    self.emit('task_progress', {'task': 'wu_install', 'log': 'Eszközök újraszkennelése...'})
                    self._run(['pnputil', '/scan-devices'])
            finally:
                logging.debug(f"[CATALOG_INSTALL] Temp dir törlése: {temp_dir}")
                shutil.rmtree(temp_dir, ignore_errors=True)

            logging.info(f"[CATALOG_INSTALL] Kész - Sikeres: {success}/{total}, Sikertelen: {fail}, Kihagyott: {skipped}")
            self.emit('task_progress', {'task': 'wu_install', 'current': total, 'total': total,
                                        'log': f'\n--- Sikeres: {success}, Sikertelen: {fail}, Kihagyott: {skipped} ---'})
            self.emit('task_complete', {'task': 'wu_install', 'success': success, 'fail': fail,
                                        'status': f'Kész! Sikeres: {success}, Sikertelen: {fail}' + (f', Kihagyott: {skipped}' if skipped else '')})

        self._safe_thread('wu_install', worker)

    # ================================================================
    # AUTOFIX
    # ================================================================
    def _open_autofix_progress_window(self):
        """Nyit egy külön WebView2 progress ablakot software renderinggel."""
        try:
            self._autofix_log_path = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'DriverDoktor_autofix_progress.jsonl')
            # Töröljük a régi fájlt ha van
            if os.path.exists(self._autofix_log_path):
                os.remove(self._autofix_log_path)
            
            # Megnyitjuk a log fájlt írásra ELŐSZÖR (mielőtt a subprocess elindul)
            self._autofix_log_file = open(self._autofix_log_path, 'w', encoding='utf-8', buffering=1)
            logging.info(f"[AUTOFIX] Progress log létrehozva: {self._autofix_log_path}")
            
            # Az exe önmagát hívja meg --progress argumentummal
            # Ez mind frozen, mind dev módban működik
            self._autofix_window_proc = subprocess.Popen(
                [sys.executable, '--progress', self._autofix_log_path],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            logging.info(f"[AUTOFIX] Progress ablak indítva: {sys.executable} --progress")
        except Exception as e:
            logging.error(f"[AUTOFIX] Progress ablak nyitási hiba: {e}")
            self._autofix_log_file = None
            self._autofix_window_proc = None

    def _close_autofix_progress_window(self):
        """Bezárja az autofix progress ablakot."""
        try:
            if self._autofix_log_file:
                # Küldünk egy complete jelzést
                self._autofix_log_file.write(json.dumps({'complete': True}) + '\n')
                self._autofix_log_file.flush()
                time.sleep(0.5)
                self._autofix_log_file.close()
                self._autofix_log_file = None
            
            # 10 mp múlva bezárjuk az ablakot
            def close_later():
                time.sleep(10)
                if hasattr(self, '_autofix_window_proc') and self._autofix_window_proc:
                    try:
                        self._autofix_window_proc.terminate()
                        self._autofix_window_proc.wait()  # Prevent zombie process
                    except Exception:
                        pass
                    self._autofix_window_proc = None
            threading.Thread(target=close_later, daemon=True).start()
        except Exception as e:
            logging.error(f"[AUTOFIX] Progress ablak bezárási hiba: {e}")

    def _write_progress(self, data):
        """Ír a progress ablaknak JSON formátumban."""
        if self._autofix_log_file:
            try:
                self._autofix_log_file.write(json.dumps(data, ensure_ascii=False) + '\n')
                self._autofix_log_file.flush()
            except Exception:
                pass

    def start_autofix(self):
        logging.info("[API] start_autofix() - 1 KATTINTÁSOS DRIVER FIX INDÍTVA!")
        logging.info("=" * 60)
        logging.info("[AUTOFIX] TELJES DRIVER ÚJRATELEPÍTÉS INDÍTÁSA")
        logging.info("=" * 60)
        self._cancel_flag = False  # Reset cancel flag
        
        # Külön WebView2 progress ablak megnyitása (software rendering)
        self._open_autofix_progress_window()
        
        def worker():
            overall_start = time.time()

            def elapsed():
                s = int(time.time() - overall_start)
                m, sec = divmod(s, 60)
                return f"{m:02d}:{sec:02d}"

            def check_cancel():
                if self._check_cancel():
                    logging.warning("[AUTOFIX] Felhasználó megszakította!")
                    self.emit('task_progress', {'task': 'autofix', 'log': '\n❗ Megszakítva a felhasználó által!'})
                    self.emit('task_complete', {'task': 'autofix', 'status': '❗ Megszakítva!', 'counter': 'Megszakítva'})
                    self._close_autofix_progress_window()
                    return True
                return False

            self.emit('task_start', {'task': 'autofix', 'title': '⚡ 1 Kattintásos Driver Fix'})

            # PHASE 1: Disable WU drivers
            logging.info("[AUTOFIX] FÁZIS 1: WU driver letiltása...")
            self.emit('task_progress', {'task': 'autofix', 'phase': '⛔ 1. FÁZIS: WU letiltás',
                                        'log': '=' * 50 + '\nFÁZIS 1: WU driver keresés letiltása...',
                                        'current': 0, 'total': 4})
            try:
                key_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
                logging.debug(f"[AUTOFIX] Registry írás: {key_path}")
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 1)
                logging.info("[AUTOFIX] ExcludeWUDriversInQualityUpdate = 1")
                self.emit('task_progress', {'task': 'autofix', 'log': '  ✅ ExcludeWUDriversInQualityUpdate = 1'})
            except Exception as e:
                logging.error(f"[AUTOFIX] winreg hiba: {e}")
                self.emit('task_progress', {'task': 'autofix', 'log': f'  ⚠ winreg hiba: {e}'})
            self._run(['reg', 'add', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate',
                       '/v', 'ExcludeWUDriversInQualityUpdate', '/t', 'REG_DWORD', '/d', '1', '/f'])

            try:
                key_path2 = r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching"
                logging.debug(f"[AUTOFIX] Registry írás: {key_path2}")
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path2, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 0)
                logging.info("[AUTOFIX] SearchOrderConfig = 0")
                self.emit('task_progress', {'task': 'autofix', 'log': '  ✅ SearchOrderConfig = 0'})
            except Exception as e:
                logging.error(f"[AUTOFIX] winreg hiba: {e}")
                self.emit('task_progress', {'task': 'autofix', 'log': f'  ⚠ winreg hiba: {e}'})
            self._run(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching',
                       '/v', 'SearchOrderConfig', '/t', 'REG_DWORD', '/d', '0', '/f'])

            self._run('net stop wuauserv & net start wuauserv', shell=True)
            logging.info("[AUTOFIX] WU szolgáltatás újraindítva")
            self.emit('task_progress', {'task': 'autofix', 'log': '  ✅ WU szolgáltatás újraindítva\n\n✅ WU letiltás kész!\n',
                                        'current': 4, 'total': 4})
            
            if check_cancel(): return

            # PHASE 2: Delete third-party drivers
            self.emit('task_progress', {'task': 'autofix', 'phase': '🔴 2. FÁZIS: Driver törlés',
                                        'log': '=' * 50 + '\nFÁZIS 2: Third-party driverek törlése...'})
            drivers = self._get_third_party_drivers()
            del_total = len(drivers)
            self.emit('task_progress', {'task': 'autofix', 'log': f'Talált: {del_total} db', 'total': max(del_total, 1), 'current': 0})
            del_success = 0
            del_fail = 0
            display_driver_deleted = False
            for i, drv in enumerate(drivers):
                if check_cancel(): return
                pub = drv.get("published", "?")
                prov = drv.get("provider", "")
                drv_class = drv.get("class", "").lower()
                self.emit('task_progress', {'task': 'autofix', 'status': f'Törlés: {pub}', 'log': f'  🗑 {pub} [{prov}]'})
                try:
                    res = self._run(['pnputil', '/delete-driver', pub, '/uninstall', '/force'])
                    if res.returncode == 0 or any(k in res.stdout for k in ["Deleted", "törölve", "successfully"]):
                        del_success += 1
                        self.emit('task_progress', {'task': 'autofix', 'log': f'    ✅ törölve'})
                        # Track display driver deletion for window recovery
                        if 'display' in drv_class or 'video' in drv_class or 'nvidia' in prov.lower() or 'amd' in prov.lower() or 'intel' in prov.lower():
                            display_driver_deleted = True
                            logging.info(f"[AUTOFIX] Display driver törölve: {pub} ({prov})")
                    else:
                        del_fail += 1
                        self.emit('task_progress', {'task': 'autofix', 'log': f'    ❌ sikertelen'})
                except Exception as e:
                    del_fail += 1
                    self.emit('task_progress', {'task': 'autofix', 'log': f'    ❌ hiba: {e}'})
                self.emit('task_progress', {'task': 'autofix', 'current': i + 1, 'total': del_total,
                                            'counter': f'{i+1}/{del_total} (✅{del_success} ❌{del_fail})'})

            self.emit('task_progress', {'task': 'autofix', 'log': f'\n--- Törlés kész. Sikeres: {del_success}, Sikertelen: {del_fail} ---\n'})
            
            # Display driver recovery: if GPU driver was deleted, try to recover the window
            if display_driver_deleted:
                logging.info("[AUTOFIX] Display driver törölve - ablak helyreállítás...")
                self.emit('task_progress', {'task': 'autofix', 'log': '🖥️ Videókártya driver törölve - ablak helyreállítás...'})
                time.sleep(3)  # Wait for Basic Display Adapter to initialize
                try:
                    if self._window:
                        # Try to recover WebView2 rendering by reloading
                        html_path = resource_path('ui.html')
                        self._window.load_url(f'file:///{html_path}')
                        time.sleep(2)
                        # Re-send current state to UI
                        self.emit('task_progress', {'task': 'autofix', 'phase': '🔴 2. FÁZIS: Driver törlés',
                                                    'log': '✅ Ablak helyreállítva! Folytatás...',
                                                    'current': del_total, 'total': del_total})
                        logging.info("[AUTOFIX] Ablak helyreállítás sikeres!")
                except Exception as e:
                    logging.warning(f"[AUTOFIX] Ablak helyreállítás sikertelen: {e}")

            if check_cancel(): return

            # PHASE 3: Hardware rescan
            self.emit('task_progress', {'task': 'autofix', 'phase': '🟡 3. FÁZIS: Hardver scan',
                                        'log': '=' * 50 + '\nFÁZIS 3: pnputil /scan-devices...', 'indeterminate': True})
            try:
                self._run(['pnputil', '/scan-devices'], timeout=120)
                time.sleep(5)
                self.emit('task_progress', {'task': 'autofix', 'log': '✅ Hardver scan kész!'})
            except Exception:
                self.emit('task_progress', {'task': 'autofix', 'log': '⚠ Scan timeout/hiba — folytatás...'})

            if check_cancel(): return

            # PHASE 4+5: WU search & install (single PS process)
            self.emit('task_progress', {'task': 'autofix', 'phase': '🟠 4. FÁZIS: Driver keresés + telepítés (WU szerverekről)',
                                        'log': '=' * 50 + '\nFÁZIS 4: Driver keresés és telepítés WU szerverekről...\n', 'indeterminate': True})

            ps_script = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    $Session = New-Object -ComObject Microsoft.Update.Session
    $Searcher = $Session.CreateUpdateSearcher()
    try { $SM = New-Object -ComObject Microsoft.Update.ServiceManager; $SM.AddService2("7971f918-a847-4430-9279-4a52d1efe18d", 7, "") | Out-Null } catch {}
    $Searcher.ServerSelection = 3; $Searcher.ServiceID = "7971f918-a847-4430-9279-4a52d1efe18d"
    Write-Output "SEARCH: Driver frissítések keresése..."
    $Result = $Searcher.Search("IsInstalled=0 and Type='Driver'")
    if ($Result.Updates.Count -eq 0) { Write-Output "EMPTY: Nincs elérhető driver."; return }
    $ToInstall = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($U in $Result.Updates) {
        if (-not $U.EulaAccepted) { $U.AcceptEula() }
        $ToInstall.Add($U) | Out-Null; Write-Output "FOUND: $($U.Title)"
    }
    $total = $ToInstall.Count; Write-Output "TOTAL: $total"
    $s = 0; $f = 0
    for ($i = 0; $i -lt $total; $i++) {
        $U = $ToInstall.Item($i); $t = $U.Title; $idx = $i + 1
        Write-Output "DLONE: $idx/$total $t"
        $SC = New-Object -ComObject Microsoft.Update.UpdateColl; $SC.Add($U) | Out-Null
        $DL = $Session.CreateUpdateDownloader(); $DL.Updates = $SC
        try { $DR = $DL.Download() } catch { Write-Output "FAIL: [LETÖLTÉS] $t"; $f++; continue }
        if ($DR.ResultCode -ne 2 -and $DR.ResultCode -ne 3) { Write-Output "FAIL: [DL kód=$($DR.ResultCode)] $t"; $f++; continue }
        Write-Output "INSTONE: $idx/$total $t"
        $Inst = $Session.CreateUpdateInstaller(); $Inst.Updates = $SC
        try { $IR = $Inst.Install() } catch { Write-Output "FAIL: [TELEPÍTÉS] $t"; $f++; continue }
        $rc = $IR.GetUpdateResult(0).ResultCode
        switch ($rc) { 2 { Write-Output "OK: $t"; $s++ } 3 { Write-Output "OK: $t"; $s++ } default { Write-Output "FAIL: [kód=$rc] $t"; $f++ } }
    }
    Write-Output "DONE: Sikeres=$s, Sikertelen=$f"
} catch { Write-Output "ERROR: $($_.Exception.Message)" }
"""
            install_success = 0
            install_fail = 0
            install_total = 0
            process = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                startupinfo=self._si, creationflags=self._nw)

            for line in process.stdout:
                if self._check_cancel():
                    process.terminate()
                    process.wait()  # Prevent zombie process
                    self.emit('task_progress', {'task': 'autofix', 'log': '\n❗ Megszakítva!'})
                    self.emit('task_complete', {'task': 'autofix', 'status': '❗ Megszakítva!', 'counter': 'Megszakítva'})
                    return
                line = line.strip()
                if not line:
                    continue
                if line.startswith("SEARCH:"):
                    self.emit('task_progress', {'task': 'autofix', 'status': line.split(":", 1)[1].strip(), 'log': line})
                elif line.startswith("FOUND:"):
                    self.emit('task_progress', {'task': 'autofix', 'log': f'  📦 {line[6:].strip()}'})
                elif line.startswith("TOTAL:"):
                    m = re.search(r'(\d+)', line)
                    if m: install_total = int(m.group(1))
                    self.emit('task_progress', {'task': 'autofix', 'phase': f'🟢 5. FÁZIS: {install_total} driver telepítése (WU szerverekről)',
                                                'total': max(install_total, 1), 'current': 0, 'log': f'\nÖsszesen {install_total} driver telepítése WU szerverekről...'})
                elif line.startswith("DLONE:"):
                    self.emit('task_progress', {'task': 'autofix', 'status': f'⬇ {line[6:].strip()}', 'log': f'  ⬇ {line[6:].strip()}'})
                elif line.startswith("INSTONE:"):
                    self.emit('task_progress', {'task': 'autofix', 'status': f'⚙ {line[8:].strip()}', 'log': f'  ⚙ {line[8:].strip()}'})
                elif line.startswith("OK:"):
                    install_success += 1
                    done = install_success + install_fail
                    self.emit('task_progress', {'task': 'autofix', 'log': f'  ✅ {line[3:].strip()}',
                                                'current': done, 'total': max(install_total, 1), 'counter': f'{done}/{install_total} (✅{install_success} ❌{install_fail})'})
                elif line.startswith("FAIL:"):
                    install_fail += 1
                    done = install_success + install_fail
                    self.emit('task_progress', {'task': 'autofix', 'log': f'  ❌ {line[5:].strip()}',
                                                'current': done, 'total': max(install_total, 1), 'counter': f'{done}/{install_total} (✅{install_success} ❌{install_fail})'})
                elif line.startswith("DONE:"):
                    self.emit('task_progress', {'task': 'autofix', 'log': f'\n--- {line[5:].strip()} ---'})
                elif line.startswith("EMPTY:"):
                    self.emit('task_progress', {'task': 'autofix', 'log': line[6:].strip()})
                elif line.startswith("ERROR:"):
                    self.emit('task_progress', {'task': 'autofix', 'log': f'❌ HIBA: {line[6:].strip()}'})
                else:
                    self.emit('task_progress', {'task': 'autofix', 'log': line})
            process.wait()

            if install_success > 0:
                self.emit('task_progress', {'task': 'autofix', 'log': '\nEszközök újraszkennelése...'})
                self._run(['pnputil', '/scan-devices'])
                self.emit('task_progress', {'task': 'autofix', 'log': '✅ Eszközök frissítve!'})

            if check_cancel(): return

            # PHASE 6: Reboot (only if changes were made)
            changes_made = (del_success > 0) or (install_success > 0)
            if changes_made:
                self.emit('task_progress', {'task': 'autofix', 'phase': '🔵 6. FÁZIS: Újraindítás',
                                            'log': f'\n{"=" * 50}\nFÁZIS 6: Újraindítás 30 másodperc múlva!\n\n⚡ Teljes idő: {elapsed()}'})
                for c in range(30, 0, -1):
                    if check_cancel(): return
                    self.emit('task_progress', {'task': 'autofix', 'counter': f'Újraindítás {c} mp múlva...', 'current': 30 - c, 'total': 30})
                    time.sleep(1)

                self.emit('task_progress', {'task': 'autofix', 'log': '🔄 Újraindítás MOST!'})
                self.emit('task_complete', {'task': 'autofix', 'status': '🔄 Újraindítás...', 'counter': 'Reboot'})
                self._close_autofix_progress_window()
                self._run(['shutdown', '/r', '/t', '0', '/f'])
            else:
                self.emit('task_progress', {'task': 'autofix', 'phase': '✅ KÉSZ',
                                            'log': f'\n{"=" * 50}\nNem történt változás - újraindítás nem szükséges.\n\n⚡ Teljes idő: {elapsed()}'})
                self.emit('task_complete', {'task': 'autofix', 'status': '✅ Kész (nincs változás)', 'counter': 'Kész'})
                self._close_autofix_progress_window()

        self._safe_thread('autofix', worker)

    # ================================================================
    # WU MANAGEMENT
    # ================================================================
    def check_wu_status(self):
        logging.info("[API] check_wu_status()")
        try:
            policy_disabled = False
            search_disabled = False
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate", 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, "ExcludeWUDriversInQualityUpdate")
                    if val == 1: policy_disabled = True
                    logging.debug(f"[WU_STATUS] ExcludeWUDriversInQualityUpdate = {val}")
            except FileNotFoundError:
                logging.debug("[WU_STATUS] ExcludeWUDriversInQualityUpdate kulcs nem létezik")
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching", 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, "SearchOrderConfig")
                    if val == 0: search_disabled = True
                    logging.debug(f"[WU_STATUS] SearchOrderConfig = {val}")
            except FileNotFoundError:
                logging.debug("[WU_STATUS] SearchOrderConfig kulcs nem létezik")

            if policy_disabled and search_disabled:
                result = {'status': 'Teljesen LETILTVA', 'color': 'disabled'}
            elif policy_disabled:
                result = {'status': 'Házirend által LETILTVA', 'color': 'disabled'}
            elif search_disabled:
                result = {'status': 'Eszközbeállításokban LETILTVA', 'color': 'disabled'}
            else:
                result = {'status': 'Driver frissítés ENGEDÉLYEZVE', 'color': 'enabled'}
            logging.info(f"[WU_STATUS] Eredmény: {result['status']}")
            return result
        except Exception as e:
            logging.error(f"[WU_STATUS] Hiba: {e}")
            return {'status': 'Ismeretlen', 'color': 'unknown'}

    def disable_wu(self):
        logging.info("[API] disable_wu()")
        def worker():
            logging.info("[WU] WU driver letiltás indítása...")
            self.emit('task_start', {'task': 'disable_wu', 'title': 'WU Driver Letiltás'})
            self.emit('task_progress', {'task': 'disable_wu', 'log': 'WU driver letiltás...', 'indeterminate': True})
            try:
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate", 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 1)
                self.emit('task_progress', {'task': 'disable_wu', 'log': '✅ ExcludeWUDriversInQualityUpdate = 1'})
            except Exception as e:
                self.emit('task_progress', {'task': 'disable_wu', 'log': f'⚠ {e}'})
            self._run(['reg', 'add', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate',
                       '/v', 'ExcludeWUDriversInQualityUpdate', '/t', 'REG_DWORD', '/d', '1', '/f'])
            try:
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching", 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 0)
                self.emit('task_progress', {'task': 'disable_wu', 'log': '✅ SearchOrderConfig = 0'})
            except Exception as e:
                self.emit('task_progress', {'task': 'disable_wu', 'log': f'⚠ {e}'})
            self._run(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching',
                       '/v', 'SearchOrderConfig', '/t', 'REG_DWORD', '/d', '0', '/f'])
            self._run('net stop wuauserv & net start wuauserv', shell=True)
            self.emit('task_progress', {'task': 'disable_wu', 'log': '✅ WU szolgáltatás újraindítva'})
            self.emit('task_complete', {'task': 'disable_wu', 'status': '✅ WU driver letiltás kész!'})
        self._safe_thread('disable_wu', worker)

    def enable_wu(self):
        logging.info("[API] enable_wu()")
        def worker():
            logging.info("[WU_ENABLE] Worker indult - WU engedélyezés és reset...")
            self.emit('task_start', {'task': 'enable_wu', 'title': 'WU Driver Engedélyezés + Reset'})
            self.emit('task_progress', {'task': 'enable_wu', 'log': 'WU driver engedélyezés + teljes reset...', 'indeterminate': True})

            # Delete policy
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate", 0, winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key, "ExcludeWUDriversInQualityUpdate")
                logging.info("[WU_ENABLE] ExcludeWUDrivers policy törölve")
                self.emit('task_progress', {'task': 'enable_wu', 'log': '✅ ExcludeWUDrivers policy törölve'})
            except FileNotFoundError:
                logging.debug("[WU_ENABLE] Policy nem létezett")
                self.emit('task_progress', {'task': 'enable_wu', 'log': '  Policy nem létezett'})
            except Exception as e:
                logging.warning(f"[WU_ENABLE] Policy törlés hiba: {e}")
                self.emit('task_progress', {'task': 'enable_wu', 'log': f'⚠ {e}'})
                try:
                    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate", 0, winreg.KEY_WRITE) as key:
                        winreg.SetValueEx(key, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 0)
                except Exception:
                    pass

            # SearchOrderConfig = 1
            try:
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching", 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 1)
                logging.info("[WU_ENABLE] SearchOrderConfig = 1")
                self.emit('task_progress', {'task': 'enable_wu', 'log': '✅ SearchOrderConfig = 1'})
            except Exception as e:
                logging.warning(f"[WU_ENABLE] SearchOrderConfig hiba: {e}")
                self.emit('task_progress', {'task': 'enable_wu', 'log': f'⚠ {e}'})

            self._run(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching',
                       '/v', 'SearchOrderConfig', '/t', 'REG_DWORD', '/d', '1', '/f'])
            self._run(['reg', 'delete', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate',
                       '/v', 'ExcludeWUDriversInQualityUpdate', '/f'])

            # Stop services
            logging.info("[WU_ENABLE] Szolgáltatások leállítása...")
            for svc in ['wuauserv', 'bits', 'cryptsvc']:
                self._run(f'net stop {svc} /y', shell=True)
            time.sleep(2)

            # Delete SoftwareDistribution
            sysroot = os.environ.get('SYSTEMROOT', r'C:\Windows')
            sw_dist = os.path.join(sysroot, 'SoftwareDistribution')
            logging.info(f"[WU_ENABLE] SoftwareDistribution törlése: {sw_dist}")
            self.emit('task_progress', {'task': 'enable_wu', 'log': f'SoftwareDistribution törlése...'})
            for _ in range(3):
                try:
                    if os.path.exists(sw_dist):
                        shutil.rmtree(sw_dist, ignore_errors=False)
                        logging.info("[WU_ENABLE] SoftwareDistribution törölve")
                        self.emit('task_progress', {'task': 'enable_wu', 'log': '  ✅ Törölve'})
                        break
                except Exception as e:
                    logging.warning(f"[WU_ENABLE] SoftwareDistribution törlés újrapróbálás: {e}")
                    self.emit('task_progress', {'task': 'enable_wu', 'log': f'  ⚠ Újrapróbálás: {e}'})
                    time.sleep(3)

            # Rename catroot2
            catroot2 = os.path.join(sysroot, 'System32', 'catroot2')
            bak = catroot2 + '.bak'
            try:
                if os.path.exists(bak):
                    shutil.rmtree(bak, ignore_errors=True)
                if os.path.exists(catroot2):
                    os.rename(catroot2, bak)
                    logging.info("[WU_ENABLE] catroot2 átnevezve")
                    self.emit('task_progress', {'task': 'enable_wu', 'log': '✅ catroot2 átnevezve'})
            except Exception as e:
                logging.warning(f"[WU_ENABLE] catroot2 hiba: {e}")
                self.emit('task_progress', {'task': 'enable_wu', 'log': f'⚠ catroot2: {e}'})

            # Re-register DLLs
            logging.info("[WU_ENABLE] WU DLL-ek újraregisztrálása...")
            sys32 = os.path.join(sysroot, 'System32')
            for dll in ['wuaueng.dll', 'wuapi.dll', 'wups.dll', 'wups2.dll', 'wuwebv.dll', 'wucltux.dll']:
                fp = os.path.join(sys32, dll)
                if os.path.exists(fp):
                    self._run(f'regsvr32.exe /s "{fp}"', shell=True)
            self.emit('task_progress', {'task': 'enable_wu', 'log': '✅ WU DLL-ek újraregisztrálva'})

            # Winsock reset
            logging.info("[WU_ENABLE] Winsock reset...")
            self._run('netsh winsock reset', shell=True)

            # Start services
            logging.info("[WU_ENABLE] Szolgáltatások indítása...")
            for svc in ['cryptsvc', 'bits', 'wuauserv']:
                for _ in range(3):
                    res = self._run(f'net start {svc}', shell=True)
                    if res.returncode == 0 or 'already' in (res.stdout + res.stderr).lower():
                        break
                    time.sleep(3)

            self._run('wuauclt.exe /resetauthorization /detectnow', shell=True)
            self._run('UsoClient.exe StartScan', shell=True)
            logging.info("[WU_ENABLE] Kész!")
            self.emit('task_progress', {'task': 'enable_wu', 'log': '✅ Frissítés-keresés elindítva'})
            self.emit('task_complete', {'task': 'enable_wu', 'status': '✅ WU engedélyezés + reset kész!'})

        self._safe_thread('enable_wu', worker)

    def restart_wu(self):
        logging.info("[API] restart_wu()")
        def worker():
            logging.info("[WU_RESTART] Worker indult - szolgáltatások újraindítása...")
            self.emit('task_start', {'task': 'restart_wu', 'title': 'WU Szolgáltatások Újraindítása'})
            self.emit('task_progress', {'task': 'restart_wu', 'log': 'WU szolgáltatások újraindítása...', 'indeterminate': True})

            logging.info("[WU_RESTART] Szolgáltatások leállítása...")
            for svc in ['wuauserv', 'bits', 'cryptsvc', 'msiserver']:
                self._run(f'net stop {svc} /y', shell=True)
                self.emit('task_progress', {'task': 'restart_wu', 'log': f'  stop {svc}'})
            time.sleep(2)
            logging.info("[WU_RESTART] Szolgáltatások indítása...")
            for svc in ['rpcss', 'cryptsvc', 'bits', 'msiserver', 'wuauserv']:
                for _ in range(3):
                    res = self._run(f'net start {svc}', shell=True)
                    if res.returncode == 0 or 'already' in (res.stdout + res.stderr).lower():
                        break
                    time.sleep(3)
                self.emit('task_progress', {'task': 'restart_wu', 'log': f'  start {svc}'})
            self._run('wuauclt.exe /resetauthorization /detectnow', shell=True)
            self._run('UsoClient.exe StartScan', shell=True)
            logging.info("[WU_RESTART] Kész!")
            self.emit('task_progress', {'task': 'restart_wu', 'log': '✅ Frissítés-keresés elindítva'})
            self.emit('task_complete', {'task': 'restart_wu', 'status': '✅ WU szolgáltatások újraindítva!'})

        self._safe_thread('restart_wu', worker)

    # ================================================================
    # BACKUP / RESTORE
    # ================================================================
    def backup_third_party(self):
        logging.info("[API] backup_third_party()")
        dest = self.select_directory('Válassz mappát a driverek kimentéséhez')
        if not dest:
            logging.info("[BACKUP] Mégse - nincs mappa kiválasztva")
            return
        logging.info(f"[BACKUP] Third-party backup indítása -> {dest}")
        self._cancel_flag = False

        def worker():
            folder = os.path.join(dest, f"DriverDoktor_Export_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            logging.info(f"[BACKUP] Célmappa létrehozása: {folder}")
            os.makedirs(folder, exist_ok=True)
            self.emit('task_start', {'task': 'backup', 'title': 'Driver Exportálás'})
            self.emit('task_progress', {'task': 'backup', 'log': f'Célmappa: {folder}\nExportálás indítása...', 'indeterminate': True})

            logging.info("[BACKUP] DISM export-driver futtatása...")
            process = subprocess.Popen(
                ['dism', '/online', '/export-driver', f'/destination:{folder}'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                startupinfo=self._si, creationflags=self._nw, errors='replace')

            cancelled = False
            for line in process.stdout:
                if self._check_cancel():
                    process.terminate()
                    process.wait()  # Prevent zombie process
                    cancelled = True
                    break
                line = line.strip()
                if not line:
                    continue
                logging.debug(f"[BACKUP] DISM: {line[:100]}")
                m = re.search(r'(\d+)\s*(?:/|of)\s*(\d+)', line, re.I)
                if m:
                    self.emit('task_progress', {'task': 'backup', 'current': int(m.group(1)), 'total': int(m.group(2)),
                                                'counter': f'{m.group(1)}/{m.group(2)}', 'status': line[:60]})
                self.emit('task_progress', {'task': 'backup', 'log': line})
            process.wait()

            if cancelled:
                self.emit('task_complete', {'task': 'backup', 'status': '❗ Megszakítva!', 'log': '\n--- MEGSZAKÍTVA! ---'})
                return

            success = process.returncode == 0
            logging.info(f"[BACKUP] DISM befejezve, returncode={process.returncode}")
            self.emit('task_complete', {'task': 'backup',
                                        'status': f'{"✅ Sikeres export!" if success else "❌ Hiba!"} Mappa: {folder}',
                                        'log': f'\n--- {"Sikeres" if success else "Hibás"} export: {folder} ---'})
        self._safe_thread('backup', worker)

    def backup_all(self):
        logging.info("[API] backup_all()")
        dest = self.select_directory('Válassz mappát az ÖSSZES driver kimentéséhez')
        if not dest:
            logging.info("[BACKUP_ALL] Mégse - nincs mappa kiválasztva")
            return
        logging.info(f"[BACKUP_ALL] Összes driver backup indítása -> {dest}")
        self._cancel_flag = False

        def worker():
            folder = os.path.join(dest, f"DriverDoktor_FullExport_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(folder, exist_ok=True)
            self.emit('task_start', {'task': 'backup', 'title': 'ÖSSZES Driver Exportálása'})
            self.emit('task_progress', {'task': 'backup', 'log': 'Driver lista lekérdezése...', 'indeterminate': True})

            enum_res = self._run(['pnputil', '/enum-drivers'])
            all_infs = re.findall(r'(oem\d+\.inf)', enum_res.stdout, re.I)
            self.emit('task_progress', {'task': 'backup', 'log': f'OEM driverek: {len(all_infs)} db'})

            success = 0
            fail = 0
            cancelled = False
            for i, inf in enumerate(all_infs):
                if self._check_cancel():
                    cancelled = True
                    break
                inf_folder = os.path.join(folder, inf.replace('.inf', ''))
                os.makedirs(inf_folder, exist_ok=True)
                res = self._run(['pnputil', '/export-driver', inf, inf_folder])
                if res.returncode == 0:
                    success += 1
                else:
                    fail += 1
                self.emit('task_progress', {'task': 'backup', 'current': i + 1, 'total': len(all_infs),
                                            'counter': f'{i+1}/{len(all_infs)}', 'status': f'Export: {inf}'})

            if cancelled:
                self.emit('task_complete', {'task': 'backup', 'status': f'❗ Megszakítva! OEM: {success} db exportálva',
                                            'log': f'\n--- MEGSZAKÍTVA! Sikeres: {success}, Sikertelen: {fail} ---'})
                return

            # Copy inbox drivers (FileRepository + INF)
            if self._check_cancel():
                self.emit('task_complete', {'task': 'backup', 'status': f'❗ Megszakítva!', 'log': '\n--- MEGSZAKÍTVA! ---'})
                return
            self.emit('task_progress', {'task': 'backup', 'log': 'Windows inbox driverek másolása (FileRepository)...', 'indeterminate': True})
            driverstore = os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), 'System32', 'DriverStore', 'FileRepository')
            inbox_folder = os.path.join(folder, '_Windows_Inbox_Drivers')
            os.makedirs(inbox_folder, exist_ok=True)
            self._run(['robocopy', driverstore, inbox_folder, '/E', '/R:0', '/W:0', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP'])

            if self._check_cancel():
                self.emit('task_complete', {'task': 'backup', 'status': f'❗ Megszakítva!', 'log': '\n--- MEGSZAKÍTVA! ---'})
                return
            self.emit('task_progress', {'task': 'backup', 'log': 'Windows INF mappa másolása...'})
            inf_src = os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), 'INF')
            inbox_inf_folder = os.path.join(folder, '_Windows_Inbox_INF')
            os.makedirs(inbox_inf_folder, exist_ok=True)
            self._run(['robocopy', inf_src, inbox_inf_folder, '/E', '/R:0', '/W:0', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP'])

            total_size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fns in os.walk(folder) for f in fns
                             if os.path.exists(os.path.join(dp, f)))
            size_mb = total_size / (1024 * 1024)
            self.emit('task_complete', {'task': 'backup',
                                        'status': f'✅ Kész! OEM: {success} db ({fail} sikertelen), Inbox másolva. Méret: {size_mb:.0f} MB',
                                        'log': f'\n--- Export kész: {folder} ({size_mb:.0f} MB) | Sikeres: {success}, Sikertelen: {fail} ---'})
        self._safe_thread('backup', worker)

    def create_restore_point(self):
        logging.info("[API] create_restore_point()")
        def worker():
            logging.info("[RESTORE_POINT] Worker indult - visszaállítási pont létrehozása...")
            desc = f"DriverDoktor_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            logging.info(f"[RESTORE_POINT] Név: {desc}")
            self.emit('task_start', {'task': 'rp', 'title': 'Visszaállítási Pont'})
            self.emit('task_progress', {'task': 'rp', 'log': 'Rendszervédelem engedélyezése...', 'indeterminate': True})

            # 1) Enable System Restore on C: (force enable even if disabled)
            logging.info("[RESTORE_POINT] Rendszervédelem engedélyezése...")
            enable_ps = '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; try { Enable-ComputerRestore -Drive "C:\\" -ErrorAction Stop; Write-Output "OK" } catch { Write-Output "FAIL: $($_.Exception.Message)" }'
            enable_res = self._run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", enable_ps], encoding='utf-8')
            enable_out = (enable_res.stdout or '').strip()
            if 'FAIL' in enable_out:
                logging.warning(f"[RESTORE_POINT] Enable-ComputerRestore hiba: {enable_out}")
                # Try via registry + vssadmin as fallback
                self.emit('task_progress', {'task': 'rp', 'log': f'⚠ Enable-ComputerRestore hiba: {enable_out}\nRegistry + vssadmin fallback...'})
                self._run(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore', '/v', 'DisableSR', '/t', 'REG_DWORD', '/d', '0', '/f'])
                self._run(['vssadmin', 'resize', 'shadowstorage', '/for=C:', '/on=C:', '/maxsize=5%'])
                # Retry enable
                enable_res2 = self._run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", enable_ps], encoding='utf-8')
                enable_out2 = (enable_res2.stdout or '').strip()
                if 'FAIL' in enable_out2:
                    logging.error(f"[RESTORE_POINT] Rendszervédelem nem kapcsolható be: {enable_out2}")
                    self.emit('task_complete', {'task': 'rp', 'status': f'❌ Rendszervédelem nem kapcsolható be: {enable_out2}'})
                    return
                logging.info("[RESTORE_POINT] Rendszervédelem bekapcsolva (fallback)")
                self.emit('task_progress', {'task': 'rp', 'log': '✅ Rendszervédelem bekapcsolva (fallback)'})
            else:
                logging.info("[RESTORE_POINT] Rendszervédelem bekapcsolva")
                self.emit('task_progress', {'task': 'rp', 'log': '✅ Rendszervédelem bekapcsolva'})

            # 2) Disable 24-hour frequency limit
            logging.info("[RESTORE_POINT] 24 órás limit feloldása...")
            self._run(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore', 
                       '/v', 'SystemRestorePointCreationFrequency', '/t', 'REG_DWORD', '/d', '0', '/f'])

            # 3) Create restore point
            logging.info("[RESTORE_POINT] Checkpoint-Computer futtatása...")
            self.emit('task_progress', {'task': 'rp', 'log': f'Visszaállítási pont: {desc}', 'status': 'Pont létrehozása...'})
            create_ps = f'[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; try {{ Checkpoint-Computer -Description "{desc}" -RestorePointType "MODIFY_SETTINGS" -ErrorAction Stop; Write-Output "OK" }} catch {{ Write-Output "FAIL: $($_.Exception.Message)" }}'
            res = self._run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", create_ps], encoding='utf-8')
            create_out = (res.stdout or '').strip()
            logging.debug(f"[RESTORE_POINT] Checkpoint result: {create_out}")

            # 4) Verify
            logging.info("[RESTORE_POINT] Ellenőrzés...")
            verify_ps = f'[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; (Get-ComputerRestorePoint | Where-Object {{ $_.Description -eq "{desc}" }}).Description'
            verify_res = self._run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", verify_ps], encoding='utf-8')
            verified = desc in (verify_res.stdout or '')
            logging.debug(f"[RESTORE_POINT] Verified: {verified}")

            if 'OK' in create_out and verified:
                logging.info(f"[RESTORE_POINT] Sikeresen létrehozva: {desc}")
                self.emit('task_complete', {'task': 'rp', 'status': f'✅ Visszaállítási pont létrehozva: {desc}'})
            elif 'OK' in create_out:
                logging.warning("[RESTORE_POINT] Lefutott de nem ellenőrizhető (késleltetett létrehozás?)")
                self.emit('task_complete', {'task': 'rp', 'status': '⚠ Visszaállítási pont létrehozás elindítva (ellenőrzés később)'})
            else:
                logging.error(f"[RESTORE_POINT] Hiba: {create_out}")
                self.emit('task_complete', {'task': 'rp', 'status': f'❌ Hiba: {create_out}'})
        self._safe_thread('rp', worker)

    def restore_online(self):
        logging.info("[API] restore_online()")
        source = self.select_directory('ÉLŐ MÓD: Válassz kimentett driver mappát')
        if not source:
            logging.info("[RESTORE] Mégse - nincs forrás kiválasztva")
            return
        logging.info(f"[RESTORE] Online restore indítása: source={source}")
        self._run_restore(online=True, source=source, target=None)

    def restore_offline(self):
        logging.info("[API] restore_offline()")
        target = self.select_directory('OFFLINE MÓD: 1. Válaszd ki a HALOTT WINDOWS meghajtóját')
        if not target:
            logging.info("[RESTORE] Mégse - nincs cél kiválasztva")
            return
        target = os.path.splitdrive(os.path.abspath(target))[0] + "\\"
        logging.info(f"[RESTORE] Offline target: {target}")
        source = self.select_directory('OFFLINE MÓD: 2. Válassz kimentett driver mappát')
        if not source:
            logging.info("[RESTORE] Mégse - nincs forrás kiválasztva")
            return
        logging.info(f"[RESTORE] Offline restore indítása: source={source}, target={target}")
        self._run_restore(online=False, source=source, target=target)

    def _run_restore(self, online, source, target):
        logging.info(f"[RESTORE] _run_restore: online={online}, source={source}, target={target}")
        self._cancel_flag = False
        def worker():
            mode = 'Élő' if online else 'Offline'
            logging.info(f"[RESTORE] Worker indult - {mode} mód")
            self.emit('task_start', {'task': 'restore', 'title': f'Driver Visszaállítás ({mode})'})
            self.emit('task_progress', {'task': 'restore', 'log': f'=== {mode.upper()} RESTORE ===\nForrás: {source}\nCél: {target or "jelenlegi rendszer"}\n', 'indeterminate': True})

            norm_source = os.path.normpath(source)
            norm_target = os.path.normpath(target) if target else None
            logging.debug(f"[RESTORE] norm_source={norm_source}, norm_target={norm_target}")

            # Detect source type
            is_wim_extract = not online and "Windows_Gyari_Alap_Driverek" in norm_source
            inbox_subfolder = os.path.join(norm_source, "_Windows_Inbox_Drivers") if not online else None
            has_inbox_subfolder = inbox_subfolder and os.path.isdir(inbox_subfolder)
            logging.info(f"[RESTORE] Típus detektálás: is_wim_extract={is_wim_extract}, has_inbox_subfolder={has_inbox_subfolder}")

            def force_copy(src, dst):
                """Robocopy-based forced copy with fallback for inbox/system drivers."""
                logging.debug(f"[RESTORE] force_copy: {src} -> {dst}")
                if not os.path.exists(src):
                    logging.warning(f"[RESTORE] Forrás nem létezik: {src}")
                    return
                os.makedirs(dst, exist_ok=True)
                self.emit('task_progress', {'task': 'restore', 'log': f'\n  Robocopy indul: {os.path.basename(src)} -> {os.path.basename(dst)}\n  (Backup mód - Windows jogosultságok megkerülése)'})
                cmd = ['robocopy', src, dst, '/E', '/ZB', '/R:1', '/W:1', '/COPY:DAT', '/NC', '/NS', '/NFL', '/NDL', '/NP']
                res = self._run(cmd)

                if res.returncode < 8:
                    logging.info(f"[RESTORE] Robocopy sikeres, returncode={res.returncode}")
                    self.emit('task_progress', {'task': 'restore', 'log': f'  ✅ Sikeres robocopy kényszerítés ({res.returncode})'})
                else:
                    self.emit('task_progress', {'task': 'restore', 'log': f'  ⚠️ Robocopy hiba ({res.returncode}), végső tartalék: mappánkénti jogszerzés (lassabb)...'})
                    for root, _, files in os.walk(src):
                        if self._cancel_flag: return
                        rel = os.path.relpath(root, src)
                        target_dir = os.path.join(dst, rel) if rel != '.' else dst
                        os.makedirs(target_dir, exist_ok=True)

                        for f in files:
                            if self._cancel_flag: return
                            sfile = os.path.join(root, f)
                            dfile = os.path.join(target_dir, f)
                            if os.path.exists(dfile):
                                self._run(f'takeown /f "{dfile}" /A', shell=True)
                                self._run(f'icacls "{dfile}" /grant *S-1-5-32-544:F', shell=True)
                                self._run(f'attrib -R "{dfile}"', shell=True)
                            try:
                                shutil.copy2(sfile, dfile)
                            except Exception as e:
                                self.emit('task_progress', {'task': 'restore', 'log': f'❌ Hiba ({f}): {e}'})
                    self.emit('task_progress', {'task': 'restore', 'log': '  ✅ Fallback másolás befejeződött.'})

            def run_dism_add_driver(driver_path, label=""):
                """Run DISM /Add-Driver on a folder with /Recurse. Returns (returncode, cancelled)."""
                scratch = os.path.join(norm_target, "Scratch")
                os.makedirs(scratch, exist_ok=True)
                cmd = ['dism', f'/Image:{norm_target}', '/Add-Driver', f'/Driver:{driver_path}', '/Recurse', '/ForceUnsigned', f'/ScratchDir:{scratch}']
                self.emit('task_progress', {'task': 'restore', 'log': f'{label}Parancs: {" ".join(cmd)}'})
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                           startupinfo=self._si, creationflags=self._nw, errors='replace')
                cancelled = False
                for line in process.stdout:
                    if self._check_cancel():
                        process.terminate()
                        cancelled = True
                        break
                    stripped = line.strip()
                    if stripped:
                        self.emit('task_progress', {'task': 'restore', 'log': stripped})
                process.wait()
                if not cancelled:
                    self.emit('task_progress', {'task': 'restore', 'log': f'Return code: {process.returncode}'})
                return (process.returncode, cancelled)

            if online:
                cmd = ['pnputil', '/add-driver', f"{norm_source}\\*.inf", '/subdirs', '/install']
                self.emit('task_progress', {'task': 'restore', 'log': f'Parancs: {" ".join(cmd)}'})
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                           startupinfo=self._si, creationflags=self._nw, errors='replace')
                cancelled = False
                for line in process.stdout:
                    if self._check_cancel():
                        process.terminate()
                        cancelled = True
                        break
                    self.emit('task_progress', {'task': 'restore', 'log': line.strip()})
                process.wait()
                if cancelled:
                    self.emit('task_complete', {'task': 'restore', 'status': '❗ Megszakítva!'})
                    return
                self.emit('task_progress', {'task': 'restore', 'log': f'\nReturn code: {process.returncode}'})
            elif is_wim_extract:
                # WIM-ből kimentett driverek (Windows_Gyari_Alap_Driverek_*)
                # Ezek FileRepository + INF formátumban vannak
                self.emit('task_progress', {'task': 'restore', 'log': 'WIM-ből kimentett gyári driverek visszaállítása...'})
                new_format_repo = os.path.join(norm_source, "FileRepository")
                new_format_inf = os.path.join(norm_source, "INF")
                target_repo = os.path.join(norm_target, "Windows", "System32", "DriverStore", "FileRepository")
                target_inf = os.path.join(norm_target, "Windows", "INF")

                try:
                    if os.path.exists(new_format_repo):
                        self.emit('task_progress', {'task': 'restore', 'log': '1/2 FileRepository és INF fizikai másolása...'})
                        force_copy(new_format_repo, target_repo)
                        if self._check_cancel():
                            self.emit('task_complete', {'task': 'restore', 'status': '❗ Megszakítva!'})
                            return
                        if os.path.exists(new_format_inf):
                            force_copy(new_format_inf, target_inf)
                            if self._check_cancel():
                                self.emit('task_complete', {'task': 'restore', 'status': '❗ Megszakítva!'})
                                return
                    else:
                        self.emit('task_progress', {'task': 'restore', 'log': '1/2 DriverStore fizikai másolása...'})
                        force_copy(norm_source, target_repo)
                        if self._check_cancel():
                            self.emit('task_complete', {'task': 'restore', 'status': '❗ Megszakítva!'})
                            return

                    self.emit('task_progress', {'task': 'restore', 'log': '✅ Fizikai másolás kész!'})
                except Exception as e:
                    err_msg = str(e)
                    if len(err_msg) > 300: err_msg = err_msg[:300] + "..."
                    self.emit('task_progress', {'task': 'restore', 'log': f'⚠️ Másolási hiba: {err_msg}'})

                # DISM regisztrálás a fizikai másolás után
                self.emit('task_progress', {'task': 'restore', 'log': '\n2/2 DISM driver regisztrálás (inbox drivereknél sok hiba normális)...'})
                _, dism_cancelled = run_dism_add_driver(norm_source, "")
                if dism_cancelled:
                    self.emit('task_complete', {'task': 'restore', 'status': '❗ Megszakítva!'})
                    return
                self.emit('task_progress', {'task': 'restore', 'log': '✅ A fizikai másolás + DISM regisztrálás kész. Az inbox driverek a másolásnak köszönhetően elérhetőek.'})

            elif has_inbox_subfolder:
                # DriverDoktor_FullExport / ALL_Driver_Backup formátum: _Windows_Inbox_Drivers + oem almappák
                self.emit('task_progress', {'task': 'restore', 'log': 'Teljes export formátum észlelve (DriverDoktor_FullExport / ALL_Driver_Backup).\n'
                                            'Az inbox drivereket fizikailag másoljuk (DISM nem tudja telepíteni őket),\n'
                                            'az OEM drivereket DISM-mel regisztráljuk.\n'})

                # 1) Inbox driverek fizikai másolása (FileRepository + INF)
                target_repo = os.path.join(norm_target, "Windows", "System32", "DriverStore", "FileRepository")
                target_inf = os.path.join(norm_target, "Windows", "INF")
                inbox_inf_subfolder = os.path.join(norm_source, "_Windows_Inbox_INF")
                self.emit('task_progress', {'task': 'restore', 'log': '--- 1. LÉPÉS: Inbox driverek fizikai másolása a DriverStore-ba ---'})
                try:
                    force_copy(inbox_subfolder, target_repo)
                    if self._check_cancel():
                        self.emit('task_complete', {'task': 'restore', 'status': '❗ Megszakítva!'})
                        return
                    if os.path.isdir(inbox_inf_subfolder):
                        self.emit('task_progress', {'task': 'restore', 'log': 'Windows INF mappa visszamásolása (új formátumú backup)...'})
                        force_copy(inbox_inf_subfolder, target_inf)
                        if self._check_cancel():
                            self.emit('task_complete', {'task': 'restore', 'status': '❗ Megszakítva!'})
                            return
                    else:
                        # Régi backup: nincs _Windows_Inbox_INF, ezért a FileRepository almappáiból
                        # kiszedjük az .inf fájlokat és bemásoljuk a Windows\INF-be
                        self.emit('task_progress', {'task': 'restore', 'log': 'Régi backup formátum: _Windows_Inbox_INF nem található.\n'
                                                    'INF fájlok kinyerése a FileRepository almappáiból...'})
                        os.makedirs(target_inf, exist_ok=True)
                        inf_count = 0
                        for repo_dir in os.listdir(inbox_subfolder):
                            repo_path = os.path.join(inbox_subfolder, repo_dir)
                            if not os.path.isdir(repo_path):
                                continue
                            for fname in os.listdir(repo_path):
                                if fname.lower().endswith('.inf'):
                                    src_inf = os.path.join(repo_path, fname)
                                    dst_inf = os.path.join(target_inf, fname)
                                    try:
                                        shutil.copy2(src_inf, dst_inf)
                                        inf_count += 1
                                    except Exception:
                                        pass
                        self.emit('task_progress', {'task': 'restore', 'log': f'✅ {inf_count} db .inf fájl kinyerve a Windows\\INF mappába (.pnf-eket a Windows legenerálja bootoláskor).'})
                    self.emit('task_progress', {'task': 'restore', 'log': '✅ Inbox driverek fizikai másolása kész!'})
                except Exception as e:
                    err_msg = str(e)
                    if len(err_msg) > 300: err_msg = err_msg[:300] + "..."
                    self.emit('task_progress', {'task': 'restore', 'log': f'⚠️ Inbox másolási hiba: {err_msg}'})

                # 2) OEM driverek DISM-mel (almappák, amik nem _Windows_Inbox_Drivers)
                oem_folders = []
                for item in os.listdir(norm_source):
                    item_path = os.path.join(norm_source, item)
                    if os.path.isdir(item_path) and item not in ("_Windows_Inbox_Drivers", "_Windows_Inbox_INF"):
                        # Check if folder contains any .inf files (directly or in subfolders)
                        has_inf = any(f.lower().endswith('.inf') for _, _, fns in os.walk(item_path) for f in fns)
                        if has_inf:
                            oem_folders.append(item_path)

                if oem_folders:
                    self.emit('task_progress', {'task': 'restore', 'log': f'\n--- 2. LÉPÉS: {len(oem_folders)} db OEM driver mappa DISM regisztrálása ---'})
                    for i, oem_path in enumerate(oem_folders):
                        if self._check_cancel():
                            self.emit('task_complete', {'task': 'restore', 'status': '❗ Megszakítva!'})
                            return
                        self.emit('task_progress', {'task': 'restore', 'log': f'\n[{i+1}/{len(oem_folders)}] {os.path.basename(oem_path)}:'})
                        _, dism_cancelled = run_dism_add_driver(oem_path, "  ")
                        if dism_cancelled:
                            self.emit('task_complete', {'task': 'restore', 'status': '❗ Megszakítva!'})
                            return
                    self.emit('task_progress', {'task': 'restore', 'log': '\n✅ OEM driverek DISM regisztrálása kész!'})
                else:
                    self.emit('task_progress', {'task': 'restore', 'log': '\nNincs OEM driver mappa a backup-ban.'})

            else:
                # Egyéb mappa (pl. DriverDoktor_Export / Driver_Backup third-party export) — tisztán DISM
                _, dism_cancelled = run_dism_add_driver(norm_source, "")
                if dism_cancelled:
                    self.emit('task_complete', {'task': 'restore', 'status': '❗ Megszakítva!'})
                    return

            # Post-install
            if online:
                is_pe = os.environ.get('SystemDrive', 'C:') == 'X:'
                if not is_pe:
                    self.emit('task_progress', {'task': 'restore', 'log': 'Hardverváltozások keresése...'})
                    time.sleep(1.5)
                    self._run(['pnputil', '/scan-devices'])
                    time.sleep(3.5)
                    self.emit('task_progress', {'task': 'restore', 'log': '✅ Scan kész!'})
            else:
                # Automata PnP rescan beállítása az asztal betöltésére
                self.emit('task_progress', {'task': 'restore', 'log': 'Első bejelentkezési rescan script beállítása...'})
                startup_dir = os.path.join(target, "ProgramData", "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
                os.makedirs(startup_dir, exist_ok=True)
                bat_path = os.path.join(startup_dir, "auto_pnputil_scan.bat")
                bat_content = (
                    '@echo off\n'
                    'set LOGFILE="%SystemDrive%\\Users\\Public\\driver_startup_log.txt"\n'
                    'echo [%DATE% %TIME%] Boot rescan indult... >> %LOGFILE%\n'
                    'pnputil /scan-devices >> %LOGFILE% 2>&1\n'
                    'echo [%DATE% %TIME%] Kesz! >> %LOGFILE%\n'
                    'ping 127.0.0.1 -n 3 > nul\n'
                    '(goto) 2>nul & del "%~f0"\n'
                )
                try:
                    with open(bat_path, 'w', encoding='utf-8') as f:
                        f.write(bat_content)
                    self.emit('task_progress', {'task': 'restore', 'log': '✅ Startup script elhelyezve.'})
                except Exception as e:
                    self.emit('task_progress', {'task': 'restore', 'log': f'⚠ Script írási hiba: {e}'})

            self.emit('task_progress', {'task': 'restore', 'log': '\n==== BEFEJEZVE ===='})
            self.emit('task_complete', {'task': 'restore', 'status': '✅ Visszaállítás befejezve!'})

        self._safe_thread('restore', worker)

    def extract_wim(self):
        logging.info("[API] extract_wim()")
        wim_path = self.select_file('Válaszd ki az install.wim fájlt', 'WIM fájlok (*.wim)|*.wim')
        if not wim_path:
            logging.info("[WIM] Mégse - nincs WIM kiválasztva")
            return
        logging.info(f"[WIM] WIM fájl: {wim_path}")
        if wim_path.lower().endswith(".esd"):
            logging.error("[WIM] ESD fájl nem támogatott!")
            self.emit('alert', {'title': 'Hiba', 'message': 'ESD fájl nem támogatott. Kérlek, használj install.wim fájlt!'})
            return
        dest = self.select_directory('Válassz ideiglenes mappát a kicsomagoláshoz')
        if not dest:
            logging.info("[WIM] Mégse - nincs célmappa kiválasztva")
            return
        logging.info(f"[WIM] Célmappa: {dest}")
        self._cancel_flag = False

        def worker():
            logging.info("[WIM] Worker indult - WIM kinyerés...")
            self.emit('task_start', {'task': 'wim', 'title': 'WIM Driver Kinyerés'})
            wim = os.path.abspath(wim_path).replace("/", "\\")
            # A WIM csatolási mappának a C: meghajtón kell lennie (NTFS), mert a cserélhető meghajtókat (USB) a DISM visszautasítja
            sys_temp = os.environ.get('TEMP', 'C:\\Temp')
            mount_dir = os.path.join(sys_temp, f"WIM_Mount_Temp_{int(time.time())}")
            target_folder = os.path.join(dest, f"Windows_Gyari_Alap_Driverek_{datetime.now().strftime('%Y%m%d_%H%M')}")
            logging.info(f"[WIM] Mount dir: {mount_dir}")
            logging.info(f"[WIM] Target folder: {target_folder}")

            if os.path.exists(mount_dir):
                logging.debug("[WIM] Régi mount dir törlése...")
                shutil.rmtree(mount_dir, ignore_errors=True)
            os.makedirs(mount_dir, exist_ok=True)
            os.makedirs(target_folder, exist_ok=True)

            try:
                # Cancel check before mount
                if self._check_cancel():
                    self.emit('task_complete', {'task': 'wim', 'status': '❗ Megszakítva!'})
                    return

                logging.info("[WIM] DISM Mount-Image futtatása...")
                self.emit('task_progress', {'task': 'wim', 'log': 'WIM csatolás (ez 4-5 perc)...', 'indeterminate': True,
                                            'counter': '1/3', 'status': 'Képfájl csatolása...'})
                res = self._run(["dism", "/Mount-Image", f"/ImageFile:{wim}", "/Index:1", f"/MountDir:{mount_dir}", "/ReadOnly"])
                if res.returncode != 0:
                    logging.error(f"[WIM] DISM Mount hiba: {res.stdout} {res.stderr}")
                    raise Exception(f"DISM Mount hiba: {res.stdout} {res.stderr}")
                
                # Cancel check after mount (will unmount in except)
                if self._check_cancel():
                    raise Exception("Megszakítva a felhasználó által")
                
                logging.info("[WIM] WIM csatolva, fájlok másolása...")

                self.emit('task_progress', {'task': 'wim', 'log': 'Fájlok másolása...', 'counter': '2/3', 'status': 'Gyári driverek másolása...'})
                
                driverstore = os.path.join(mount_dir, "Windows", "System32", "DriverStore", "FileRepository")
                target_repo = os.path.join(target_folder, "FileRepository")
                if os.path.exists(driverstore):
                    logging.info(f"[WIM] FileRepository másolása: {driverstore} -> {target_repo}")
                    shutil.copytree(driverstore, target_repo, dirs_exist_ok=True)
                else:
                    logging.error("[WIM] FileRepository nem található!")
                    raise Exception("FileRepository nem található a WIM-ben!")

                inf_dir = os.path.join(mount_dir, "Windows", "INF")
                target_inf = os.path.join(target_folder, "INF")
                if os.path.exists(inf_dir):
                    logging.info(f"[WIM] INF mappa másolása: {inf_dir} -> {target_inf}")
                    shutil.copytree(inf_dir, target_inf, dirs_exist_ok=True)

                logging.info("[WIM] WIM leválasztása...")
                self.emit('task_progress', {'task': 'wim', 'log': 'WIM leválasztása...', 'counter': '3/3', 'status': 'Takarítás...'})
                self._run(["dism", "/Unmount-Image", f"/MountDir:{mount_dir}", "/Discard"])
                shutil.rmtree(mount_dir, ignore_errors=True)

                logging.info(f"[WIM] Kész! Kimenet: {target_folder}")
                self.emit('task_complete', {'task': 'wim', 'status': f'✅ Gyári driverek kimentve: {target_folder}',
                                            'log': f'\n✅ Kész! Mappa: {target_folder}'})
            except Exception as e:
                logging.error(f"[WIM] Hiba: {e}")
                logging.error(traceback.format_exc())
                self._run(["dism", "/Unmount-Image", f"/MountDir:{mount_dir}", "/Discard"])
                shutil.rmtree(mount_dir, ignore_errors=True)
                self.emit('task_error', {'task': 'wim', 'error': str(e)})
                self.emit('task_complete', {'task': 'wim', 'status': f'❌ Hiba: {e}'})

        self._safe_thread('wim', worker)


# ================================================================
# CLI MÓD (WinPE kompatibilis)
# ================================================================
def run_cli_mode():
    """Parancssoros mód - működik WinPE-ben is GUI nélkül."""
    import argparse
    
    print("=" * 60)
    print("  DriverDoktor CLI - Parancssoros mód")
    print("  (WinPE kompatibilis)")
    print("=" * 60)
    
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    nw = subprocess.CREATE_NO_WINDOW
    
    target_os = None
    
    def run_cmd(cmd, shell=False):
        try:
            if shell:
                return subprocess.run(cmd, shell=True, capture_output=True, text=True, startupinfo=si, creationflags=nw, timeout=120)
            else:
                return subprocess.run(cmd, capture_output=True, text=True, startupinfo=si, creationflags=nw, timeout=120)
        except Exception as e:
            class DummyRes:
                returncode = 1
                stdout = ""
                stderr = str(e)
            return DummyRes()
    
    def list_drivers(all_drivers=False):
        """Driver lista megjelenítése."""
        print("\n📋 Driverek listázása...")
        
        if target_os:
            # Offline mód
            res = run_cmd(['dism', f'/Image:{target_os}', '/Get-Drivers', '/Format:Table'])
        else:
            res = run_cmd(['pnputil', '/enum-drivers'])
        
        if res.returncode != 0:
            print(f"❌ Hiba: {res.stderr}")
            return []
        
        drivers = []
        lines = res.stdout.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # pnputil formátum: "oem123.inf" vagy "Published Name: oem123.inf"
            if '.inf' in line.lower():
                parts = line.split()
                for p in parts:
                    if '.inf' in p.lower():
                        inf_name = p.strip(':').strip()
                        if not all_drivers and not inf_name.lower().startswith('oem'):
                            continue
                        if inf_name not in drivers:
                            drivers.append(inf_name)
        
        if drivers:
            print(f"\n{'Third-party' if not all_drivers else 'Összes'} driver ({len(drivers)} db):")
            print("-" * 40)
            for i, d in enumerate(drivers, 1):
                print(f"  {i:3}. {d}")
        else:
            print("Nincs találat.")
        
        return drivers
    
    def delete_drivers(drivers, force=False):
        """Driverek törlése."""
        print(f"\n🗑️  {len(drivers)} driver törlése...")
        
        success = 0
        fail = 0
        
        for d in drivers:
            print(f"  Törlés: {d}...", end=" ")
            
            if target_os:
                res = run_cmd(['dism', f'/Image:{target_os}', '/Remove-Driver', f'/Driver:{d}'])
            else:
                res = run_cmd(['pnputil', '/delete-driver', d, '/uninstall', '/force'])
            
            if res.returncode == 0 or 'deleted' in res.stdout.lower() or 'törölve' in res.stdout.lower():
                print("✅")
                success += 1
            else:
                print("❌")
                fail += 1
        
        print(f"\n--- Eredmény: ✅ {success} sikeres, ❌ {fail} sikertelen ---")
        return success, fail
    
    def export_drivers(output_path):
        """Driver export DISM-mel."""
        print(f"\n💾 Driverek mentése: {output_path}")
        
        os.makedirs(output_path, exist_ok=True)
        
        if target_os:
            res = run_cmd(['dism', f'/Image:{target_os}', '/Export-Driver', f'/Destination:{output_path}'])
        else:
            res = run_cmd(['dism', '/Online', '/Export-Driver', f'/Destination:{output_path}'])
        
        if res.returncode == 0:
            print("✅ Mentés sikeres!")
            return True
        else:
            print(f"❌ Hiba: {res.stderr}")
            return False
    
    def set_target(path):
        """Cél OS beállítása (offline mód)."""
        nonlocal target_os
        if path and os.path.isdir(os.path.join(path, 'Windows')):
            target_os = path
            print(f"✅ Cél OS: {target_os}")
            return True
        elif path:
            print(f"❌ Nem található Windows mappa: {path}")
            return False
        else:
            target_os = None
            print("✅ Visszaállítva: jelenlegi rendszer")
            return True
    
    # Interaktív menü
    while True:
        print("\n" + "=" * 40)
        if target_os:
            print(f"  [Offline mód: {target_os}]")
        print("  1. Third-party driverek listázása")
        print("  2. ÖSSZES driver listázása (veszélyes!)")
        print("  3. Driver(ek) törlése")
        print("  4. Driverek mentése (export)")
        print("  5. Cél OS váltása (offline)")
        print("  6. Hardver újraszkennelés")
        print("  0. Kilépés")
        print("=" * 40)
        
        try:
            choice = input("Választás: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        
        if choice == '1':
            list_drivers(all_drivers=False)
        
        elif choice == '2':
            list_drivers(all_drivers=True)
        
        elif choice == '3':
            all_mode = input("Összes driver mód? (i/n): ").strip().lower() == 'i'
            drivers = list_drivers(all_drivers=all_mode)
            if not drivers:
                continue
            
            sel = input("Törlendő sorszámok (pl: 1,3,5 vagy 'mind'): ").strip()
            
            if sel.lower() == 'mind':
                to_delete = drivers
            else:
                indices = [int(x.strip())-1 for x in sel.split(',') if x.strip().isdigit()]
                to_delete = [drivers[i] for i in indices if 0 <= i < len(drivers)]
            
            if to_delete:
                confirm = input(f"Biztosan törölsz {len(to_delete)} drivert? (i/n): ").strip().lower()
                if confirm == 'i':
                    delete_drivers(to_delete)
        
        elif choice == '4':
            path = input("Mentés helye (mappa): ").strip()
            if path:
                export_drivers(path)
        
        elif choice == '5':
            path = input("Cél OS path (üres = jelenlegi): ").strip()
            set_target(path if path else None)
        
        elif choice == '6':
            if target_os:
                print("❌ Offline módban nem elérhető.")
            else:
                print("🔄 Hardver újraszkennelés...")
                res = run_cmd(['pnputil', '/scan-devices'])
                if res.returncode == 0:
                    print("✅ Kész!")
                else:
                    print(f"❌ Hiba: {res.stderr}")
        
        elif choice == '0':
            print("Viszlát!")
            break
        
        else:
            print("❌ Érvénytelen választás!")


# ================================================================
# MAIN
# ================================================================
if __name__ == "__main__":
    # Ha --progress argumentummal indítottuk, csak a progress ablakot nyitjuk meg
    if len(sys.argv) >= 3 and sys.argv[1] == '--progress':
        log_path = sys.argv[2]
        run_progress_window(log_path)
        sys.exit(0)
    
    # CLI mód
    if '--cli' in sys.argv:
        if not is_admin():
            print("❌ Rendszergazdai jogosultság szükséges!")
            print("   Futtasd rendszergazdaként!")
            input("Nyomj ENTER-t a kilépéshez...")
            sys.exit(1)
        run_cli_mode()
        sys.exit(0)
    
    if not is_admin():
        params = ' '.join([f'"{arg}"' for arg in sys.argv[1:]])
        if getattr(sys, 'frozen', False):
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        else:
            script = sys.argv[0]
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
        sys.exit()

    # Logging
    log_filename = os.path.join(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)), "DriverDoktor_debug.log")
    try:
        logging.basicConfig(filename=log_filename, level=logging.DEBUG,
                            format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S', encoding='utf-8')
    except Exception:
        logging.basicConfig(level=logging.DEBUG)

    def global_exception_handler(exc_type, exc_value, exc_traceback):
        global _webview_error
        err_str = str(exc_value)
        logging.exception("FATÁLIS HIBA:", exc_info=(exc_type, exc_value, exc_traceback))
        # WebView2 hibák detektálása
        if 'WebView2' in err_str or 'ICoreWebView2' in err_str or '.NET' in err_str:
            logging.error("[MAIN] WebView2 hiba detektálva exception handler-ben!")
            _webview_error.set()
    sys.excepthook = global_exception_handler

    def thread_exception_handler(args):
        global _webview_error
        err_str = str(args.exc_value)
        logging.exception("HÁTTÉRSZÁL HIBA:", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        if 'WebView2' in err_str or 'ICoreWebView2' in err_str or '.NET' in err_str:
            logging.error("[MAIN] WebView2 hiba detektálva szál exception handler-ben!")
            _webview_error.set()
    threading.excepthook = thread_exception_handler

    logging.info("=" * 50)
    logging.info("DriverDoktor ELINDITVA")
    logging.info(f"Futtatasi konyvtar: {os.getcwd()}")
    logging.info("=" * 50)

    # WebView2 Runtime verzió ellenőrzés induláskor
    wv2_ok, wv2_info = check_webview2_runtime()
    if wv2_ok:
        logging.info(f"[INIT] WebView2 Runtime OK: v{wv2_info}")
    else:
        logging.error(f"[INIT] WebView2 Runtime hiba: {wv2_info}")
        show_webview2_error(wv2_info)

    # Hardware rendering (gyors) - az autofix progress külön ablakban jelenik meg

    api = DriverToolApi()
    html_path = resource_path('ui.html')

    window = webview.create_window(
        'DriverDoktor',
        url=html_path,
        js_api=api,
        width=1200, height=780,
        min_size=(900, 600)
    )

    def on_start():
        api.set_window(window)

    # Watchdog: ha 15mp alatt nem indul el a GUI, bezárja az ablakot és CLI-re vált
    def webview_watchdog():
        global _webview_ready, _webview_error
        TIMEOUT = 15  # seconds
        start = time.time()
        while time.time() - start < TIMEOUT:
            if _webview_ready.is_set():
                logging.info("[WATCHDOG] WebView2 sikeresen elindult")
                return  # GUI OK
            if _webview_error.is_set():
                logging.error("[WATCHDOG] WebView2 hiba detektálva, ablak bezárása...")
                time.sleep(0.5)  # Adj időt a log kiírására
                try:
                    window.destroy()
                except Exception:
                    pass
                return
            time.sleep(0.25)
        # Timeout
        logging.error(f"[WATCHDOG] {TIMEOUT}s timeout - WebView2 nem válaszol, ablak bezárása...")
        _webview_error.set()
        try:
            window.destroy()
        except Exception:
            pass

    watchdog_thread = threading.Thread(target=webview_watchdog, daemon=True)
    watchdog_thread.start()

    gui_failed = False
    try:
        logging.info("[MAIN] webview.start() hívása...")
        webview.start(func=on_start, debug=False)
        # webview.start() visszatért - ellenőrizzük hogy sikeres volt-e
        if not _webview_ready.is_set() or _webview_error.is_set():
            gui_failed = True
            logging.info("[MAIN] GUI nem indult el sikeresen, CLI mód következik...")
    except Exception as e:
        gui_failed = True
        logging.error(f"[MAIN] WebView indítási hiba: {e}")
        logging.error("[MAIN] Automatikus CLI mód indítása...")
    
    if gui_failed:
        # Konzol ablak létrehozása ha nincs (windowed exe-nél)
        try:
            ctypes.windll.kernel32.AllocConsole()
            # Stdin/stdout/stderr átirányítása az új konzolra
            sys.stdin = open('CONIN$', 'r')
            sys.stdout = open('CONOUT$', 'w')
            sys.stderr = open('CONOUT$', 'w')
        except Exception:
            pass
        
        print("\n" + "=" * 60)
        print("  ⚠️  GUI nem elérhető - CLI mód automatikusan aktiválva")
        print("  (Telepítsd a WebView2 Runtime-ot a GUI-hoz)")
        print("=" * 60)
        
        run_cli_mode()
    
    os._exit(0)
