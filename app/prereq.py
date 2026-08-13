"""Indulási előfeltételek: felmérés, automatikus javítás, döntés a GUI-ról.

MIÉRT VAN EZ A FÁJL (2026-08-13, explicit user decision):
A program régi rendszereken (Windows 7 / 8 / 8.1) nem hibaüzenettel állt meg, hanem
NYOMTALANUL ELTŰNT - a felhasználó annyit látott, hogy "elindítom és nem történik semmi",
a naplóban pedig az utolsó sor a `webview.start() hívása...` volt, háromszor egymás után.
Az ok natív összeomlás (a pywebview a pythonnet-en át .NET Framework-öt tölt be), ami után
SEMMI nem fut le: se kivételkezelő, se watchdog, se naplósor.

Ezért a program MOST MÁR INDULÁS ELŐTT felméri a környezetét, amit tud megjavít, amit nem,
azt kimondja - és mindent naplóz. A felhasználó kérése szó szerint: "gondolkodj elore milyen
problemak johetnek elo es az exe indulas elott oldja meg ha valamiert nem tud elindulni".

A HÁROM SZINT:
  1. MEGJAVÍTJUK        - .NET Framework 4.8 letöltése+telepítése (jóváhagyással),
                          WebView2 Runtime telepítése (a belépési pontban).
  2. KIKERÜLJÜK         - ha a grafikus felület nem indítható, a CLI mód teljes értékű:
                          minden driveres funkció elérhető benne.
  3. NAPLÓZZUK          - amit futásidőben nem lehet orvosolni (PowerShell-generáció,
                          pnputil szintaxisa, TLS-beállítás), az bekerül a naplóba, hogy
                          egy későbbi hibajelentés ne találgatásból induljon.

FONTOS ELV: itt SEMMI nem módosítja a rendszert a felhasználó tudta nélkül. A .NET
telepítése kérdéssel indul, a TLS-beállítást pedig szándékosan csak OLVASSUK (lásd lent).
"""

# === AUTO-IMPORTS ===
import os
import subprocess
import sys
import time
import logging
import winreg
from app import common
from app.common import (
    check_dotnet_framework,
    check_webview2_runtime,
    default_run,
    download_with_cert_fallback,
    file_version,
    is_legacy_windows,
    windows_version,
    DOTNET_RELEASE_MIN,
)
# === /AUTO-IMPORTS ===


# A .NET Framework 4.8 hivatalos webes telepítője (~1,5 MB letöltő, ami utána ~110 MB-ot
# tölt le). Windows 7 SP1 / 8.1 / 10 mind támogatott. Ez az utolsó olyan .NET Framework,
# ami ezekre a rendszerekre települ, és bőven felette van a pythonnet 4.7.2-es minimumának.
DOTNET_WEB_INSTALLER_URL = "https://go.microsoft.com/fwlink/?LinkId=2085155"

# A telepítő maga tölti le a tényleges csomagot, ezért LASSÚ: gyenge gépen, lassú neten
# negyed óra is lehet. Ennél rövidebb korlát egy egyébként haladó telepítést vágna el.
DOTNET_INSTALL_TIMEOUT = 1800  # 30 perc

# A .NET telepítő kilépési kódjai. 1641/3010 = sikeres, de újraindítás kell; 1638 = már van
# ilyen vagy újabb verzió (számunkra siker). Az 5100 a "nem teljesülnek a követelmények" -
# tipikusan hiányzó Windows-frissítés Win7-en, ezt névvel jelezzük.
DOTNET_RC_SUCCESS = (0, 1638)
DOTNET_RC_REBOOT = (1641, 3010)
DOTNET_RC_MESSAGES = {
    1602: "a telepítést megszakították",
    1603: "általános telepítési hiba",
    1638: "már van ilyen vagy újabb .NET verzió a gépen",
    5100: "a gép nem felel meg a követelményeknek (hiányzó Windows-frissítés? Windows 7-en "
          "SP1 + a legfrissebb kumulatív frissítés kell)",
}


def _read_powershell_version():
    """A telepített PowerShell fő verziója a registryből (subprocess nélkül, mert ez
    induláskor fut). Windows 7 = 2.0, Windows 8 = 3.0, 8.1 = 4.0, Windows 10+ = 5.1.

    Miért érdekes: a program PowerShell-parancsainak jó része (Get-CimInstance,
    ConvertTo-Json, Get-PnpDevice, Register-ScheduledTask, Get-Printer, Get-NetAdapter,
    Get-BitLockerVolume) CSAK 3.0/Windows 8 óta létezik. Egy Win7-es hibajelentésnél ez az
    első kérdés."""
    for path in (r"SOFTWARE\Microsoft\PowerShell\3\PowerShellEngine",
                 r"SOFTWARE\Microsoft\PowerShell\1\PowerShellEngine"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                ver, _ = winreg.QueryValueEx(key, "PowerShellVersion")
                if ver:
                    return str(ver)
        except (FileNotFoundError, OSError):
            continue
    return None


def _read_tls12_client_state():
    """A rendszer TLS 1.2 kliens-beállítása (schannel) - CSAK OLVASVA.

    SZÁNDÉKOSAN NEM ÍRJUK: ez rendszerszintű biztonsági beállítás egy ÜGYFÉL gépén,
    a hatályba lépéséhez újraindítás kell, és a program elsődleges letöltési útja (a Python
    saját OpenSSL-je) amúgy sem függ tőle. Olvasni viszont érdemes: ha egy letöltés a
    PowerShell/certutil ágon hasal el egy régi gépen, ez a napló-sor mondja meg, miért.

    Visszatérés: 'engedélyezve' / 'letiltva' / 'alapértelmezett (nincs külön beállítva)'."""
    path = (r"SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL"
            r"\Protocols\TLS 1.2\Client")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            enabled = disabled_default = None
            try:
                enabled, _ = winreg.QueryValueEx(key, "Enabled")
            except (FileNotFoundError, OSError):
                pass
            try:
                disabled_default, _ = winreg.QueryValueEx(key, "DisabledByDefault")
            except (FileNotFoundError, OSError):
                pass
            if enabled == 0:
                return 'letiltva'
            if enabled and not disabled_default:
                return 'engedélyezve'
            return f'részleges (Enabled={enabled}, DisabledByDefault={disabled_default})'
    except (FileNotFoundError, OSError):
        return 'alapértelmezett (nincs külön beállítva)'


def _free_disk_mb(path):
    """Szabad hely MB-ban az adott útvonal meghajtóján, vagy None.

    Miért kell: a program több nagy letöltést végez (WebView2 ~150 MB, .NET ~110 MB,
    stresstools.zip ~620 MB, egy GPU-driver akár 1,2 GB). Egy tele rendszerlemez terepen
    már okozott hibát ([Errno 28]), és a naplóból utólag nem lehetett látni."""
    try:
        import ctypes
        free = ctypes.c_ulonglong(0)
        if ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(path), None, None, ctypes.pointer(free)):
            return free.value // (1024 * 1024)
    except Exception as e:
        logging.debug(f"[PREREQ] Szabad lemezhely nem olvasható ({path}): {e}")
    return None


def _pnputil_syntax(build):
    """Melyik pnputil-szintaxist ismeri ez a Windows.

    A program végig a PERJELES alakot használja (/delete-driver, /add-driver,
    /export-driver, /scan-devices), ami csak Windows 10 1607 (build 14393) óta létezik;
    régebbi rendszereken a kötőjeles alak kell (-e, -a, -d, -f -d), az /export-driver és a
    /scan-devices pedig egyáltalán nem elérhető. Ezt futásidőben NEM tudjuk megkerülni -
    de a naplóban látszania kell, mert egy Win8.1-es "nem törli a drivert" jelentésnél ez a
    magyarázat."""
    if build >= 15063:
        return 'új (perjeles), /scan-devices is elérhető'
    if build >= 14393:
        return 'új (perjeles), de /scan-devices NINCS (1703+ kell)'
    return 'RÉGI (kötőjeles: -e/-a/-d/-f) - a program perjeles hívásai NEM működnek'


def collect_environment():
    """Minden induláskor releváns környezeti adat egy dict-ben. Csak registry/API
    olvasások, egyetlen subprocess sincs benne - ez induláskor fut, nem lassíthat."""
    major, minor, build, os_name = windows_version()
    dotnet_ok, dotnet_release, dotnet_name = check_dotnet_framework()
    wv2_ok, wv2_info = check_webview2_runtime()
    env = {
        'os_name': os_name,
        'os_version': f"{major}.{minor}.{build}",
        'os_build': build,
        'legacy': is_legacy_windows(),
        'arch': os.environ.get('PROCESSOR_ARCHITECTURE', '?'),
        'winpe': os.environ.get('SystemDrive', 'C:') == 'X:',
        'admin': bool(common.is_admin()),
        'dotnet_ok': dotnet_ok,
        'dotnet_release': dotnet_release,
        'dotnet_name': dotnet_name,
        'webview2_ok': wv2_ok,
        'webview2': wv2_info if wv2_ok else None,
        'powershell': _read_powershell_version(),
        'tls12': _read_tls12_client_state(),
        'free_mb': _free_disk_mb(os.environ.get('SystemDrive', 'C:') + '\\'),
        'pnputil': _pnputil_syntax(build),
        'frozen': bool(getattr(sys, 'frozen', False)),
    }
    try:
        import webview as _wv
        env['webview2_sdk'] = file_version(
            os.path.join(os.path.dirname(_wv.__file__), 'lib', 'Microsoft.Web.WebView2.Core.dll'))
    except Exception:
        env['webview2_sdk'] = None
    try:
        import importlib.metadata as _md
        env['pywebview'] = _md.version('pywebview')
    except Exception:
        env['pywebview'] = None
    return env


def log_environment(env=None):
    """A környezet-kép a naplóba, egy összefüggő `[PREREQ]` blokkban.

    Rule 0 (CLAUDE.md): ami nincs a logban, az nem történt meg. Ez a blokk az, amiből egy
    régi gépről érkező hibajelentés önmagában megválaszolható - korábban még az sem derült
    ki a naplóból, milyen Windowson futott a program."""
    env = env or collect_environment()
    logging.info("[PREREQ] " + "-" * 56)
    logging.info(f"[PREREQ] Rendszer: {env['os_name']} ({env['os_version']}) {env['arch']}"
                 f"{' [WinPE]' if env['winpe'] else ''}"
                 f"{' [RÉGI RENDSZER]' if env['legacy'] else ''}")
    logging.info(f"[PREREQ] Admin: {env['admin']} | Fagyasztott exe: {env['frozen']} | "
                 f"Szabad hely a rendszerlemezen: "
                 f"{str(env['free_mb']) + ' MB' if env['free_mb'] is not None else 'ismeretlen'}")

    net_msg = f"[PREREQ] .NET Framework: {env['dotnet_name']} (Release={env['dotnet_release']})"
    if env['dotnet_ok']:
        logging.info(net_msg + " - MEGFELELŐ a grafikus felülethez")
    else:
        logging.warning(net_msg + f" - TÚL RÉGI (minimum 4.7.2 / {DOTNET_RELEASE_MIN}); "
                                  f"enélkül a felület natívan omlik össze")

    if env['webview2_ok']:
        logging.info(f"[PREREQ] WebView2 Runtime: {env['webview2']}")
    else:
        logging.warning("[PREREQ] WebView2 Runtime: NINCS vagy túl régi")
    logging.info(f"[PREREQ] pywebview: {env['pywebview'] or 'ismeretlen'}, "
                 f"becsomagolt WebView2 SDK: {env['webview2_sdk'] or 'ismeretlen'}")

    ps = env['powershell']
    if ps and str(ps).startswith('2'):
        # PS 2.0: a program parancsainak jelentős része nem is létezik ezen a gépen.
        logging.warning(f"[PREREQ] PowerShell: {ps} - EZ RÉGI. A Get-CimInstance, "
                        f"ConvertTo-Json, Get-PnpDevice, Register-ScheduledTask, Get-Printer, "
                        f"Get-NetAdapter, Get-BitLockerVolume mind 3.0+ (Windows 8) - ezek a "
                        f"funkciók ezen a gépen hibázni fognak")
    else:
        logging.info(f"[PREREQ] PowerShell: {ps or 'ismeretlen'}")

    logging.info(f"[PREREQ] TLS 1.2 (kliens, schannel): {env['tls12']}")
    pnp_msg = f"[PREREQ] pnputil szintaxis: {env['pnputil']}"
    if env['os_build'] < 14393:
        logging.warning(pnp_msg)
    else:
        logging.info(pnp_msg)
    logging.info("[PREREQ] " + "-" * 56)
    return env


def install_dotnet_framework(log=None, timeout=DOTNET_INSTALL_TIMEOUT):
    """A .NET Framework 4.8 letöltése és telepítése.

    A letöltés a projekt KÖZÖS letöltőjén megy (Python -> PowerShell: Invoke-WebRequest /
    WebClient / certutil), mert pont ezeken a régi gépeken hasal el a Python TLS-verme -
    a lánc utolsó, natív certutil-ága viszont mérve PowerShell 2.0 alatt is működik.

    A telepítő ABLAKA SZÁNDÉKOSAN LÁTSZIK (/passive): egy 10-20 perces, teljesen néma
    művelet pontosan az a helyzet, amit a felhasználó kifogásolt ("nem tudom, hogy fagyott-e").
    A /norestart is szándékos: a gépet a felhasználó indítsa újra, ne mi, a háta mögött.

    log: opcionális callback(str) a képernyőre íráshoz (a napló mindig megy).
    Visszatérés: (sikeres, újraindítás_kell, üzenet)."""
    def say(msg):
        logging.info(f"[PREREQ-NET] {msg}")
        if log:
            try:
                log(msg)
            except Exception as e:
                logging.debug(f"[PREREQ-NET] A log-callback hibázott: {e}")

    import tempfile
    dest = os.path.join(tempfile.gettempdir(), 'dv_ndp48_web.exe')
    say("A .NET Framework 4.8 telepítőjének letöltése...")
    logging.info(f"[PREREQ-NET] Forrás: {DOTNET_WEB_INSTALLER_URL} -> {dest}")

    try:
        if os.path.exists(dest):
            os.remove(dest)
    except OSError as e:
        logging.debug(f"[PREREQ-NET] A korábbi telepítő nem törölhető: {e}")

    try:
        download_with_cert_fallback(
            default_run, DOTNET_WEB_INSTALLER_URL, dest,
            timeout=120, ps_timeout=600, log_tag='PREREQ-NET',
            error_msg="A .NET telepítő letöltése nem sikerült.")
    except Exception as e:
        logging.error(f"[PREREQ-NET] A letöltés elhasalt: {e}")
        return (False, False, f"A .NET telepítő letöltése nem sikerült: {e}")

    size = os.path.getsize(dest) if os.path.exists(dest) else 0
    # A webes telepítő ~1,5 MB. Egy ennél sokkal kisebb fájl nem a telepítő (hibaoldal,
    # átirányítás) - ezt a naplóból utólag nem lehetne kitalálni, ezért itt buktatjuk el.
    if size < 500 * 1024:
        logging.error(f"[PREREQ-NET] A letöltött fájl gyanúsan kicsi ({size} bájt) - "
                      f"valószínűleg nem a telepítő jött le.")
        return (False, False, f"A letöltött telepítő hibás ({size} bájt).")
    say(f"Letöltve ({size // 1024} KB). Telepítés indul...")
    logging.info(f"[PREREQ-NET] Telepítő indítása: {dest} /passive /norestart "
                 f"(időkorlát: {timeout}s)")

    t0 = time.monotonic()
    try:
        # NINCS CREATE_NO_WINDOW és nincs capture_output: hadd látszódjon a Microsoft saját
        # folyamatjelzője, és ne a mi pufferünkbe menjen a kimenete.
        result = subprocess.run([dest, '/passive', '/norestart'],
                                stdin=subprocess.DEVNULL, timeout=timeout)
        rc = result.returncode
    except subprocess.TimeoutExpired:
        logging.error(f"[PREREQ-NET] A telepítő {timeout}s alatt sem fejezte be.")
        return (False, False, "A .NET telepítő túllépte az időkorlátot. Indítsd újra a gépet, "
                              "és próbáld újra.")
    except Exception as e:
        logging.error(f"[PREREQ-NET] A telepítő indítása nem sikerült: {e}")
        return (False, False, f"A .NET telepítő nem indult el: {e}")
    finally:
        try:
            os.remove(dest)
        except OSError as e:
            logging.debug(f"[PREREQ-NET] A telepítő nem törölhető: {e}")

    elapsed = int(time.monotonic() - t0)
    detail = DOTNET_RC_MESSAGES.get(rc, '')
    logging.info(f"[PREREQ-NET] A telepítő lefutott: returncode={rc} "
                 f"({detail or 'nincs külön jelentése'}), {elapsed}s alatt.")

    if rc in DOTNET_RC_REBOOT:
        return (True, True, "A .NET Framework 4.8 telepítve - ÚJRAINDÍTÁS SZÜKSÉGES.")
    if rc in DOTNET_RC_SUCCESS:
        # Az ellenőrzés a mérés, nem a kilépési kód: ha a registry szerint mégsem elég új,
        # az újraindítás után szokott rendbe jönni.
        ok_now, release_now, name_now = check_dotnet_framework()
        logging.info(f"[PREREQ-NET] Telepítés utáni állapot: {name_now} (Release={release_now})")
        if ok_now:
            return (True, False, f"A .NET Framework rendben ({name_now}).")
        return (True, True, f"A telepítő sikert jelzett, de a rendszer még a régi verziót "
                            f"mutatja ({name_now}) - ÚJRAINDÍTÁS SZÜKSÉGES.")
    return (False, False, f"A .NET telepítő hibakóddal állt le ({rc})"
                          f"{' - ' + detail if detail else ''}.")


def gui_blocker(env=None):
    """Van-e olyan hiányzó előfeltétel, ami miatt a grafikus felület el sem indulhat?

    Visszatérés: None, ha mehet a GUI, különben (kulcs, rövid_leírás). A kulcs alapján a
    hívó dönti el, felajánlja-e a javítást ('dotnet') vagy csak tájékoztat."""
    env = env or collect_environment()
    if not env['dotnet_ok']:
        return ('dotnet', f"a .NET Framework túl régi ({env['dotnet_name']}), "
                          f"a grafikus felülethez 4.7.2 vagy újabb kell")
    return None
