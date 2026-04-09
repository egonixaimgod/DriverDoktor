BUILD_NUMBER = 34

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

# Suppress noisy PIL/Pillow debug logging
logging.getLogger('PIL').setLevel(logging.WARNING)
logging.getLogger('PIL.PngImagePlugin').setLevel(logging.WARNING)


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
        self._window = None
        self.target_os_path = None
        self.sys_drive = os.environ.get('SystemDrive', 'C:') + '\\'
        self.hw_updates_pool = []
        self._hw_installed_devs = []
        self._hw_scanning = False
        self._hw_loaded = False
        self.wu_api_mode = True
        self._si = subprocess.STARTUPINFO()
        self._si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self._nw = subprocess.CREATE_NO_WINDOW

    def set_window(self, window):
        self._window = window
        # Wait for WebView2 DOM to be ready
        for _ in range(50):
            try:
                if self._window and self._window.evaluate_js('1+1') == 2:
                    break
            except Exception:
                pass
            time.sleep(0.1)

    def emit(self, event, data=None):
        if self._window:
            try:
                payload = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
                self._window.evaluate_js(f'window.handlePyEvent({payload})')
            except Exception as e:
                if 'NoneType' in str(e):
                    time.sleep(0.5)
                    try:
                        self._window.evaluate_js(f'window.handlePyEvent({payload})')
                    except Exception:
                        pass
                else:
                    logging.error(f"emit error ({event}): {e}")

    def _run(self, cmd, **kwargs):
        return subprocess.run(cmd, capture_output=True, text=True, errors='replace',
                              startupinfo=self._si, creationflags=self._nw, **kwargs)

    def _safe_thread(self, task, target):
        def wrapper():
            try:
                target()
            except Exception as e:
                logging.error(f"{task} worker error: {e}")
                logging.error(traceback.format_exc())
                self.emit('task_error', {'task': task, 'error': str(e)})
                self.emit('task_complete', {'task': task, 'status': f'❌ Hiba: {e}'})
        threading.Thread(target=wrapper, daemon=True).start()

    # ================================================================
    # GENERAL
    # ================================================================
    def get_init_data(self):
        return {'build': BUILD_NUMBER, 'sys_drive': self.sys_drive, 'target_os': self.target_os_path}

    def change_target_os(self):
        result = self._window.create_file_dialog(_FOLDER_DIALOG, allow_multiple=False)
        if result and len(result) > 0:
            d = os.path.abspath(result[0]).replace("/", "\\")
            return {'path': d, 'has_windows': os.path.exists(os.path.join(d, "Windows"))}
        return None

    def apply_target_os(self, path):
        self.target_os_path = path
        return True

    def reset_target_os(self):
        self.target_os_path = None
        return True

    def select_directory(self, title='Válassz mappát'):
        result = self._window.create_file_dialog(_FOLDER_DIALOG, allow_multiple=False)
        if result and len(result) > 0:
            return result[0]
        return None

    def select_file(self, title='Válassz fájlt', file_types=''):
        ft = (file_types.split('|')[0],) if file_types else ()
        result = self._window.create_file_dialog(_OPEN_DIALOG, allow_multiple=False, file_types=ft)
        if result and len(result) > 0:
            return result[0]
        return None

    # ================================================================
    # DRIVER LISTING
    # ================================================================
    def load_drivers(self, all_drivers=False):
        def worker():
            self.emit('drivers_loading')
            start = time.time()
            try:
                if self.target_os_path:
                    drivers = self._get_offline_drivers(all_drivers)
                elif all_drivers:
                    drivers = self._get_all_drivers()
                else:
                    drivers = self._get_third_party_drivers()
                elapsed = time.time() - start
                self.emit('drivers_loaded', {'drivers': drivers, 'elapsed': round(elapsed, 1)})
            except Exception as e:
                logging.error(f"load_drivers error: {e}")
                self.emit('drivers_loaded', {'drivers': [], 'elapsed': 0, 'error': str(e)})
        threading.Thread(target=worker, daemon=True).start()

    def _get_third_party_drivers(self):
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
        cmd = ['powershell', '-NoProfile', '-Command',
               '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-WindowsDriver -Online -All | Select-Object ProviderName, ClassName, Version, Driver, OriginalFileName | ConvertTo-Json -Depth 2 -WarningAction SilentlyContinue']
        res = self._run(cmd, encoding='utf-8')
        out = res.stdout.strip()
        if not out:
            return []
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return [{"published": d.get("Driver", ""), "original": d.get("OriginalFileName", ""),
                 "provider": d.get("ProviderName", ""), "class": d.get("ClassName", ""),
                 "version": d.get("Version", "")} for d in data]

    def _get_offline_drivers(self, all_drivers=False):
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
        return drivers

    # ================================================================
    # DRIVER DELETION
    # ================================================================
    def delete_drivers(self, published_names, list_all=False):
        def worker():
            total = len(published_names)
            success = 0
            fail = 0
            self.emit('task_start', {'task': 'delete', 'title': f'Törlés folyamatban... ({total} driver)'})
            self.emit('task_progress', {'task': 'delete', 'log': f'Kijelölt driverek törlése indult ({total} db)'})

            for i, pub in enumerate(published_names):
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
                                    self._run(f'icacls "{d}" /grant administrators:F /t', shell=True)
                                    shutil.rmtree(d, ignore_errors=True)
                                    self._run(f'rmdir /s /q "{d}"', shell=True)
                                found_any = True

                            bname = os.path.splitext(pub)[0]
                            for ext in ['.inf', '.pnf', '.INF', '.PNF']:
                                fpath = os.path.join(inf_dir, bname + ext)
                                if os.path.exists(fpath):
                                    self._run(f'takeown /f "{fpath}" /A', shell=True)
                                    self._run(f'icacls "{fpath}" /grant administrators:F', shell=True)
                                    try:
                                        os.remove(fpath)
                                        found_any = True
                                    except:
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

            self.emit('task_progress', {'task': 'delete', 'log': f'\n--- Sikeres: {success}, Sikertelen: {fail} ---', 'current': total, 'total': total})
            self.emit('task_complete', {'task': 'delete', 'success': success, 'fail': fail,
                                        'counter': f'✅ {success} / ❌ {fail}',
                                        'status': f'Kész! Sikeres: {success}, Sikertelen: {fail}'})

        self._safe_thread('delete', worker)

    # ================================================================
    # HARDWARE SCAN
    # ================================================================
    def start_hw_scan(self):
        if self._hw_scanning:
            return
        self._hw_scanning = True

        def worker():
            try:
                _start = time.time()
                sys_info_text = "Ismeretlen PC / Laptop"

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

        threading.Thread(target=worker, daemon=True).start()

    def _extract_hwid(self, pnp_id):
        if not pnp_id:
            return None
        m = re.search(r'(HDAUDIO\\FUNC_[0-9A-F]+&VEN_[0-9A-F]+&DEV_[0-9A-F]+)', pnp_id, re.I)
        if m: return m.group(1)
        m = re.search(r'(VEN_[0-9A-F]+&DEV_[0-9A-F]+)', pnp_id, re.I)
        if m: return m.group(1)
        m = re.search(r'(HID\\VID_[0-9A-F]+&PID_[0-9A-F]+)', pnp_id, re.I)
        if m: return m.group(1)
        m = re.search(r'(USB\\VID_[0-9A-F]+&PID_[0-9A-F]+)', pnp_id, re.I)
        if m: return m.group(1)
        m = re.search(r'(VID_[0-9A-F]+&PID_[0-9A-F]+)', pnp_id, re.I)
        if m: return m.group(1)
        m = re.search(r'(ACPI\\[A-Z0-9_]+)', pnp_id, re.I)
        if m: return m.group(1)
        m = re.search(r'(DISPLAY\\[A-Z0-9]+)', pnp_id, re.I)
        if m: return m.group(1)
        return None

    def _search_wu_api(self):
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
                return None
            if out:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                return data if isinstance(data, list) else None
        except subprocess.TimeoutExpired:
            logging.error("WU API timeout (300s)")
        except Exception as e:
            logging.error(f"WU API error: {e}")
        return None

    def _catalog_search(self, devices_to_check):
        import urllib.request, urllib.parse, ssl
        ssl_ctx = ssl.create_default_context()
        lock = threading.Lock()

        def check_one(item):
            try:
                url = 'https://www.catalog.update.microsoft.com/Search.aspx?q=' + urllib.parse.quote(item['id'])
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
                        with lock:
                            self.hw_updates_pool.append({
                                "name": item['name'], "cat": item['cat'], "hwid": item['id'],
                                "url": cab_link.group(1), "pnp_id": item.get('pnp_id', ''),
                                "wu_title": f"MS Katalógus: {item['name']}"
                            })
            except Exception:
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

    def get_hw_pool(self):
        return {'pool': self.hw_updates_pool, 'installed': self._hw_installed_devs}

    # ================================================================
    # WU DRIVER INSTALL
    # ================================================================
    def install_selected_wu(self, selected_indices):
        selected_pool = [self.hw_updates_pool[i] for i in selected_indices if 0 <= i < len(self.hw_updates_pool)]
        if not selected_pool:
            return

        if self.wu_api_mode:
            self._install_wu_api(selected_pool)
        else:
            self._install_catalog(selected_pool)

    def _install_wu_api(self, selected_pool):
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
        def worker():
            import urllib.request, ssl
            ssl_ctx = ssl.create_default_context()
            total = len(selected_pool)
            self.emit('task_start', {'task': 'wu_install', 'title': f'Katalógus Driver Telepítés ({total} db)'})

            temp_dir = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'driver_tool_wu')
            os.makedirs(temp_dir, exist_ok=True)
            success = 0

            try:
                for i, drv in enumerate(selected_pool):
                    name = drv['name']
                    url = drv.get('url', '')
                    if not url:
                        self.emit('task_progress', {'task': 'wu_install', 'log': f'  [KIHAGYÁS] {name} - nincs link'})
                        continue

                    cab_path = os.path.join(temp_dir, f"drv_{i}.cab")
                    ext_path = os.path.join(temp_dir, f"drv_ext_{i}")
                    self.emit('task_progress', {'task': 'wu_install', 'current': i, 'total': total,
                                                'status': f'Letöltés: {name}', 'counter': f'{i+1}/{total}',
                                                'log': f'-> {name} letöltése...'})
                    try:
                        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                        with urllib.request.urlopen(req, context=ssl_ctx) as resp, open(cab_path, 'wb') as f:
                            shutil.copyfileobj(resp, f)
                    except Exception as e:
                        self.emit('task_progress', {'task': 'wu_install', 'log': f'  [HIBA] Letöltés: {e}'})
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
                        self.emit('task_progress', {'task': 'wu_install', 'log': f'  ✅ {name} telepítve!'})
                    else:
                        self.emit('task_progress', {'task': 'wu_install', 'log': f'  ❌ {name} hiba: {res.stdout[:100]}'})

                if success > 0 and not self.target_os_path:
                    self.emit('task_progress', {'task': 'wu_install', 'log': 'Eszközök újraszkennelése...'})
                    self._run(['pnputil', '/scan-devices'])
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

            self.emit('task_progress', {'task': 'wu_install', 'current': total, 'total': total,
                                        'log': f'\n--- Sikeres: {success}/{total} ---'})
            self.emit('task_complete', {'task': 'wu_install', 'success': success, 'fail': total - success,
                                        'status': f'Kész! Sikeres: {success}/{total}'})

        self._safe_thread('wu_install', worker)

    # ================================================================
    # AUTOFIX
    # ================================================================
    def start_autofix(self):
        def worker():
            overall_start = time.time()

            def elapsed():
                s = int(time.time() - overall_start)
                m, sec = divmod(s, 60)
                return f"{m:02d}:{sec:02d}"

            self.emit('task_start', {'task': 'autofix', 'title': '⚡ 1 Kattintásos Driver Fix'})

            # PHASE 1: Disable WU drivers
            self.emit('task_progress', {'task': 'autofix', 'phase': '⛔ 1. FÁZIS: WU letiltás',
                                        'log': '=' * 50 + '\nFÁZIS 1: WU driver keresés letiltása...',
                                        'current': 0, 'total': 4})
            try:
                key_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 1)
                self.emit('task_progress', {'task': 'autofix', 'log': '  ✅ ExcludeWUDriversInQualityUpdate = 1'})
            except Exception as e:
                self.emit('task_progress', {'task': 'autofix', 'log': f'  ⚠ winreg hiba: {e}'})
            self._run(['reg', 'add', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate',
                       '/v', 'ExcludeWUDriversInQualityUpdate', '/t', 'REG_DWORD', '/d', '1', '/f'])

            try:
                key_path2 = r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching"
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path2, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 0)
                self.emit('task_progress', {'task': 'autofix', 'log': '  ✅ SearchOrderConfig = 0'})
            except Exception as e:
                self.emit('task_progress', {'task': 'autofix', 'log': f'  ⚠ winreg hiba: {e}'})
            self._run(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching',
                       '/v', 'SearchOrderConfig', '/t', 'REG_DWORD', '/d', '0', '/f'])

            self._run('net stop wuauserv & net start wuauserv', shell=True)
            self.emit('task_progress', {'task': 'autofix', 'log': '  ✅ WU szolgáltatás újraindítva\n\n✅ WU letiltás kész!\n',
                                        'current': 4, 'total': 4})

            # PHASE 2: Delete third-party drivers
            self.emit('task_progress', {'task': 'autofix', 'phase': '🔴 2. FÁZIS: Driver törlés',
                                        'log': '=' * 50 + '\nFÁZIS 2: Third-party driverek törlése...'})
            drivers = self._get_third_party_drivers()
            del_total = len(drivers)
            self.emit('task_progress', {'task': 'autofix', 'log': f'Talált: {del_total} db', 'total': max(del_total, 1), 'current': 0})
            del_success = 0
            del_fail = 0
            for i, drv in enumerate(drivers):
                pub = drv.get("published", "?")
                prov = drv.get("provider", "")
                self.emit('task_progress', {'task': 'autofix', 'status': f'Törlés: {pub}', 'log': f'  🗑 {pub} [{prov}]'})
                try:
                    res = self._run(['pnputil', '/delete-driver', pub, '/uninstall', '/force'])
                    if res.returncode == 0 or any(k in res.stdout for k in ["Deleted", "törölve", "successfully"]):
                        del_success += 1
                        self.emit('task_progress', {'task': 'autofix', 'log': f'    ✅ törölve'})
                    else:
                        del_fail += 1
                        self.emit('task_progress', {'task': 'autofix', 'log': f'    ❌ sikertelen'})
                except Exception as e:
                    del_fail += 1
                    self.emit('task_progress', {'task': 'autofix', 'log': f'    ❌ hiba: {e}'})
                self.emit('task_progress', {'task': 'autofix', 'current': i + 1, 'total': del_total,
                                            'counter': f'{i+1}/{del_total} (✅{del_success} ❌{del_fail})'})

            self.emit('task_progress', {'task': 'autofix', 'log': f'\n--- Törlés kész. Sikeres: {del_success}, Sikertelen: {del_fail} ---\n'})

            # PHASE 3: Hardware rescan
            self.emit('task_progress', {'task': 'autofix', 'phase': '🟡 3. FÁZIS: Hardver scan',
                                        'log': '=' * 50 + '\nFÁZIS 3: pnputil /scan-devices...', 'indeterminate': True})
            try:
                self._run(['pnputil', '/scan-devices'], timeout=120)
                time.sleep(5)
                self.emit('task_progress', {'task': 'autofix', 'log': '✅ Hardver scan kész!'})
            except Exception:
                self.emit('task_progress', {'task': 'autofix', 'log': '⚠ Scan timeout/hiba — folytatás...'})

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

            # PHASE 6: Reboot
            self.emit('task_progress', {'task': 'autofix', 'phase': '🔵 6. FÁZIS: Újraindítás',
                                        'log': f'\n{"=" * 50}\nFÁZIS 6: Újraindítás 30 másodperc múlva!\n\n⚡ Teljes idő: {elapsed()}'})
            for c in range(30, 0, -1):
                self.emit('task_progress', {'task': 'autofix', 'counter': f'Újraindítás {c} mp múlva...', 'current': 30 - c, 'total': 30})
                time.sleep(1)

            self.emit('task_progress', {'task': 'autofix', 'log': '🔄 Újraindítás MOST!'})
            self._run(['shutdown', '/r', '/t', '0', '/f'])

        self._safe_thread('autofix', worker)

    # ================================================================
    # WU MANAGEMENT
    # ================================================================
    def check_wu_status(self):
        try:
            policy_disabled = False
            search_disabled = False
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate", 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, "ExcludeWUDriversInQualityUpdate")
                    if val == 1: policy_disabled = True
            except FileNotFoundError:
                pass
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching", 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, "SearchOrderConfig")
                    if val == 0: search_disabled = True
            except FileNotFoundError:
                pass

            if policy_disabled and search_disabled:
                return {'status': 'Teljesen LETILTVA', 'color': 'disabled'}
            elif policy_disabled:
                return {'status': 'Házirend által LETILTVA', 'color': 'disabled'}
            elif search_disabled:
                return {'status': 'Eszközbeállításokban LETILTVA', 'color': 'disabled'}
            else:
                return {'status': 'Driver frissítés ENGEDÉLYEZVE', 'color': 'enabled'}
        except Exception:
            return {'status': 'Ismeretlen', 'color': 'unknown'}

    def disable_wu(self):
        def worker():
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
        def worker():
            self.emit('task_start', {'task': 'enable_wu', 'title': 'WU Driver Engedélyezés + Reset'})
            self.emit('task_progress', {'task': 'enable_wu', 'log': 'WU driver engedélyezés + teljes reset...', 'indeterminate': True})

            # Delete policy
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate", 0, winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key, "ExcludeWUDriversInQualityUpdate")
                self.emit('task_progress', {'task': 'enable_wu', 'log': '✅ ExcludeWUDrivers policy törölve'})
            except FileNotFoundError:
                self.emit('task_progress', {'task': 'enable_wu', 'log': '  Policy nem létezett'})
            except Exception as e:
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
                self.emit('task_progress', {'task': 'enable_wu', 'log': '✅ SearchOrderConfig = 1'})
            except Exception as e:
                self.emit('task_progress', {'task': 'enable_wu', 'log': f'⚠ {e}'})

            self._run(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching',
                       '/v', 'SearchOrderConfig', '/t', 'REG_DWORD', '/d', '1', '/f'])
            self._run(['reg', 'delete', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate',
                       '/v', 'ExcludeWUDriversInQualityUpdate', '/f'])

            # Stop services
            for svc in ['wuauserv', 'bits', 'cryptsvc']:
                self._run(f'net stop {svc} /y', shell=True)
            time.sleep(2)

            # Delete SoftwareDistribution
            sysroot = os.environ.get('SYSTEMROOT', r'C:\Windows')
            sw_dist = os.path.join(sysroot, 'SoftwareDistribution')
            self.emit('task_progress', {'task': 'enable_wu', 'log': f'SoftwareDistribution törlése...'})
            for _ in range(3):
                try:
                    if os.path.exists(sw_dist):
                        shutil.rmtree(sw_dist, ignore_errors=False)
                        self.emit('task_progress', {'task': 'enable_wu', 'log': '  ✅ Törölve'})
                        break
                except Exception as e:
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
                    self.emit('task_progress', {'task': 'enable_wu', 'log': '✅ catroot2 átnevezve'})
            except Exception as e:
                self.emit('task_progress', {'task': 'enable_wu', 'log': f'⚠ catroot2: {e}'})

            # Re-register DLLs
            sys32 = os.path.join(sysroot, 'System32')
            for dll in ['wuaueng.dll', 'wuapi.dll', 'wups.dll', 'wups2.dll', 'wuwebv.dll', 'wucltux.dll']:
                fp = os.path.join(sys32, dll)
                if os.path.exists(fp):
                    self._run(f'regsvr32.exe /s "{fp}"', shell=True)
            self.emit('task_progress', {'task': 'enable_wu', 'log': '✅ WU DLL-ek újraregisztrálva'})

            # Winsock reset
            self._run('netsh winsock reset', shell=True)

            # Start services
            for svc in ['cryptsvc', 'bits', 'wuauserv']:
                for _ in range(3):
                    res = self._run(f'net start {svc}', shell=True)
                    if res.returncode == 0 or 'already' in (res.stdout + res.stderr).lower():
                        break
                    time.sleep(3)

            self._run('wuauclt.exe /resetauthorization /detectnow', shell=True)
            self._run('UsoClient.exe StartScan', shell=True)
            self.emit('task_progress', {'task': 'enable_wu', 'log': '✅ Frissítés-keresés elindítva'})
            self.emit('task_complete', {'task': 'enable_wu', 'status': '✅ WU engedélyezés + reset kész!'})

        self._safe_thread('enable_wu', worker)

    def restart_wu(self):
        def worker():
            self.emit('task_start', {'task': 'restart_wu', 'title': 'WU Szolgáltatások Újraindítása'})
            self.emit('task_progress', {'task': 'restart_wu', 'log': 'WU szolgáltatások újraindítása...', 'indeterminate': True})

            for svc in ['wuauserv', 'bits', 'cryptsvc', 'msiserver']:
                self._run(f'net stop {svc} /y', shell=True)
                self.emit('task_progress', {'task': 'restart_wu', 'log': f'  stop {svc}'})
            time.sleep(2)
            for svc in ['rpcss', 'cryptsvc', 'bits', 'msiserver', 'wuauserv']:
                for _ in range(3):
                    res = self._run(f'net start {svc}', shell=True)
                    if res.returncode == 0 or 'already' in (res.stdout + res.stderr).lower():
                        break
                    time.sleep(3)
                self.emit('task_progress', {'task': 'restart_wu', 'log': f'  start {svc}'})
            self._run('wuauclt.exe /resetauthorization /detectnow', shell=True)
            self._run('UsoClient.exe StartScan', shell=True)
            self.emit('task_progress', {'task': 'restart_wu', 'log': '✅ Frissítés-keresés elindítva'})
            self.emit('task_complete', {'task': 'restart_wu', 'status': '✅ WU szolgáltatások újraindítva!'})

        self._safe_thread('restart_wu', worker)

    # ================================================================
    # BACKUP / RESTORE
    # ================================================================
    def backup_third_party(self):
        dest = self.select_directory('Válassz mappát a driverek kimentéséhez')
        if not dest:
            return

        def worker():
            folder = os.path.join(dest, f"Driver_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(folder, exist_ok=True)
            self.emit('task_start', {'task': 'backup', 'title': 'Driver Exportálás'})
            self.emit('task_progress', {'task': 'backup', 'log': f'Célmappa: {folder}\nExportálás indítása...', 'indeterminate': True})

            process = subprocess.Popen(
                ['dism', '/online', '/export-driver', f'/destination:{folder}'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                startupinfo=self._si, creationflags=self._nw, errors='replace')

            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                m = re.search(r'(\d+)\s*(?:/|of)\s*(\d+)', line, re.I)
                if m:
                    self.emit('task_progress', {'task': 'backup', 'current': int(m.group(1)), 'total': int(m.group(2)),
                                                'counter': f'{m.group(1)}/{m.group(2)}', 'status': line[:60]})
                self.emit('task_progress', {'task': 'backup', 'log': line})
            process.wait()

            success = process.returncode == 0
            self.emit('task_complete', {'task': 'backup',
                                        'status': f'{"✅ Sikeres export!" if success else "❌ Hiba!"} Mappa: {folder}',
                                        'log': f'\n--- {"Sikeres" if success else "Hibás"} export: {folder} ---'})
        self._safe_thread('backup', worker)

    def backup_all(self):
        dest = self.select_directory('Válassz mappát az ÖSSZES driver kimentéséhez')
        if not dest:
            return

        def worker():
            folder = os.path.join(dest, f"ALL_Driver_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(folder, exist_ok=True)
            self.emit('task_start', {'task': 'backup', 'title': 'ÖSSZES Driver Exportálása'})
            self.emit('task_progress', {'task': 'backup', 'log': 'Driver lista lekérdezése...', 'indeterminate': True})

            enum_res = self._run(['pnputil', '/enum-drivers'])
            all_infs = re.findall(r'(oem\d+\.inf)', enum_res.stdout, re.I)
            self.emit('task_progress', {'task': 'backup', 'log': f'OEM driverek: {len(all_infs)} db'})

            success = 0
            fail = 0
            for i, inf in enumerate(all_infs):
                inf_folder = os.path.join(folder, inf.replace('.inf', ''))
                os.makedirs(inf_folder, exist_ok=True)
                res = self._run(['pnputil', '/export-driver', inf, inf_folder])
                if res.returncode == 0:
                    success += 1
                else:
                    fail += 1
                self.emit('task_progress', {'task': 'backup', 'current': i + 1, 'total': len(all_infs),
                                            'counter': f'{i+1}/{len(all_infs)}', 'status': f'Export: {inf}'})

            # Copy inbox drivers
            self.emit('task_progress', {'task': 'backup', 'log': 'Windows inbox driverek másolása...', 'indeterminate': True})
            driverstore = os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), 'System32', 'DriverStore', 'FileRepository')
            inbox_folder = os.path.join(folder, '_Windows_Inbox_Drivers')
            os.makedirs(inbox_folder, exist_ok=True)
            self._run(['robocopy', driverstore, inbox_folder, '/E', '/R:0', '/W:0', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP'])

            total_size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fns in os.walk(folder) for f in fns
                             if os.path.exists(os.path.join(dp, f)))
            size_mb = total_size / (1024 * 1024)
            self.emit('task_complete', {'task': 'backup',
                                        'status': f'✅ Kész! OEM: {success} db ({fail} sikertelen), Inbox másolva. Méret: {size_mb:.0f} MB',
                                        'log': f'\n--- Export kész: {folder} ({size_mb:.0f} MB) | Sikeres: {success}, Sikertelen: {fail} ---'})
        self._safe_thread('backup', worker)

    def create_restore_point(self):
        def worker():
            desc = f"Driver_Cleaner_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.emit('task_start', {'task': 'rp', 'title': 'Visszaállítási Pont'})
            self.emit('task_progress', {'task': 'rp', 'log': 'Rendszervédelem engedélyezése...', 'indeterminate': True})

            # 1) Enable System Restore on C: (force enable even if disabled)
            enable_ps = '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; try { Enable-ComputerRestore -Drive "C:\\" -ErrorAction Stop; Write-Output "OK" } catch { Write-Output "FAIL: $($_.Exception.Message)" }'
            enable_res = self._run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", enable_ps], encoding='utf-8')
            enable_out = (enable_res.stdout or '').strip()
            if 'FAIL' in enable_out:
                # Try via registry + vssadmin as fallback
                self.emit('task_progress', {'task': 'rp', 'log': f'⚠ Enable-ComputerRestore hiba: {enable_out}\nRegistry + vssadmin fallback...'})
                self._run(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore', '/v', 'DisableSR', '/t', 'REG_DWORD', '/d', '0', '/f'])
                self._run(['vssadmin', 'resize', 'shadowstorage', '/for=C:', '/on=C:', '/maxsize=5%'])
                # Retry enable
                enable_res2 = self._run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", enable_ps], encoding='utf-8')
                enable_out2 = (enable_res2.stdout or '').strip()
                if 'FAIL' in enable_out2:
                    self.emit('task_complete', {'task': 'rp', 'status': f'❌ Rendszervédelem nem kapcsolható be: {enable_out2}'})
                    return
                self.emit('task_progress', {'task': 'rp', 'log': '✅ Rendszervédelem bekapcsolva (fallback)'})
            else:
                self.emit('task_progress', {'task': 'rp', 'log': '✅ Rendszervédelem bekapcsolva'})

            # 2) Create restore point
            self.emit('task_progress', {'task': 'rp', 'log': f'Visszaállítási pont: {desc}', 'status': 'Pont létrehozása...'})
            create_ps = f'[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; try {{ Checkpoint-Computer -Description "{desc}" -RestorePointType "MODIFY_SETTINGS" -ErrorAction Stop; Write-Output "OK" }} catch {{ Write-Output "FAIL: $($_.Exception.Message)" }}'
            res = self._run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", create_ps], encoding='utf-8')
            create_out = (res.stdout or '').strip()

            # 3) Verify
            verify_ps = f'[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; (Get-ComputerRestorePoint | Where-Object {{ $_.Description -eq "{desc}" }}).Description'
            verify_res = self._run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", verify_ps], encoding='utf-8')
            verified = desc in (verify_res.stdout or '')

            if 'OK' in create_out and verified:
                self.emit('task_complete', {'task': 'rp', 'status': f'✅ Visszaállítási pont létrehozva: {desc}'})
            elif 'OK' in create_out:
                self.emit('task_complete', {'task': 'rp', 'status': '⚠ Lefutott de nem ellenőrizhető (24 órás limit?)'})
            else:
                self.emit('task_complete', {'task': 'rp', 'status': f'❌ Hiba: {create_out}'})
        self._safe_thread('rp', worker)

    def restore_online(self):
        source = self.select_directory('ÉLŐ MÓD: Válassz kimentett driver mappát')
        if not source:
            return
        self._run_restore(online=True, source=source, target=None)

    def restore_offline(self):
        target = self.select_directory('OFFLINE MÓD: 1. Válaszd ki a HALOTT WINDOWS meghajtóját')
        if not target:
            return
        target = os.path.splitdrive(os.path.abspath(target))[0] + "\\"
        source = self.select_directory('OFFLINE MÓD: 2. Válassz kimentett driver mappát')
        if not source:
            return
        self._run_restore(online=False, source=source, target=target)

    def _run_restore(self, online, source, target):
        def worker():
            mode = 'Élő' if online else 'Offline'
            self.emit('task_start', {'task': 'restore', 'title': f'Driver Visszaállítás ({mode})'})
            self.emit('task_progress', {'task': 'restore', 'log': f'=== {mode.upper()} RESTORE ===\nForrás: {source}\nCél: {target or "jelenlegi rendszer"}\n', 'indeterminate': True})

            norm_source = os.path.normpath(source)
            norm_target = os.path.normpath(target) if target else None
            is_inbox = not online and "Windows_Gyari_Alap_Driverek" in norm_source

            if online:
                cmd = ['pnputil', '/add-driver', f"{norm_source}\\*.inf", '/subdirs', '/install']
                self.emit('task_progress', {'task': 'restore', 'log': f'Parancs: {" ".join(cmd)}'})
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                           startupinfo=self._si, creationflags=self._nw, errors='replace')
                for line in process.stdout:
                    self.emit('task_progress', {'task': 'restore', 'log': line.strip()})
                process.wait()
                self.emit('task_progress', {'task': 'restore', 'log': f'\nReturn code: {process.returncode}'})
            else:
                if is_inbox:
                    self.emit('task_progress', {'task': 'restore', 'log': 'Gyári inbox driverek injektálása (DISM) - Ez eltarthat 10-20 percig!'})
                scratch = os.path.join(norm_target, "Scratch")
                os.makedirs(scratch, exist_ok=True)
                cmd = ['dism', f'/Image:{norm_target}', '/Add-Driver', f'/Driver:{norm_source}', '/Recurse', '/ForceUnsigned', f'/ScratchDir:{scratch}']
                self.emit('task_progress', {'task': 'restore', 'log': f'Parancs: {" ".join(cmd)}'})
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                           startupinfo=self._si, creationflags=self._nw, errors='replace')
                for line in process.stdout:
                    self.emit('task_progress', {'task': 'restore', 'log': line.strip()})
                process.wait()
                self.emit('task_progress', {'task': 'restore', 'log': f'\nReturn code: {process.returncode}'})

            # Post-install
            if online:
                is_pe = os.environ.get('SystemDrive', 'C:') == 'X:'
                if not is_pe:
                    self.emit('task_progress', {'task': 'restore', 'log': 'Hardverváltozások keresése...'})
                    time.sleep(1.5)
                    self._run(['pnputil', '/scan-devices'])
                    time.sleep(3.5)
                    self.emit('task_progress', {'task': 'restore', 'log': '✅ Scan kész!'})
            elif not is_inbox:
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
        wim_path = self.select_file('Válaszd ki az install.wim fájlt', 'WIM fájlok (*.wim)|*.wim')
        if not wim_path:
            return
        if wim_path.lower().endswith(".esd"):
            self.emit('alert', {'title': 'Hiba', 'message': 'ESD fájl nem támogatott. Kérlek, használj install.wim fájlt!'})
            return
        dest = self.select_directory('Válassz ideiglenes mappát a kicsomagoláshoz')
        if not dest:
            return

        def worker():
            self.emit('task_start', {'task': 'wim', 'title': 'WIM Driver Kinyerés'})
            wim = os.path.abspath(wim_path).replace("/", "\\")
            mount_dir = os.path.join(dest, "WIM_Mount_Temp")
            target_folder = os.path.join(dest, f"Windows_Gyari_Alap_Driverek_{datetime.now().strftime('%Y%m%d_%H%M')}")

            if os.path.exists(mount_dir):
                shutil.rmtree(mount_dir, ignore_errors=True)
            os.makedirs(mount_dir, exist_ok=True)
            os.makedirs(target_folder, exist_ok=True)

            try:
                self.emit('task_progress', {'task': 'wim', 'log': 'WIM csatolás (ez 4-5 perc)...', 'indeterminate': True,
                                            'counter': '1/3', 'status': 'Képfájl csatolása...'})
                res = self._run(["dism", "/Mount-Image", f"/ImageFile:{wim}", "/Index:1", f"/MountDir:{mount_dir}", "/ReadOnly"])
                if res.returncode != 0:
                    raise Exception(f"DISM Mount hiba: {res.stdout} {res.stderr}")

                self.emit('task_progress', {'task': 'wim', 'log': 'DriverStore másolása...', 'counter': '2/3', 'status': 'Gyári driverek másolása...'})
                driverstore = os.path.join(mount_dir, "Windows", "System32", "DriverStore", "FileRepository")
                if os.path.exists(driverstore):
                    shutil.copytree(driverstore, target_folder, dirs_exist_ok=True)
                else:
                    raise Exception("FileRepository nem található a WIM-ben!")

                self.emit('task_progress', {'task': 'wim', 'log': 'WIM leválasztása...', 'counter': '3/3', 'status': 'Takarítás...'})
                self._run(["dism", "/Unmount-Image", f"/MountDir:{mount_dir}", "/Discard"])
                shutil.rmtree(mount_dir, ignore_errors=True)

                self.emit('task_complete', {'task': 'wim', 'status': f'✅ Gyári driverek kimentve: {target_folder}',
                                            'log': f'\n✅ Kész! Mappa: {target_folder}'})
            except Exception as e:
                self._run(["dism", "/Unmount-Image", f"/MountDir:{mount_dir}", "/Discard"])
                shutil.rmtree(mount_dir, ignore_errors=True)
                self.emit('task_error', {'task': 'wim', 'error': str(e)})
                self.emit('task_complete', {'task': 'wim', 'status': f'❌ Hiba: {e}'})

        self._safe_thread('wim', worker)


# ================================================================
# MAIN
# ================================================================
if __name__ == "__main__":
    if not is_admin():
        params = ' '.join([f'"{arg}"' for arg in sys.argv[1:]])
        if getattr(sys, 'frozen', False):
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        else:
            script = sys.argv[0]
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
        sys.exit()

    # Logging
    log_filename = os.path.join(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)), "driver_tool_debug.log")
    try:
        logging.basicConfig(filename=log_filename, level=logging.DEBUG,
                            format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S', encoding='utf-8')
    except Exception:
        logging.basicConfig(level=logging.DEBUG)

    def global_exception_handler(exc_type, exc_value, exc_traceback):
        logging.exception("FATÁLIS HIBA:", exc_info=(exc_type, exc_value, exc_traceback))
    sys.excepthook = global_exception_handler

    def thread_exception_handler(args):
        logging.exception("HÁTTÉRSZÁL HIBA:", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = thread_exception_handler

    logging.info("=" * 50)
    logging.info("ULTIMATE DRIVER GYILKOLO (es telepito) SZERVIZ TOOL ELINDITVA")
    logging.info(f"Futtatasi konyvtar: {os.getcwd()}")
    logging.info("=" * 50)

    api = DriverToolApi()
    html_path = resource_path('ui.html')

    window = webview.create_window(
        'ULTIMATE DRIVER GYILKOLO (es telepito) SZERVIZ TOOL',
        url=html_path,
        js_api=api,
        width=1200, height=780,
        min_size=(900, 600)
    )

    def on_start():
        api.set_window(window)

    try:
        webview.start(func=on_start, debug=False)
    except Exception:
        pass
    finally:
        os._exit(0)
