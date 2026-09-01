"""Gyártói (OEM) driver-katalógusok - a NEGYEDIK driver-forrás, közös mag.

MIÉRT VAN SZÜKSÉG RÁ (terepi eset, ThinkPad T580, 2026-08-24, log a debug_logok/-ban):
az AutoFix 116 third-party csomagot törölt, és a lánc végére 30 nem került vissza. Egy
részük a klónozott image idegen maradéka volt (azok hiánya HELYES), de volt köztük a gép
saját hardveréhez tartozó is. Ezek egy részét sem a WU Agent, sem a Microsoft Update
Catalog nem szállítja - a gépgyártó a SAJÁT frissítő-csatornáján adja (Lenovo Vantage /
System Update, Dell Command Update, HP Image Assistant).

MI EZ ÉS MI NEM (CLAUDE.md, "THE PRODUCT'S WHOLE POINT: re-driver from ZERO"):
ez egy VALÓDI FORRÁS, ahonnan a driver NULLÁRÓL letölthető és telepíthető. Nem a gép régi
driverének eltétele és visszarakása - az tiltott, mert egy friss Windowsnál vagy eleve
hiányzó drivernél semmit nem érne, és mert amit a lánc töröl, az definíció szerint a rossz
driver. Ez a modul a gyártó AKTUÁLIS csomagját hozza le, ugyanúgy, ahogy a WU vagy a
Microsoft-katalógus tenné.

MI EZ A "UNIVERZÁLIS" KÉRDÉSBEN (fontos, hogy senki ne értse félre):
az univerzális driver-forrás a WU Agent + a Microsoft Update Catalog - azok MINDEN gépen,
minden márkán működnek, és minden gyártó oda publikálja a WHQL-drivereit. Ez a modul
RÁADÁS azokra a gépekre, ahol a gyártó gépi olvasásra alkalmas katalógust publikál. Ha egy
géphez nincs ilyen (Acer, összerakott PC, egyedi alaplap), ez a kör egyszerűen ÜRESEN tér
vissza, és a gép semmit nem veszít: a többi forrás változatlanul lefut rá. Soha ne váljon
ez a modul feltétellé, és soha ne legyen benne modellre szabott javítás.

MÉRT ADATOK (dev gép, 2026-08-25) - ezekre épül a kód, ne tippeld újra:
  * Lenovo: `https://download.lenovo.com/catalog/<MTM4>_<Win10|Win11>.xml` -> 10-17 KB,
    56 csomag a T580-ra. Minden csomag-leíró tartalmaz `<_PnPID>` HARDVER-AZONOSÍTÓKAT,
    tehát a meglévő HWID-illesztő közvetlenül használható.
  * A gyártói csomag KICSOMAGOLHATÓ TELEPÍTÉS NÉLKÜL:
    `n20gx20w.exe /VERYSILENT /DIR=<mappa> /EXTRACT="YES"` -> rc=0, 7,5 mp, 111 fájl,
    köztük az INF. Így a telepítés a már jól ismert `pnputil /add-driver /install` úton
    megy, ismeretlen installer futtatása NÉLKÜL. Ez oldja fel a CLAUDE.md korábbi
    aggályát ("blind-shipping untested silent OEM installers").
  * Dell: `https://downloads.dell.com/catalog/DriverPackCatalog.cab` -> 0,32 MB, kibontva
    3,1 MB XML; `CatalogPC.cab` -> 2,92 MB, kibontva 54,9 MB. MINDKETTŐ **UTF-16**
    kódolású - utf-8-ként olvasva néma bájtszemét lesz belőle (ugyanaz a csapda, amit a
    wu_core._read_text_best_effort az INF-eknél kezel). Kulcs: `systemID` + modellnév.
  * HP: `https://ftp.hp.com/pub/caps-softpaq/cmit/HPClientDriverPackCatalog.cab` -> 0,18 MB,
    kibontva 2,1 MB XML (`<NewDataSet>`, Product/Softpaq táblák).
"""
import io
import os
import re
import ssl
import json
import time
import shutil
import logging
import subprocess
import urllib.request

from app.common import _app_data_dir

# ---------------------------------------------------------------------------
# Végpontok. Egy helyen, hogy ha egy gyártó URL-t vált, egy sort kelljen írni.
# ---------------------------------------------------------------------------
LENOVO_CATALOG_URL = "https://download.lenovo.com/catalog/{mtm}_{os}.xml"
DELL_DRIVERPACK_CATALOG = "https://downloads.dell.com/catalog/DriverPackCatalog.cab"
DELL_BASE = "https://downloads.dell.com/"
HP_DRIVERPACK_CATALOG = "https://ftp.hp.com/pub/caps-softpaq/cmit/HPClientDriverPackCatalog.cab"

HTTP_UA = {'User-Agent': 'Mozilla/5.0'}
HTTP_TIMEOUT = 60
# A katalógus-válaszok gyorsítótára: egy lánc 3-4 lábon át fut, és mindegyik ugyanazt a
# katalógust kérdezné le újra. Napokban.
CATALOG_CACHE_DAYS = 3

# ---------------------------------------------------------------------------
# A TELJES GÉPRE SZÓLÓ (Dell/HP) DRIVER PACKEK KI VANNAK KAPCSOLVA
# (explicit user decision, 2026-09-01: "ez a dell pack baromsag nem is kell bele")
#
# MI KÜLÖNBSÉG: ez KIZÁRÓLAG a `whole_machine` packekre vonatkozik - a Dell és a HP
# több száz MB - 1+ GB méretű, TELJES gépre szóló csomagjaira. A Lenovo per-eszköz
# csomagjai (`<_PnPID>` hardver-azonosítókkal) VÁLTOZATLANUL futnak: azok célzottak,
# kicsik (a T580 UltraNav-csomagja 27,4 MB volt), és a T580-nál bizonyítottan ez volt
# az EGYETLEN forrás, ami a touchpadot megtalálta. Az ő kivételük valódi veszteség lenne.
#
# MIÉRT KELLETT KIVENNI - négy, egymástól független ok, mind mérve:
#  1. STRUKTURÁLISAN NEM TUD DÖNTENI. A `whole_machine` pack `pnpids`-e ÜRES, tehát nincs
#     eszköze (`dev is None`), amihez a verzióját hasonlítani lehetne - `_oem_already_current`
#     ezért definíció szerint MINDIG "telepítsd"-et ad. A program tehát nem tudja, és nem is
#     tudhatja meg, hogy a csomag hoz-e bármi újat: vaktában tölti le, minden gépen, mindig.
#  2. AZ IDŐ, AMIT ELVISZ. Mérve (2026-09-01, Dell Latitude 5580, Build 288): a
#     `5580-win10-A13-JRG2W.CAB` letöltése **11 perc 33 mp** volt - a 82 perces lánc
#     egyhetede -, majd a kicsomagolás azonnal elbukott (lásd a 3. pontot), tehát a
#     teljes 11,5 perc tiszta veszteség lett. A HP-nál ugyanez már dokumentálva volt:
#     az `sp92706` LÁBANKÉNT ~7 percet vitt el, amíg az `oem_done` mankó meg nem született.
#  3. AMIT LETÖLTÖTT, AZT KI SEM TUDTA CSOMAGOLNI. A Dell whole-machine packja `.CAB`,
#     az `extract_vendor_package` viszont mind a 4 kapcsolókészletével önkicsomagoló
#     `.exe`-t feltételez -> `[WinError 193] %1: nem Win32 alkalmazás`, négyszer. Ez a hiba
#     minden Dell gépen, minden láncon elsült volna.
#  4. AMIT HOZNA, AZT A KATALÓGUS ÚGYIS HOZZA. Ugyanabban a futásban a Microsoft Update
#     Catalog 16 drivert telepített (chipset, hang, LAN, Wi-Fi, videó, ME, I2C) - célzottan,
#     HWID alapján, verzió-ellenőrzéssel és kötés-vizsgálattal. A gépgyártói pack ezeket
#     egy régebbi, egybegyúrt kiadásban tartalmazza.
#
# Asztali/összerakott gépekre amúgy sincs ilyen pack, tehát ez a bolt bevételének nagy
# részét eleve nem érintette.
#
# HA VALAHA VISSZA KELL: ezt az egy sort kell True-ra állítani - a providerek, az
# illesztés és a kicsomagolás kódja érintetlenül megmaradt. Ilyenkor viszont a 3. pont
# CAB-hibáját is javítani kell, különben Dell gépen ismét 11 perc menne a semmibe.
INSTALL_WHOLE_MACHINE_PACKS = False

# A gyártói önkicsomagoló exe-k kapcsolói. A Lenovo a leírójában meg is adja; a többinél
# ez a lánc a próbálkozási sorrend. MINDEGYIK csak KICSOMAGOL, nem telepít - ez a modul
# soha nem futtat gyártói telepítőt (lásd a fenti indoklást).
EXTRACT_SWITCH_SETS = [
    ['/VERYSILENT', '/DIR={dest}', '/EXTRACT=YES'],   # Lenovo (a leíróból, mérve)
    ['/s', '/e={dest}'],                              # Dell DUP
    ['/s', '/f', '{dest}'],                           # HP SoftPaq
    ['-s', '-e', '-f{dest}'],                         # egyéb InstallShield-szerű
]
EXTRACT_TIMEOUT = 900


def _cache_dir():
    return os.path.join(_app_data_dir(), 'oemcatalog_cache')


# ---------------------------------------------------------------------------
# Letöltés / kódolás
# ---------------------------------------------------------------------------
def http_get(url, timeout=HTTP_TIMEOUT):
    """Bináris letöltés. Kivételt dob - a hívó dönt, hogy az mennyire végzetes."""
    req = urllib.request.Request(url, headers=HTTP_UA)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return r.read()


def decode_catalog_bytes(raw):
    """Katalógus-XML dekódolása a kódolás KITALÁLÁSÁVAL.

    MIÉRT: a Dell katalógusai UTF-16-osak (mérve, 2026-08-25), és utf-8-ként beolvasva
    nem hibát adnak, hanem néma szemetet - a `< ? x m l` alakot, amiben egyetlen minta sem
    illeszkedik, tehát a katalógus "üresnek" látszik. Ugyanaz a hibaosztály, amit a
    wu_core._read_text_best_effort kezel az INF-eknél, és pontosan ugyanúgy néma."""
    if not raw:
        return ''
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        try:
            return raw.decode('utf-16')
        except Exception:
            pass
    # BOM nélküli UTF-16: az XML ASCII-tartalmú, tehát minden második bájt 0x00.
    probe = raw[:4096]
    if len(probe) >= 16:
        even_nul, odd_nul = probe[0::2].count(0), probe[1::2].count(0)
        half = len(probe) // 2
        for enc, nul in (('utf-16-le', odd_nul), ('utf-16-be', even_nul)):
            if half and nul >= half * 0.8:
                try:
                    return raw.decode(enc, errors='replace')
                except Exception:
                    break
    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode('latin-1', errors='replace')


def fetch_catalog_text(url, cache_key=None, timeout=HTTP_TIMEOUT):
    """Katalógus letöltése szöveggé dekódolva, opcionális lemezes gyorsítótárral.

    A gyorsítótár azért kell, mert a lánc 3-4 külön processzben futó lábból áll, és
    mindegyik ugyanazt a katalógust kérné le újra."""
    cache_path = None
    if cache_key:
        try:
            os.makedirs(_cache_dir(), exist_ok=True)
            cache_path = os.path.join(_cache_dir(), cache_key)
            if os.path.isfile(cache_path):
                age_days = (time.time() - os.path.getmtime(cache_path)) / 86400.0
                if age_days < CATALOG_CACHE_DAYS:
                    logging.debug(f"[OEM] Katalógus a gyorsítótárból ({age_days:.1f} napos): {cache_key}")
                    return io.open(cache_path, encoding='utf-8', errors='replace').read()
        except Exception as e:
            logging.debug(f"[OEM] Gyorsítótár olvasása sikertelen ({cache_key}): {e}")
    text = decode_catalog_bytes(http_get(url, timeout=timeout))
    if cache_path:
        try:
            io.open(cache_path, 'w', encoding='utf-8').write(text)
        except Exception as e:
            logging.debug(f"[OEM] Gyorsítótár írása sikertelen ({cache_key}): {e}")
    return text


def expand_cab(run_fn, cab_path, dest_dir):
    """CAB kibontása a Windows saját `expand` eszközével. Visszatérés: sikerült-e.

    A visszatérési kód itt NEM ítélet (a projektben visszatérő tanulság): a lemezen lévő
    eredmény az. Ezért a fájllistát nézzük."""
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except Exception as e:
        logging.warning(f"[OEM] A kibontási mappa nem hozható létre: {e}")
        return False
    run_fn(['expand', cab_path, '-F:*', dest_dir], timeout=300)
    try:
        return bool(os.listdir(dest_dir))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# GÉPAZONOSÍTÁS - gyártófüggetlen
# ---------------------------------------------------------------------------
MACHINE_QUERY_PS = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$o = [ordered]@{}; "
    "try { $cs = Get-CimInstance Win32_ComputerSystem; "
    "$o.Manufacturer = $cs.Manufacturer; $o.Model = $cs.Model; $o.SKU = $cs.SystemSKUNumber } catch {}; "
    "try { $p = Get-CimInstance Win32_ComputerSystemProduct; "
    "$o.ProductName = $p.Name; $o.Serial = $p.IdentifyingNumber } catch {}; "
    "try { $b = Get-CimInstance Win32_BaseBoard; "
    "$o.BoardVendor = $b.Manufacturer; $o.BoardProduct = $b.Product } catch {}; "
    "try { $os = Get-CimInstance Win32_OperatingSystem; $o.Build = $os.BuildNumber } catch {}; "
    "$o | ConvertTo-Json -Compress"
)

# A gyártónév sokféle alakban jön ("LENOVO", "Dell Inc.", "HP", "Hewlett-Packard").
VENDOR_PATTERNS = (
    ('lenovo', ('lenovo',)),
    ('dell', ('dell',)),
    ('hp', ('hp', 'hewlett')),
)

# Placeholder gyártónevek (összerakott gépek) - ezekre nincs OEM katalógus, és ez rendben van.
PLACEHOLDER_VALUES = (
    'to be filled by o.e.m.', 'default string', 'system manufacturer',
    'system product name', 'o.e.m.', 'not specified', 'none', '',
)


def _is_placeholder(v):
    return str(v or '').strip().lower() in PLACEHOLDER_VALUES


def detect_machine(run_fn):
    """A gép gyártófüggetlen azonosítása. MINDIG ad vissza dictet (üres vendorral is).

    Visszatérés: {'vendor','manufacturer','model','sku','serial','board_vendor',
                  'board_product','build','lenovo_mtm','os_tag'}"""
    info = {}
    try:
        res = run_fn(["powershell", "-NoProfile", "-Command", MACHINE_QUERY_PS],
                     encoding='utf-8', timeout=120)
        raw = (getattr(res, 'stdout', '') or '').strip()
        if raw:
            info = json.loads(raw) or {}
    except Exception as e:
        logging.warning(f"[OEM] A gépazonosítás lekérdezése sikertelen: {e}")

    manufacturer = str(info.get('Manufacturer') or '').strip()
    model = str(info.get('Model') or '').strip()
    low = manufacturer.lower()
    vendor = ''
    for name, keys in VENDOR_PATTERNS:
        if any(k in low for k in keys):
            vendor = name
            break

    build = 0
    try:
        build = int(str(info.get('Build') or '0').strip() or 0)
    except Exception:
        build = 0

    machine = {
        'vendor': vendor,
        'manufacturer': manufacturer,
        'model': model,
        'sku': str(info.get('SKU') or '').strip(),
        'product_name': str(info.get('ProductName') or '').strip(),
        'serial': str(info.get('Serial') or '').strip(),
        'board_vendor': str(info.get('BoardVendor') or '').strip(),
        'board_product': str(info.get('BoardProduct') or '').strip(),
        'build': build,
        # Windows 11 = 22000-es buildtől. A gyártói katalógusok külön OS-tagot használnak.
        'os_tag': 'Win11' if build >= 22000 else 'Win10',
        # Lenovónál a gépazonosító a Model első 4 karaktere ("20L9S0KM00" -> "20L9").
        'lenovo_mtm': (model[:4].upper() if vendor == 'lenovo' and len(model) >= 4 else ''),
    }
    if _is_placeholder(manufacturer) or _is_placeholder(model):
        # Összerakott gép: ez NEM hiba, csak nincs hozzá gyártói katalógus.
        logging.info(f"[OEM] A gépazonosító mezők általánosak (összerakott gép?): "
                     f"gyártó='{manufacturer}', modell='{model}', alaplap="
                     f"'{machine['board_vendor']} {machine['board_product']}'.")
    logging.info(f"[OEM] Gép: gyártó='{manufacturer}' modell='{model}' SKU='{machine['sku']}' "
                 f"-> szolgáltató={vendor or 'nincs'} (OS: {machine['os_tag']}, build {build})")
    return machine


# ---------------------------------------------------------------------------
# SZOLGÁLTATÓK. Mindegyik ugyanolyan alakú csomag-dicteket ad vissza:
#   {'vendor','title','version','category','pnpids':[...],'url','descriptor','id'}
# Aki nem tud a géppel mit kezdeni, ÜRES listát ad - az nem hiba.
# ---------------------------------------------------------------------------
def lenovo_packages(machine, log=None):
    """Lenovo: gépmodell (MTM) -> csomag-leírók, hardver-azonosítókkal.

    Ez a legjobb minőségű forrás a háromból: a leíró megnevezi a támogatott
    hardver-azonosítókat, így pontosan az a csomag tölthető le, amire szükség van."""
    say = log or (lambda _m: None)
    mtm = machine.get('lenovo_mtm')
    if not mtm:
        return []
    pkgs = []
    for os_tag in (machine.get('os_tag') or 'Win10', 'Win10'):
        url = LENOVO_CATALOG_URL.format(mtm=mtm, os=os_tag)
        try:
            cat = fetch_catalog_text(url, cache_key=f"lenovo_{mtm}_{os_tag}.xml")
        except Exception as e:
            logging.info(f"[OEM] Lenovo katalógus nem érhető el ({url}): {e}")
            continue
        pairs = re.findall(r'<location>([^<]+)</location>\s*<category>([^<]*)</category>', cat)
        if not pairs:
            pairs = [(u, '') for u in re.findall(r'<location>([^<]+)</location>', cat)]
        logging.info(f"[OEM] Lenovo katalógus {mtm}/{os_tag}: {len(pairs)} csomag-leíró.")
        if not pairs:
            continue
        say(f'🏭 Lenovo gyári katalógus: {len(pairs)} csomag a(z) {mtm} modellhez.')
        for desc_url, category in pairs:
            try:
                x = fetch_catalog_text(desc_url, cache_key='lenovo_d_' + re.sub(r'\W+', '_', desc_url)[-80:])
            except Exception as e:
                logging.debug(f"[OEM] Lenovo leíró nem érhető el ({desc_url}): {e}")
                continue
            pkgs.append(_parse_lenovo_descriptor(x, desc_url, category))
        break   # az első működő OS-tag elég
    return [p for p in pkgs if p]


def _parse_lenovo_descriptor(xml, desc_url, category):
    """Egy Lenovo csomag-leíró értelmezése. Visszatérés: csomag-dict vagy None."""
    title = re.search(r'<Desc id="EN">([^<]+)</Desc>', xml) or re.search(r'<Desc[^>]*>([^<]+)</Desc>', xml)
    ver = re.search(r'<Package[^>]*version="([^"]+)"', xml)
    pkg_id = re.search(r'<Package[^>]*id="([^"]+)"', xml)
    pnpids = re.findall(r'<_PnPID><!\[CDATA\[([^\]]+)\]\]></_PnPID>', xml)
    if not pnpids:
        pnpids = re.findall(r'<_PnPID>([^<]+)</_PnPID>', xml)
    # A letöltendő exe a leíró mappájában van.
    files = re.findall(r'<Name>([^<]+\.exe)</Name>', xml, re.I)
    extract = re.search(r'<ExtractCommand>([^<]*)</ExtractCommand>', xml)
    base = desc_url.rsplit('/', 1)[0]
    exe = None
    for f in files:
        # A verzió-lekérdező segédprogramokat (getw10ver, *_version.exe) nem töltjük le.
        lowf = f.lower()
        if 'version' in lowf or lowf.startswith('getw'):
            continue
        exe = f
        break
    if not exe:
        return None
    return {
        'vendor': 'lenovo',
        'id': (pkg_id.group(1) if pkg_id else exe),
        'title': (title.group(1).strip() if title else exe),
        'version': (ver.group(1) if ver else ''),
        'category': category or '',
        'pnpids': sorted({p.strip().upper() for p in pnpids if p.strip()}),
        'url': f"{base}/{exe}",
        'descriptor': desc_url,
        'extract_cmd': (extract.group(1) if extract else ''),
    }


def _softpaq_number(sp_id):
    """'sp145052' -> 145052 (a nagyobb a frissebb). Nem értelmezhetőre 0."""
    m = re.search(r'(\d+)', str(sp_id or ''))
    return int(m.group(1)) if m else 0


def _keep_newest_pack(packs, key):
    """Több teljes-gép driver packból CSAK a legfrissebb marad.

    MIÉRT: a gyártói katalógusok modellenként minden Windows-kiadáshoz külön packet
    adnak, és egy pack több száz MB - mindet letölteni értelmetlen. A csomag-szintű
    (HWID-es) találatokat ez SOHA nem érinti, azokból mindegyik kell."""
    whole = [p for p in packs if p.get('whole_machine')]
    rest = [p for p in packs if not p.get('whole_machine')]
    if len(whole) <= 1:
        return packs
    best = max(whole, key=key)
    logging.info(f"[OEM] {len(whole)} teljes-gép driver packből a legfrissebb marad: "
                 f"'{best.get('title')}' (a többi: "
                 f"{[p.get('id') for p in whole if p is not best][:6]})")
    return rest + [best]


def _dell_matches_machine(block, machine):
    """Illik-e a Dell driver-pack blokk erre a gépre? systemID VAGY modellnév alapján."""
    sku = (machine.get('sku') or '').strip().upper()
    model = (machine.get('model') or '').strip().lower()
    for sys_id, name in re.findall(r'<Model\s+systemID="([^"]+)"\s+name="([^"]*)"', block):
        if sku and sys_id.strip().upper() == sku:
            return True
        n = name.strip().lower()
        if n and model and (n == model or n in model or model in n):
            return True
    return False


def dell_packages(machine, run_fn, log=None):
    """Dell: a modellhez tartozó TELJES driver pack (Dell Command Deploy).

    A Dell - a Lenovóval ellentétben - nem ad csomagonkénti hardver-azonosítót a
    letölthető katalógusban, ezért itt a gép modelljéhez tartozó teljes packet hozzuk le,
    és a benne lévő INF-eket a pnputil illeszti az eszközökre (ő ugyanazt a HWID-vizsgálatot
    végzi el, csak megbízhatóbban). A pack nagy (több száz MB), de pontosan ez a
    "gyári driver pack", amit a szerviz kézzel is használna."""
    say = log or (lambda _m: None)
    if machine.get('vendor') != 'dell':
        return []
    tmp = os.path.join(_cache_dir(), 'dell')
    try:
        os.makedirs(tmp, exist_ok=True)
        cab = os.path.join(tmp, 'DriverPackCatalog.cab')
        if not os.path.isfile(cab) or (time.time() - os.path.getmtime(cab)) / 86400.0 > CATALOG_CACHE_DAYS:
            open(cab, 'wb').write(http_get(DELL_DRIVERPACK_CATALOG, timeout=300))
        xdir = os.path.join(tmp, 'x')
        shutil.rmtree(xdir, ignore_errors=True)
        if not expand_cab(run_fn, cab, xdir):
            logging.warning("[OEM] A Dell katalógus kibontása nem sikerült.")
            return []
        xmls = [os.path.join(xdir, f) for f in os.listdir(xdir)]
        raw = open(xmls[0], 'rb').read()
        cat = decode_catalog_bytes(raw)      # FIGYELEM: UTF-16 (mérve)
    except Exception as e:
        logging.warning(f"[OEM] A Dell katalógus feldolgozása sikertelen: {e}")
        return []

    os_code = 'Windows11' if (machine.get('os_tag') == 'Win11') else 'Windows10'
    out = []
    for block in re.findall(r'<DriverPackage\b.*?</DriverPackage>', cat, re.S):
        if not _dell_matches_machine(block, machine):
            continue
        head = re.match(r'<DriverPackage\b[^>]*>', block)
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', head.group(0) if head else ''))
        path = attrs.get('path') or ''
        if not path:
            continue
        # Csak a gép Windows-verziójához illő packet kérjük.
        oses = re.findall(r'osCode="([^"]*)"', block)
        if oses and not any(os_code.lower() in o.lower().replace(' ', '') for o in oses):
            continue
        out.append({
            'vendor': 'dell',
            'id': attrs.get('releaseID') or path,
            'title': f"Dell driver pack {attrs.get('dellVersion') or ''} ({os_code})".strip(),
            'version': attrs.get('vendorVersion') or attrs.get('dellVersion') or '',
            'category': 'Driver pack',
            'pnpids': [],          # a Dell nem ad HWID-t: a pnputil illeszt
            # TELJES GÉPRE szóló pack: ez az EGYETLEN eset, amikor a hiányzó HWID nem
            # kizáró ok (lásd match_packages_to_devices).
            'whole_machine': True,
            'url': DELL_BASE + path.lstrip('/'),
            'descriptor': '',
            'extract_cmd': '',
            'size': int(attrs.get('size') or 0),
            'released': attrs.get('dateTime') or '',
        })
    # Dellnél is csak a legfrissebb pack kell (lásd _keep_newest_pack). A rendezés kulcsa
    # a kiadás dátuma, mert a dellVersion ('A01', 'A12') nem monoton összehasonlítható.
    out = _keep_newest_pack(out, key=lambda p: (p.get('released') or '', _softpaq_number(p.get('id'))))
    logging.info(f"[OEM] Dell: {len(out)} illeszkedő driver pack (modell='{machine.get('model')}', "
                 f"SKU='{machine.get('sku')}').")
    if out:
        say(f'🏭 Dell gyári driver pack találat: {len(out)} db a(z) "{machine.get("model")}" modellhez.')
    return out


def hp_packages(machine, run_fn, log=None):
    """HP: a modellhez tartozó driver pack (HP Client Driver Pack katalógus)."""
    say = log or (lambda _m: None)
    if machine.get('vendor') != 'hp':
        return []
    tmp = os.path.join(_cache_dir(), 'hp')
    try:
        os.makedirs(tmp, exist_ok=True)
        cab = os.path.join(tmp, 'HPClientDriverPackCatalog.cab')
        if not os.path.isfile(cab) or (time.time() - os.path.getmtime(cab)) / 86400.0 > CATALOG_CACHE_DAYS:
            open(cab, 'wb').write(http_get(HP_DRIVERPACK_CATALOG, timeout=300))
        xdir = os.path.join(tmp, 'x')
        shutil.rmtree(xdir, ignore_errors=True)
        if not expand_cab(run_fn, cab, xdir):
            logging.warning("[OEM] A HP katalógus kibontása nem sikerült.")
            return []
        xmls = [os.path.join(xdir, f) for f in os.listdir(xdir)]
        cat = decode_catalog_bytes(open(xmls[0], 'rb').read())
    except Exception as e:
        logging.warning(f"[OEM] A HP katalógus feldolgozása sikertelen: {e}")
        return []

    model = (machine.get('model') or '').strip().lower()
    # A HP gépazonosítója a BIOS/alaplap 4 jegyű hex kódja - a WMI-ban a
    # Win32_BaseBoard.Product adja (mérve ezen a gépen: HP EliteDesk 800 G2 SFF -> '8054').
    board_id = (machine.get('board_product') or '').strip().lower()
    want11 = (machine.get('os_tag') == 'Win11')

    # A letöltési URL-eket a KÜLÖN <SoftPaq> tábla adja - nem szabad kézzel összerakni
    # (mérve: a katalógus 779 SoftPaq-rekordot tartalmaz saját <Url> mezővel).
    softpaqs = {}
    for sp in re.findall(r'<SoftPaq>.*?</SoftPaq>', cat, re.S):
        sid = re.search(r'<Id>([^<]*)</Id>', sp)
        url = re.search(r'<Url>([^<]*)</Url>', sp)
        if not sid or not url:
            continue
        nm = re.search(r'<Name>([^<]*)</Name>', sp)
        vr = re.search(r'<Version>([^<]*)</Version>', sp)
        softpaqs[sid.group(1).strip().lower()] = {
            'url': url.group(1).strip(),
            'name': nm.group(1).strip() if nm else '',
            'version': vr.group(1).strip() if vr else '',
        }

    out, seen = [], set()
    for block in re.findall(r'<ProductOSDriverPack>.*?</ProductOSDriverPack>', cat, re.S):
        def g(tag):
            m = re.search(r'<%s>([^<]*)</%s>' % (tag, tag), block)
            return m.group(1).strip() if m else ''
        # A SystemId VESSZŐVEL ELVÁLASZTOTT lista lehet (mérve: "81c3,8396").
        sysids = {s.strip().lower() for s in g('SystemId').split(',') if s.strip()}
        name = g('SystemName')
        os_name = g('OSName').lower()
        arch = g('Architecture').lower()
        if '64' not in arch:
            continue
        if want11 and 'windows 11' not in os_name:
            continue
        if not want11 and 'windows 10' not in os_name:
            continue
        n = name.strip().lower()
        hit = (board_id and board_id in sysids) or (n and model and (n == model or n in model or model in n))
        if not hit:
            continue
        spid = g('SoftPaqId').strip().lower()
        info = softpaqs.get(spid)
        if not info or not info.get('url'):
            logging.debug(f"[OEM] HP: a(z) {spid} SoftPaq-hoz nincs URL a katalógusban.")
            continue
        if spid in seen:
            continue
        seen.add(spid)
        out.append({
            'vendor': 'hp',
            'id': spid,
            'title': f"HP driver pack {spid} - {name} ({g('OSName')})".strip(),
            'version': info.get('version') or '',
            'category': 'Driver pack',
            'pnpids': [],
            'whole_machine': True,
            'url': info['url'],
            'descriptor': '',
            'extract_cmd': '',
        })
    # CSAK A LEGFRISSEBB PACK KELL. A katalógus modellenként MINDEN Windows-build-hez ad
    # egy külön packet (mérve: ProBook 440 G5 -> 6 db), és mindegyik több száz MB. Hatot
    # letölteni értelmetlen és a felhasználó sávszélességét égetné el; a legmagasabb
    # SoftPaq-szám a legújabb kiadás.
    out = _keep_newest_pack(out, key=lambda p: _softpaq_number(p.get('id')))
    logging.info(f"[OEM] HP: {len(out)} illeszkedő driver pack "
                 f"(modell='{machine.get('model')}', alaplap-ID='{board_id}').")
    if out:
        say(f'🏭 HP gyári driver pack találat: {len(out)} db.')
    return out


def find_oem_packages(machine, run_fn, log=None):
    """A gép gyártójához tartozó összes elérhető csomag. Üres lista = nincs szolgáltató.

    ÜRES LISTA NEM HIBA: a gépek nagy részéhez (Acer, összerakott PC) nincs gépi olvasásra
    alkalmas gyártói katalógus, és ilyenkor a WU + Microsoft-katalógus + GPU-gyártói ág
    változatlanul elvégzi a munkát."""
    vendor = machine.get('vendor')
    if not vendor:
        logging.info("[OEM] Ehhez a géphez nincs gyártói katalógus-szolgáltató "
                     "(a WU és a Microsoft-katalógus természetesen fut rá).")
        return []
    # A Dell/HP szolgáltató KIZÁRÓLAG teljes gépre szóló packet ad (mindkettőnél
    # `pnpids: []` + `whole_machine: True`), tehát kikapcsolt állapotban már a
    # katalógus LETÖLTÉSÉT is megspóroljuk - nem csak a telepítést. A Lenovo nem
    # érintett: ő per-eszköz, hardver-azonosítós csomagokat ad.
    if vendor in ('dell', 'hp') and not INSTALL_WHOLE_MACHINE_PACKS:
        logging.info(f"[OEM] A(z) {vendor} csak TELJES GÉPRE szóló driver packet kínál, "
                     f"az pedig ki van kapcsolva (INSTALL_WHOLE_MACHINE_PACKS=False) - "
                     f"a katalógust le sem kérdezzük. A WU, a Microsoft-katalógus és a "
                     f"GPU-gyártói ág változatlanul fut erre a gépre.")
        return []
    try:
        if vendor == 'lenovo':
            return lenovo_packages(machine, log)
        if vendor == 'dell':
            return dell_packages(machine, run_fn, log)
        if vendor == 'hp':
            return hp_packages(machine, run_fn, log)
    except Exception as e:
        logging.warning(f"[OEM] A(z) {vendor} katalógus lekérdezése hibára futott "
                        f"(nem kritikus, a többi forrás fut tovább): {e}", exc_info=True)
    return []


# ---------------------------------------------------------------------------
# ILLESZTÉS az eszközökhöz
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# MI NEM DRIVER? - a gyártói katalógus nem csak drivereket tartalmaz
#
# ÉLES MÉRÉS KAPTA EL (2026-08-25, T580 katalógusa): az első változat "nincs
# hardver-azonosító -> mindenre illik" szabálya a következőket sorolta telepítendőnek:
#   "Fibocom Wireless WAN FIRMWARE Update Tool", "Thunderbolt FIRMWARE Update Tool",
#   "Intel Management Engine FIRMWARE", "Lenovo NVMe SSD FIRMWARE Update Utility",
#   "NVIDIA GeForce Experience SOFTWARE", dokkoló-FW segédprogramok.
# Vagyis egy felügyelet nélküli lánc BIOS-t, Thunderboltot, SSD-t és TPM-et FLASHELT
# volna - pontosan az, amit a firmware-jelölőnégyzet tilt, és amit a CLAUDE.md
# visszafordíthatatlanként ír le (megszakadt flash = hardveresen halott eszköz).
# Ez a lista + a HWID-követelmény együtt zárja ki ezt.
# ---------------------------------------------------------------------------
FIRMWARE_CATEGORY_MARKERS = (
    'bios', 'firmware', 'uefi', 'embedded controller',
)
FIRMWARE_TITLE_MARKERS = (
    'firmware', 'bios', 'uefi', ' fw ', 'fw utility', 'fw update',
)
# Nem-driver szoftverek: a gyártói katalógus tele van segédprogramokkal, amiknek semmi
# keresnivalójuk egy driver-javításban (és a felhasználó szerviz-gépre nem kér bloatware-t).
SOFTWARE_CATEGORY_MARKERS = (
    'software and utilities', 'application', 'utility',
)


def is_firmware_package(pkg):
    """Firmware-t ír-e a csomag? Szándékosan BŐKEZŰEN igent mond.

    Egy tévesen firmware-nek jelölt driver legrosszabb esetben kimarad (a WU és a
    Microsoft-katalógus úgyis lefutott rá); egy tévesen drivernek nézett firmware viszont
    visszafordíthatatlanul újraírja egy ügyfélgép nem felejtő memóriáját."""
    cat = (pkg.get('category') or '').lower()
    title = ' ' + (pkg.get('title') or '').lower() + ' '
    return (any(m in cat for m in FIRMWARE_CATEGORY_MARKERS)
            or any(m in title for m in FIRMWARE_TITLE_MARKERS))


def is_software_package(pkg):
    """Segédprogram/alkalmazás-e (nem driver)?"""
    cat = (pkg.get('category') or '').lower()
    return any(m in cat for m in SOFTWARE_CATEGORY_MARKERS)


def match_packages_to_devices(packages, devices, allow_firmware=False):
    """Csomag -> jelen lévő eszköz párosítás a gyártó által DEKLARÁLT azonosítók alapján.

    FONTOS (mérve, 2026-08-25): a párosítás kulcsa a katalógus `<_PnPID>` listája, NEM a
    kicsomagolt INF. A T580 UltraNav-csomagjának INF-je (`SynPD.inf`) csak `HID\\...`
    azonosítókat sorol fel, miközben az eszköz `ACPI\\VEN_LEN&DEV_009B`-ként jelenik meg -
    az INF alapján tehát sosem találnánk meg, a katalógus-metaadat alapján viszont pontosan.

    A HWID-nélküli csomagok (Dell/HP driver pack) MINDIG illeszkedőnek számítanak: azok a
    gép egészére szólnak, és a bennük lévő INF-eket a pnputil illeszti az eszközökre."""
    from app.wu_core import _hwid_matches      # helyben, hogy ne legyen körkörös import

    dev_hwids = []
    for d in devices or []:
        for h in (d.get('all_hwids') or []):
            if h:
                dev_hwids.append((str(h).strip(), d))
    out = []
    dropped = {'firmware': 0, 'szoftver': 0, 'nincs-hwid': 0, 'nincs-eszköz': 0}
    for pkg in packages or []:
        if is_firmware_package(pkg) and not allow_firmware:
            dropped['firmware'] += 1
            logging.info(f"[OEM] KIHAGYVA (firmware, a jelölőnégyzet nem engedte): "
                         f"{pkg.get('title')} [{pkg.get('category')}]")
            continue
        if is_software_package(pkg):
            dropped['szoftver'] += 1
            logging.debug(f"[OEM] Kihagyva (segédprogram, nem driver): {pkg.get('title')}")
            continue
        pnpids = pkg.get('pnpids') or []
        if not pnpids:
            # HWID NÉLKÜLI CSOMAG. Csak akkor telepítjük, ha a szolgáltató kifejezetten
            # TELJES GÉPRE szóló driver packnek jelölte (Dell/HP). A Lenovónál a valódi
            # driverek MIND megadják a hardver-azonosítóikat (mérve: 56-ból 45), tehát ott
            # a hiányuk azt jelenti, hogy ez nem driver - segédprogram vagy firmware-eszköz.
            if pkg.get('whole_machine'):
                # VÉDŐHÁLÓ. A providerek szintjén már nem is jönnek létre ilyen csomagok
                # (lásd find_oem_packages), de ha valaha új szolgáltató kerül be, az itt
                # akad fenn - nem a telepítőnél, több száz MB letöltése UTÁN.
                if not INSTALL_WHOLE_MACHINE_PACKS:
                    dropped['teljes-gép-pack'] = dropped.get('teljes-gép-pack', 0) + 1
                    logging.info(f"[OEM] KIHAGYVA (teljes gépre szóló driver pack, ki van "
                                 f"kapcsolva): {pkg.get('title')} [{pkg.get('category')}]")
                    continue
                out.append((pkg, None))
            else:
                dropped['nincs-hwid'] += 1
                logging.info(f"[OEM] KIHAGYVA (nincs hardver-azonosítója, tehát nem eszköz-driver): "
                             f"{pkg.get('title')} [{pkg.get('category')}]")
            continue
        hit = None
        for pid in pnpids:
            for hw, dev in dev_hwids:
                if _hwid_matches(pid, hw):
                    hit = dev
                    break
            if hit:
                break
        if hit:
            out.append((pkg, hit))
        else:
            dropped['nincs-eszköz'] += 1
            logging.debug(f"[OEM] Kihagyva (nincs illeszkedő eszköz): {pkg.get('title')} "
                          f"[{pkg.get('category')}] ids={pnpids[:4]}")
    # EGY összegző sor a döntésről (a Rule 0 "minden szűrő nevezze meg, mit dobott el"
    # szabálya, a forró ciklus elárasztása nélkül).
    logging.info(f"[OEM] Illesztés: {len(out)}/{len(packages or [])} csomag telepítendő "
                 f"(kizárva: " + ', '.join(f"{k}={v}" for k, v in dropped.items() if v) + ")")
    return out


# ---------------------------------------------------------------------------
# KICSOMAGOLÁS (telepítés nélkül)
# ---------------------------------------------------------------------------
def extract_vendor_package(run_fn, exe_path, dest_dir, extract_cmd='', log=None):
    """Gyártói önkicsomagoló exe KICSOMAGOLÁSA - telepítés NÉLKÜL.

    Miért így: a telepítést a `pnputil /add-driver /install` végzi, ugyanazon a jól ismert
    úton, mint minden más forrásnál (ugyanazokkal a védelmekkel: kötés-ellenőrzés, a nem
    használt INF-ek kivezetése). Így SOHA nem futtatunk ismeretlen gyártói telepítőt egy
    ügyfél gépén - ez oldja fel a CLAUDE.md korábbi, jogos aggályát.

    Visszatérés: az INF-eket tartalmazó mappa útvonala, vagy None."""
    say = log or (lambda _m: None)
    try:
        shutil.rmtree(dest_dir, ignore_errors=True)
        os.makedirs(dest_dir, exist_ok=True)
    except Exception as e:
        logging.warning(f"[OEM] A kicsomagolási mappa nem hozható létre: {e}")
        return None

    # A leíróban megadott parancs élvez elsőbbséget (a Lenovo megadja).
    switch_sets = list(EXTRACT_SWITCH_SETS)
    if extract_cmd:
        m = re.findall(r'(/\S+|-\S+)', extract_cmd)
        if m:
            switch_sets.insert(0, [s.replace('%PACKAGEPATH%', '{dest}') for s in m])

    for i, switches in enumerate(switch_sets):
        args = [exe_path] + [s.format(dest=dest_dir) for s in switches]
        logging.info(f"[OEM] Kicsomagolási kísérlet {i + 1}/{len(switch_sets)}: {args[1:]}")
        try:
            subprocess.run(args, capture_output=True, timeout=EXTRACT_TIMEOUT,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception as e:
            logging.info(f"[OEM] A kicsomagoló futtatása sikertelen ({i + 1}. kísérlet): {e}")
            continue
        infs = find_infs(dest_dir)
        if infs:
            logging.info(f"[OEM] Kicsomagolva: {len(infs)} INF a(z) {i + 1}. kapcsolókészlettel.")
            return dest_dir
        logging.info(f"[OEM] A(z) {i + 1}. kapcsolókészlet nem adott INF-et - próbáljuk a következőt.")
    say('⚠️ A gyártói csomagot nem sikerült kicsomagolni - kihagyjuk.')
    logging.warning(f"[OEM] Egyik kicsomagolási mód sem adott INF-et: {exe_path}")
    return None


def find_infs(root):
    """A kicsomagolt fában található INF-fájlok."""
    out = []
    for base, _dirs, files in os.walk(root or ''):
        for fn in files:
            if fn.lower().endswith('.inf'):
                out.append(os.path.join(base, fn))
    return out


def clear_catalog_cache():
    """A katalógus-gyorsítótár törlése (a lánc végén, hogy ügyfélgépen ne maradjon szemét)."""
    try:
        shutil.rmtree(_cache_dir(), ignore_errors=True)
    except Exception as e:
        logging.debug(f"[OEM] A gyorsítótár törlése nem sikerült: {e}")
