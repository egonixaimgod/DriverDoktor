"""In-app auto-updater - KÖZÖS mag (GUI automatikus/manuális ellenőrzés + CLI menüpont).

A BUILD_NUMBER-ellenőrzés és a frissítés letöltése/előkészítése EGY példányban itt él;
a GUI (app/gui/updater.py) emit-ekkel, a CLI (app/cli/updater.py) printtel csomagolja.

Fontos (CLAUDE.md): a raw.githubusercontent.com Fastly CDN mögött fut, aminek
edge-cache-e egy friss push után percekig a RÉGI tartalmat adhatja vissza (a
?t=<timestamp> csak a kliens-oldali cache-t kerüli meg) - ezért a check 3x
próbálkozik 3s szünetekkel. Frissítés CSAK szigorúan nagyobb build esetén ajánlható
(new_build > BUILD_NUMBER). A letöltés ssl.create_default_context()-tel, teljes
tanúsítvány-ellenőrzéssel megy - ezt SOHA nem szabad kikapcsolni (admin-jogú exe-t
töltünk le)."""

# === AUTO-IMPORTS ===
import os
import subprocess
import re
import time
import logging
import winreg
from app import common
from app.common import _app_exe_path
# === /AUTO-IMPORTS ===


# AZ ÚJRAPRÓBÁLKOZÁS A FASTLY CDN ELAVULT PÉLDÁNYA MIATT VAN, ÉS CSAK AKKOR FUT LE, HA
# TÉNYLEG SEGÍTHET (2026-09-08, terepen mérve). A raw.githubusercontent.com mögötti CDN
# egy push után percekig kiszolgálhat régi másolatot, és a `?t=<timestamp>` csak a
# kliens-oldali gyorsítótárat kerüli meg - ezért született a 3 próbálkozás.
#
# A ciklus viszont a SIKERES, egyértelmű válasz után is továbbment. Mérve egy induláson:
#   22:58:23  Letöltött BUILD_NUMBER: 304, Helyi: 304 -> Nincs újabb verzió.
#   22:58:26  ...ugyanaz
#   22:58:29  ...ugyanaz          ->  check_for_updates -> 6.30s
# Vagyis MINDEN kézi indítás 6,3 másodpercet és 3 HTTP-kérést költött egy olyan kérdésre,
# amire az első válasz definitív volt.
#
# AZ ÚJ SZABÁLY (a védőháló megmarad, az ár eltűnik):
#   újabb build      -> azonnal vissza (eddig is így volt)
#   AZONOS build     -> DEFINITÍV válasz, azonnal vissza  <- ez a nyereség
#   KISEBB build     -> gyanús: elavult CDN-példány (vagy helyi bump push előtt) -> újra
#   hiba / nem parse -> újra
UPDATE_CHECK_ATTEMPTS = 3
UPDATE_CHECK_RETRY_SEC = 3
_RAW_BASE = "https://raw.githubusercontent.com/egonixaimgod/DriverVarazslo/main"


def check_for_updates():
    """Update-ellenőrzés a GitHub-on lévő driver_tool.py BUILD_NUMBER-je alapján.
    Visszatérés: {'has_update': bool, 'new_version': int (csak ha van)}."""
    logging.info("[UPDATE] check_for_updates()")
    import urllib.request
    import urllib.error
    import ssl
    ssl_ctx = ssl.create_default_context()
    for attempt in range(1, UPDATE_CHECK_ATTEMPTS + 1):
        try:
            # A ?t=<timestamp> a kliens-oldali cache megkerülésére (a CDN-ét nem védi ki)
            url = f"{_RAW_BASE}/driver_tool.py?t={int(time.time())}"
            logging.info(f"[UPDATE] Update ellenőrzése erről a címről ({attempt}/{UPDATE_CHECK_ATTEMPTS}. próbálkozás): {url}")
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            try:
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
                    content = resp.read().decode('utf-8')
            except (urllib.error.URLError, ssl.SSLError) as ssl_err:
                # RÉGI WINDOWS (7/8/8.1) MIATT KELL: a Python OpenSSL-verme itt olyan
                # TLS-hibába futhat, amibe a rendszer schannel-je nem - terepen mérve
                # (2026-08-13, Win 8.1) pontosan ez buktatta el a WebView2 telepítő
                # letöltését ugyanezen a gépen ([SSL: UNEXPECTED_EOF_WHILE_READING]).
                # Ha ezt itt nem kapjuk el, a régi gép SOHA nem értesül róla, hogy van
                # újabb build - vagyis épp az a javítás nem jut el hozzá, ami a hibát
                # orvosolná. A közös letöltő ilyenkor PowerShellre (schannel) vált,
                # teljes tanúsítvány-ellenőrzéssel.
                if not common._should_try_ps_download(ssl_err):
                    raise
                logging.warning(f"[UPDATE] Python SSL/TLS hiba ({ssl_err}) - áttérés a közös "
                                f"letöltő PowerShell (schannel) ágára...")
                content = common.fetch_text_with_cert_fallback(url, timeout=10, ps_timeout=120,
                                                               log_tag='UPDATE')
            m = re.search(r'^BUILD_NUMBER\s*=\s*(\d+)', content, re.MULTILINE)
            if m:
                new_build = int(m.group(1))
                logging.info(f"[UPDATE] Letöltött BUILD_NUMBER: {new_build}, Helyi: {common.BUILD_NUMBER}")
                if new_build > common.BUILD_NUMBER:
                    logging.info(f"[UPDATE] Új verzió elérhető: {new_build} (Jelenlegi: {common.BUILD_NUMBER})")
                    return {'has_update': True, 'new_version': new_build}
                if new_build == common.BUILD_NUMBER:
                    # DEFINITÍV VÁLASZ - nincs mit újrapróbálni (lásd a konstansok indoklását).
                    logging.info("[UPDATE] Nincs újabb verzió (a szerver a helyivel azonos "
                                 "build-et ad - definitív válasz, nincs újrapróbálkozás).")
                    return {'has_update': False}
                logging.info(f"[UPDATE] A szerver a helyinél RÉGEBBI build-et ad "
                             f"({new_build} < {common.BUILD_NUMBER}) - elavult CDN-példány vagy "
                             f"push előtti helyi verziószám-emelés lehet, újrapróbáljuk.")
            else:
                logging.error("[UPDATE] Nem található BUILD_NUMBER a letöltött fájlban!")
        except Exception:
            logging.error(f"[UPDATE] Ellenőrzési hiba ({attempt}/{UPDATE_CHECK_ATTEMPTS}. próbálkozás):", exc_info=True)
        if attempt < UPDATE_CHECK_ATTEMPTS:
            time.sleep(UPDATE_CHECK_RETRY_SEC)
    return {'has_update': False}


def stage_update(log):
    """Az új exe letöltése + a cserét végző .bat előkészítése. Visszatérés: a .bat
    útvonala (a futtatás a hívóé: launch_update_and_exit). Hibánál kivételt dob."""
    import tempfile

    exe_url = f"{_RAW_BASE}/dist/DriverVarazslo.exe?t={int(time.time())}"
    # WinPE-ben a %TEMP% az X: RAM-diskre mutat - a letöltött exe-t a valódi C: meghajtóra tesszük.
    is_pe = os.environ.get('SystemDrive', 'C:') == 'X:'
    if is_pe:
        temp_dir = r'C:\DV_Temp'
        os.makedirs(temp_dir, exist_ok=True)
    else:
        temp_dir = tempfile.gettempdir()
    new_exe = os.path.join(temp_dir, f"DriverVarazslo_Update_{int(time.time())}.exe")

    logging.info(f"[UPDATE] EXE letöltése innen: {exe_url}")
    logging.info(f"[UPDATE] Cél fájl: {new_exe}")
    log('Új verzió letöltése GitHubról...')

    # A KÖZÖS letöltő (Python -> PowerShell schannel fallback), nem csupasz urllib:
    # ugyanaz az indok, mint a check_for_updates-nél - egy régi Windowson a Python
    # TLS-verme elhasalhat ott, ahol a rendszeré nem, és akkor a frissítés magán a
    # frissítendő gépen válik lehetetlenné. Az exe több MB, ezért bőven nagyobb
    # időkorláttal (a bootstrapperhez képest is), lassú gépet/hálózatot feltételezve.
    common.download_with_cert_fallback(
        common.default_run, exe_url, new_exe,
        timeout=120, ps_timeout=600, log_tag='UPDATE',
        error_msg="A frissítés letöltése nem sikerült (nincs internet, vagy a GitHub nem elérhető).")

    downloaded_size = os.path.getsize(new_exe)
    logging.info(f"[UPDATE] EXE letöltve. Fájlméret: {downloaded_size} byte.")
    if downloaded_size < 1000000:  # Ha kevesebb mint 1 MB, valószínűleg nem jó a letöltés
        logging.warning("[UPDATE] A letöltött fájl gyanúsan kicsi! Lehet, hogy hiba történt vagy 404 oldalt töltött le.")

    log('✅ Letöltés kész! A program frissítése és újraindítása következik...')

    current_exe = _app_exe_path()
    logging.info(f"[UPDATE] Jelenlegi futtatható fájl: {current_exe}")

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
            desktop_dir, _ = winreg.QueryValueEx(key, "Desktop")
    except Exception:
        desktop_dir = os.path.join(os.environ.get('USERPROFILE', 'C:\\'), 'Desktop')

    desktop_exe = os.path.join(desktop_dir, "DriverVarazslo.exe")
    logging.info(f"[UPDATE] Asztali elérési út: {desktop_exe}")

    bat_path = os.path.join(temp_dir, f"dv_update_{int(time.time())}.bat")
    # A ".old" biztonsági másolatokat sosem olvassuk vissza (nincs rollback funkció),
    # kizárólag a következő indításkori törlésre szolgálnak - ha viszont a program
    # legközelebb egy MÁSIK elérési útról indul (pl. nem az asztalról), a __init__-beli
    # takarítás sosem találja meg és törli őket, és örökre a lemezen maradnak. Ezért itt,
    # helyben (és csak sikeres másolás esetén) rögtön eltávolítjuk mindkettőt.
    bat_content = f"""@echo off
set _MEIPASS2=
set _MEIPASS=
set _PYIBoot_Pkg_ID=
timeout /t 3 /nobreak > nul

if /I not "{current_exe}"=="{desktop_exe}" (
    move /y "{current_exe}" "{current_exe}.old" > nul 2>&1
    copy /y "{new_exe}" "{current_exe}" > nul 2>&1
    if not errorlevel 1 del /f /q "{current_exe}.old" > nul 2>&1
)

move /y "{desktop_exe}" "{desktop_exe}.old" > nul 2>&1
copy /y "{new_exe}" "{desktop_exe}" > nul 2>&1
if not errorlevel 1 del /f /q "{desktop_exe}.old" > nul 2>&1

start "" "{desktop_exe}"
del "%~f0"
"""
    logging.info(f"[UPDATE] .bat fájl írása: {bat_path}")
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)
    return bat_path


def launch_update_and_exit(bat_path):
    """A csere-.bat elindítása tiszta (PyInstaller-változóktól mentes) környezetben,
    majd azonnali kilépés - a bat várja meg a folyamat leállását és cseréli az exe-t."""
    env = os.environ.copy()
    keys_to_remove = [k for k in env.keys() if k.startswith('_MEI') or k.startswith('_PYI')]
    for k in keys_to_remove:
        env.pop(k, None)

    logging.info("[UPDATE] .bat fájl elindítása és program bezárása...")
    subprocess.Popen(["cmd.exe", "/c", bat_path],
                     creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NO_WINDOW,
                     env=env)
    os._exit(0)
