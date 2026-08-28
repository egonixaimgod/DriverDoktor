"""Windows & Office aktiválás - közös mag (állapot, gyári kulcs, kulcstelepítés, aktiválás).

MIÉRT WMI-BŐL OLVAS ÉS CSAK ÍRÁSRA HASZNÁL slmgr-t: az `slmgr` kimenete LOKALIZÁLT - magyar
Windowson magyarul ír, és ennek a projektnek már van sebhelye a lokalizált konzol-szöveg
elemzéséből (lásd CLAUDE.md: a magyar pnputil "törlése nem sikerült" sora egy HIBÁS törlést
jelentett SIKERNEK). Ezért minden ÁLLAPOT a `SoftwareLicensingProduct`/`SoftwareLicensingService`
WMI-osztályokból jön, számkódként; az `slmgr` csak a három írási lépést végzi, és utána a
sikert megint a WMI mondja meg, nem a parancs kimenete.

MIÉRT `cscript //nologo`: az `slmgr` egy VBScript, és a `wscript` motorral MODÁLIS ABLAKOKAT
dob fel eredményenként - egy felügyelet nélküli GUI-folyamat ott örökre megállna. A
`cscript //nologo` ugyanazt stdout-ra írja.

A KMS-HOSTRÓL: a `/skms` a szervezet SAJÁT KMS-kiszolgálójára mutat (volume licenc), ezt a
technikus adja meg - a programban nincs, és nem is lehet, előre beírt kiszolgáló.
"""
import os
import re
import json
import logging

# A Windows licenc-alkalmazás azonosítója a SoftwareLicensingProduct-ban (fix GUID,
# minden Windowson ez). Enélkül a lekérdezés az összes terméket visszaadná (Office is).
WINDOWS_APP_ID = '55c92734-d682-4d71-983e-d6ec3f16059f'

# A SoftwareLicensingProduct.LicenseStatus számkódjai. A szöveget MI adjuk (magyarul),
# így nem függünk a rendszer nyelvétől.
LICENSE_STATUS = {
    0: ('Nincs aktiválva', 'error'),
    1: ('Aktiválva', 'ok'),
    2: ('Türelmi idő (még nincs aktiválva)', 'warning'),
    3: ('Lejárt türelmi idő', 'warning'),
    4: ('Nem eredetinek jelölt türelmi idő', 'error'),
    5: ('Értesítési állapot (aktiválás szükséges)', 'error'),
    6: ('Meghosszabbított türelmi idő', 'warning'),
}

# A licenc CSATORNÁJA - ez dönti el, hogy újratelepítés után magától aktiválódik-e.
CHANNEL_HINTS = {
    'oem': 'OEM (gyári, a BIOS-ban van a kulcs)',
    'retail': 'Retail (dobozos/letöltött, átvihető másik gépre)',
    'volume': 'Volume (céges, KMS/MAK)',
}

# A Microsoft NYILVÁNOSAN közzétett KMS-kliens telepítőkulcsai (GVLK). Ezek nem titkosak
# és nem "feltört" kulcsok: a Microsoft pont azért teszi közzé őket, hogy a KMS-es gépekre
# fel lehessen tenni. Önmagukban NEM aktiválnak semmit - ahhoz kell egy elérhető KMS-host.
# Forrás: Microsoft "KMS client setup keys" dokumentáció.
GVLK_KEYS = (
    # (a kiadás felismerhető darabja a Description/Caption mezőben, GVLK, olvasható név)
    ('professional workstation', 'NRG8B-VKK3Q-CXVCJ-9G2XF-6Q84J', 'Windows 10/11 Pro for Workstations'),
    ('professionaln',            'MH37W-N47XK-V7XM9-C7227-GCQG9', 'Windows 10/11 Pro N'),
    ('professional education',   '6TP4R-GNPTD-KYYHQ-7B7DP-J447Y', 'Windows 10/11 Pro Education'),
    ('professional',             'W269N-WFGWX-YVC9B-4J6C9-T83GX', 'Windows 10/11 Pro'),
    ('enterprise ltsc 2021',     'M7XTQ-FN8P6-TTKYV-9D4CC-J462D', 'Windows 10 Enterprise LTSC 2021'),
    ('enterprisen',              'DPH2V-TTNVB-4X9Q3-TJR4H-KHJW4', 'Windows 10/11 Enterprise N'),
    ('enterprise',               'NPPR9-FWDCX-D2C8J-H872K-2YT43', 'Windows 10/11 Enterprise'),
    ('educationn',               '2WH4N-8QGBV-H22JP-CT43Q-MDWWJ', 'Windows 10/11 Education N'),
    ('education',                'NW6C2-QMPVW-D7KKK-3GKT6-VCFB2', 'Windows 10/11 Education'),
    ('coren',                    '3KHY7-WNT83-DGQKR-F7HPR-844BM', 'Windows 10/11 Home N'),
    ('core single language',     '7HNRX-D7KGG-3K4RQ-4WPJ4-YTDFH', 'Windows 10/11 Home Single Language'),
    ('core',                     'TX9XD-98N7V-6WMQ6-BX7FG-H8Q99', 'Windows 10/11 Home'),
)

# ===========================================================================
#  IDE ÍRD BE A KMS-KISZOLGÁLÓ CÍMÉT
# ---------------------------------------------------------------------------
#  Például:  KMS_HOST = 'kms.sajatceg.hu'
#            KMS_HOST = '192.168.1.50'
#            KMS_HOST = 'kms.sajatceg.hu:1688'      (ha nem az alap 1688-as port)
#
#  MIRE KELL: csak akkor jut szerephez, ha a gépnek NINCS gyári kulcsa a BIOS-ban.
#  Olyankor a kiadáshoz tartozó nyilvános KMS-kulcs (GVLK) megy fel, és az ehhez a
#  kiszolgálóhoz fordul aktiválásért.
#
#  HA VAN GYÁRI KULCS A BIOS-BAN, EZ AZ ÉRTÉK NEM SZÁMÍT: ott mindig a gyári kulcsot
#  használjuk, és az aktiválás a Microsoft felé megy - KMS-kiszolgáló nélkül.
#
#  Üresen hagyva a program nem állít be KMS-kiszolgálót; a felület ilyenkor kiírja,
#  hogy gyári kulcs nélküli gépet nem tud aktiválni.
# ===========================================================================
KMS_HOST = 'kms8.msguides.com'


# Az `slmgr /ato` egy elérhetetlen KMS-hostra hosszan próbálkozik - időkorlát nélkül a
# folyamat percekig állna. A _run a TimeoutExpired-t elnyeli (CMD_TIMEOUT_RETURNCODE).
SLMGR_TIMEOUT = 180

# Egy KMS-aktiválás 180 napra szól, és a kliens magától megújítja. Ezt kiírjuk, mert a
# technikusnak tudnia kell, hogy ez NEM örökre szóló aktiválás.
KMS_RENEWAL_NOTE = ('A KMS-aktiválás 180 napra szól, és a gép magától megújítja, amíg eléri '
                    'a KMS-kiszolgálót. Ha az ügyfél kiviszi a hálózatból, lejár.')

# Az Office aktiválás-állapotát az ospp.vbs mondja meg; a helye Office-verziónként más.
OSPP_DIRS = (
    r'Microsoft Office\Office16', r'Microsoft Office\Office15', r'Microsoft Office\Office14',
    r'Microsoft Office\root\Office16', r'Microsoft Office\root\Office15',
)


WINDOWS_STATUS_PS = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$o = [ordered]@{}; "
    "try { $s = Get-CimInstance SoftwareLicensingService; "
    "  $o.OemKey = $s.OA3xOriginalProductKey; $o.KmsHost = $s.KeyManagementServiceMachine; "
    "  $o.KmsPort = $s.KeyManagementServicePort } catch {}; "
    # Csak a TELEPÍTETT Windows-termék érdekel: PartialProductKey nem null.
    f"try {{ $p = Get-CimInstance SoftwareLicensingProduct -Filter \"ApplicationId='{WINDOWS_APP_ID}' "
    "AND PartialProductKey IS NOT NULL\" | Select-Object -First 1; "
    "  if ($p) { $o.Name = $p.Name; $o.Description = $p.Description; $o.Status = $p.LicenseStatus; "
    "    $o.StatusReason = $p.LicenseStatusReason; $o.PartialKey = $p.PartialProductKey; "
    "    $o.GraceMinutes = $p.GracePeriodRemaining; $o.ProductKeyChannel = $p.ProductKeyChannel; "
    "    $o.KmsMachine = $p.KeyManagementServiceMachine } } catch {}; "
    "try { $os = Get-CimInstance Win32_OperatingSystem; "
    "  $o.OsCaption = $os.Caption; $o.OsVersion = $os.Version; $o.OsBuild = $os.BuildNumber } catch {}; "
    "$o | ConvertTo-Json -Compress"
)


def _ps_json(run, script, timeout=120, tag='WINACT'):
    """Egy PowerShell-lekérdezés JSON-válasza dictként. Hibánál üres dict + WARNING."""
    try:
        res = run(["powershell", "-NoProfile", "-Command", script],
                  encoding='utf-8', timeout=timeout)
        raw = (getattr(res, 'stdout', '') or '').strip()
        if not raw:
            logging.warning(f"[{tag}] A lekérdezés üres választ adott (rc="
                            f"{getattr(res, 'returncode', '?')}).")
            return {}
        return json.loads(raw) or {}
    except Exception as e:
        logging.warning(f"[{tag}] A lekérdezés sikertelen: {e}")
        return {}


def collect_windows_activation(run):
    """A Windows aktiválási állapota. MINDIG ad vissza dictet.

    Kulcsok: activated, status_code, status_text, status_color, edition, os_caption,
    os_build, partial_key, oem_key, channel, channel_text, kms_host, grace_days,
    gvlk (a kiadáshoz illő nyilvános KMS-kulcs), gvlk_name."""
    info = _ps_json(run, WINDOWS_STATUS_PS)
    try:
        code = int(info.get('Status'))
    except (TypeError, ValueError):
        code = -1
    text, color = LICENSE_STATUS.get(code, ('Ismeretlen állapot', 'unknown'))

    channel = str(info.get('ProductKeyChannel') or '').strip()
    channel_text = ''
    for key, label in CHANNEL_HINTS.items():
        if key in channel.lower():
            channel_text = label
            break

    grace = info.get('GraceMinutes')
    try:
        grace_days = int(grace) // 1440 if grace else 0
    except (TypeError, ValueError):
        grace_days = 0

    desc = str(info.get('Description') or '')
    name = str(info.get('Name') or '')
    gvlk, gvlk_name = gvlk_for_edition(f"{name} {desc} {info.get('OsCaption') or ''}")

    out = {
        'activated': code == 1,
        'status_code': code,
        'status_text': text,
        'status_color': color,
        'edition': name or desc,
        'os_caption': str(info.get('OsCaption') or ''),
        'os_build': str(info.get('OsBuild') or ''),
        'partial_key': str(info.get('PartialKey') or ''),
        # A gyári (OEM) kulcs a UEFI MSDM táblájából. Újratelepítés után ez az, ami
        # miatt a gép magától aktiválódik - ha nem tette, ezzel kézzel megoldható.
        'oem_key': str(info.get('OemKey') or '').strip(),
        'channel': channel,
        'channel_text': channel_text,
        'kms_host': str(info.get('KmsMachine') or info.get('KmsHost') or '').strip(),
        'grace_days': grace_days,
        'gvlk': gvlk,
        'gvlk_name': gvlk_name,
    }
    logging.info(f"[WINACT] Windows: '{out['edition']}' | állapot={code} ({text}) | "
                 f"csatorna='{channel}' | részkulcs={out['partial_key'] or '-'} | "
                 f"OEM-kulcs a BIOS-ban: {'IGEN' if out['oem_key'] else 'nincs'} | "
                 f"KMS-host='{out['kms_host'] or '-'}'")
    return out


def gvlk_for_edition(text):
    """A kiadáshoz illő NYILVÁNOS KMS-kliens kulcs (GVLK). (kulcs, olvasható név).

    A sorrend számít: a 'professional workstation' előbb van, mint a 'professional',
    különben a rövidebb minta elnyelné a hosszabbat."""
    low = (text or '').lower()
    for needle, key, name in GVLK_KEYS:
        if needle in low:
            return key, name
    # Ismeretlen kiadásnál a Pro a legvalószínűbb a szervizben - de megmondjuk, hogy tipp.
    return GVLK_KEYS[3][1], GVLK_KEYS[3][2] + ' (feltételezett kiadás)'


def normalize_key(key):
    """A beírt kulcs egységesítése: nagybetű, csak A-Z0-9, 5-ös csoportokban kötőjellel.
    A technikus vágólapról másol, ahol simán lehet szóköz vagy sortörés."""
    raw = re.sub(r'[^A-Za-z0-9]', '', str(key or '')).upper()
    if len(raw) != 25:
        return ''
    return '-'.join(raw[i:i + 5] for i in range(0, 25, 5))


def is_valid_kms_host(host):
    """Elfogadható-e KMS-host névnek. Szándékosan megengedő (belső gépnév, FQDN, IP),
    de a szemetet (szóköz, séma, útvonal) kiszűri - az `slmgr /skms` amúgy is némán
    elfogadná, és utána az aktiválás hasalna el érthetetlenül."""
    h = str(host or '').strip()
    if not h or len(h) > 255:
        return False
    # Opcionális :port
    if ':' in h:
        h, _, port = h.rpartition(':')
        if not port.isdigit() or not (0 < int(port) < 65536):
            return False
    return bool(re.match(r'^[A-Za-z0-9]([A-Za-z0-9\-\.]*[A-Za-z0-9])?$', h))


def _slmgr(run, *args, timeout=SLMGR_TIMEOUT):
    """Egy slmgr-hívás. `cscript //nologo`-val, hogy ne modális ablakot kapjunk."""
    slmgr_path = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'System32', 'slmgr.vbs')
    cmd = ['cscript', '//nologo', slmgr_path] + list(args)
    return run(cmd, timeout=timeout)


def install_product_key(run, key):
    """slmgr /ipk - a termékkulcs telepítése. Visszatérés: (siker, kimenet)."""
    key = normalize_key(key)
    if not key:
        return False, 'A kulcs formátuma hibás (25 karakter kell, 5x5 csoportban).'
    # A kulcsot NEM titkosítjuk el a naplóban: a technikusnak pont ez kell egy hibánál,
    # és nem jelszó - a gép matricáján/BIOS-ában amúgy is ott van.
    logging.info(f"[WINACT] Termékkulcs telepítése: {key}")
    res = _slmgr(run, '/ipk', key)
    return _slmgr_ok(res), _slmgr_text(res)


def set_kms_host(run, host):
    """slmgr /skms - a KMS-kiszolgáló beállítása. Üres hostnál nem csinál semmit."""
    host = str(host or '').strip()
    if not host:
        return True, '(nincs megadva KMS-kiszolgáló, ez a lépés kimarad)'
    if not is_valid_kms_host(host):
        return False, f'A KMS-kiszolgáló neve érvénytelen: {host}'
    logging.info(f"[WINACT] KMS-kiszolgáló beállítása: {host}")
    res = _slmgr(run, '/skms', host)
    return _slmgr_ok(res), _slmgr_text(res)


def clear_kms_host(run):
    """slmgr /ckms - a beállított KMS-kiszolgáló törlése (vissza az alapértelmezettre)."""
    logging.info("[WINACT] A beállított KMS-kiszolgáló törlése (/ckms).")
    res = _slmgr(run, '/ckms')
    return _slmgr_ok(res), _slmgr_text(res)


def activate(run):
    """slmgr /ato - aktiválás. FIGYELEM: a kimenete NEM a végső szó, a hívónak WMI-ből
    kell ellenőriznie (lásd a modul fejlécét)."""
    logging.info("[WINACT] Aktiválás indítása (/ato).")
    res = _slmgr(run, '/ato')
    return _slmgr_ok(res), _slmgr_text(res)


def _slmgr_ok(res):
    from app.common import CMD_TIMEOUT_RETURNCODE
    rc = getattr(res, 'returncode', 1)
    if rc == CMD_TIMEOUT_RETURNCODE:
        logging.warning("[WINACT] Az slmgr időtúllépéssel leállt (elérhetetlen KMS-kiszolgáló?).")
        return False
    return rc == 0


def _slmgr_text(res):
    """Az slmgr kimenete a technikusnak. Lokalizált, ezért CSAK megjelenítjük - soha nem
    hozunk belőle döntést (lásd a modul fejlécét)."""
    out = (getattr(res, 'stdout', '') or '').strip()
    err = (getattr(res, 'stderr', '') or '').strip()
    txt = '\n'.join(t for t in (out, err) if t)
    return txt or '(nincs kimenet)'


# ---------------------------------------------------------------------------
# OFFICE
# ---------------------------------------------------------------------------

def find_ospp(run=None):
    """Az ospp.vbs megkeresése (Office aktiválás-kezelő). None, ha nincs Office."""
    roots = [os.environ.get('ProgramFiles', r'C:\Program Files'),
             os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')]
    for root in roots:
        for sub in OSPP_DIRS:
            p = os.path.join(root, sub, 'ospp.vbs')
            if os.path.isfile(p):
                logging.info(f"[WINACT] Office aktiválás-kezelő: {p}")
                return p
    logging.info("[WINACT] Nem található ospp.vbs - vagy nincs Office, vagy Microsoft Store-os/M365 verzió.")
    return None


OFFICE_WMI_PS = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    f"Get-CimInstance SoftwareLicensingProduct -Filter \"ApplicationId<>'{WINDOWS_APP_ID}' "
    "AND PartialProductKey IS NOT NULL\" | "
    "Select-Object Name, Description, LicenseStatus, PartialProductKey | ConvertTo-Json -Compress"
)


def collect_office_activation(run):
    """A telepített (nem-Windows) licencelt termékek: jellemzően az Office.

    A WMI-t használjuk, nem az ospp.vbs kimenetét - ugyanaz az érv, mint a Windowsnál:
    az ospp szövege lokalizált. Az ospp.vbs helyét viszont visszaadjuk, mert az az
    eszköz, amivel a technikus kézzel tud beavatkozni."""
    out = {'products': [], 'ospp': find_ospp(run)}
    data = None
    try:
        res = run(["powershell", "-NoProfile", "-Command", OFFICE_WMI_PS],
                  encoding='utf-8', timeout=120)
        raw = (getattr(res, 'stdout', '') or '').strip()
        if raw:
            data = json.loads(raw)
    except Exception as e:
        logging.warning(f"[WINACT] Az Office-állapot lekérdezése sikertelen: {e}")
        return out

    if isinstance(data, dict):
        data = [data]
    for row in (data or []):
        try:
            code = int(row.get('LicenseStatus'))
        except (TypeError, ValueError):
            code = -1
        text, color = LICENSE_STATUS.get(code, ('Ismeretlen állapot', 'unknown'))
        out['products'].append({
            'name': str(row.get('Name') or ''),
            'description': str(row.get('Description') or ''),
            'partial_key': str(row.get('PartialProductKey') or ''),
            'status_code': code, 'status_text': text, 'status_color': color,
            'activated': code == 1,
        })
    logging.info(f"[WINACT] Office/egyéb licencelt termék: {len(out['products'])} db "
                 f"({', '.join(p['name'][:40] for p in out['products']) or 'nincs'})")
    return out
