"""Debug-log feltöltése a bolt saját Google Drive-jára - és VISSZATÖLTÉSE onnan.

MINDKÉT IRÁNY ITT VAN, szándékosan: a modul neve a feltöltésről szól, de a letöltés
ugyanarra a végpontra, ugyanazzal a csomagolással és ugyanazzal a HTTP-réteggel megy -
két fájlba szétvágva a végpont-tudás duplikálódna, ami ennek a projektnek a legrégebbi
visszatérő hibája (lásd CLAUDE.md, Build 192).

MIÉRT KELL (explicit user decision, 2026-08-26): ennek a projektnek a hibajelentése MAGA A
NAPLÓ - a CLAUDE.md is ezzel kezdődik ("a debug log az elsődleges terepi diagnózis-eszköz").
A gyakorlatban viszont a naplót kézzel kell összeszedni a szervizelt gépről, és pont akkor
marad el, amikor a legfontosabb lenne: a technikus otthon/ügyfélnél futtat egy fixet, lát
valami furcsát, aztán a gép már az ügyfélnél van, a napló elérhetetlen. Ez a modul ezt
oldja meg: a lánc végén a napló magától felmegy a bolt Drive-jára.

MIT KÜLD ÉS HOVA: a `DriverVarázsló_debug.log` (+ a rotált `.log.1`) tömörítve, a
Benchmark-ranglista MÁR MEGLÉVŐ Google Apps Script végpontjára (benchmark_defs.py:
BENCHMARK_API_URL_DEFAULT), `action="log"` megkülönböztetéssel. Nincs új szolgáltatás, új
fiók vagy új titok - ugyanaz a végpont, amit a bolt már használ.

ADATVÉDELEM - ezt tudni kell: a napló a szervizelt gép adatait tartalmazza (gépnév,
hardver-azonosítók, sorozatszámok, telepített driverek és programok nevei). A bolt SAJÁT
Drive-jára megy, de attól még ügyféladat. Ezért: a feltöltés a felhasználó kifejezett
kérésére került be, a lánc végén FUT, de HIBÁJA SOSEM akasztja meg a fixet, és a napló
minden esetben ott marad a gépen is (`_app_data_dir()`), tehát a feltöltés nem "elviszi",
csak másolatot küld.

MIÉRT TÖMÖRÍTVE: a napló szöveges, tehát nagyon jól tömörödik (mérve ~10:1), és a Drive-ra
egy ~800 KB-os csomag megy 8 MB helyett. A base64 a JSON-ba ágyazás miatt kell.
"""
import io
import os
import gzip
import json
import base64
import logging
import platform

from app.common import _app_data_dir

# A napló fájlnevei (a rotáló handler a `.1` végűt hagyja hátra) - lásd driver_tool.py.
LOG_BASENAME = 'DriverVarázsló_debug.log'

# A becsomagolt (gzip+base64) küldemény felső korlátja. Az Apps Script Web App bőven
# elbírna többet is, de egy elszabadult napló nem tarthatja fel a lánc lezárását.
# Túllépésnél a RÉGEBBI naplót hagyjuk el, az AKTUÁLISAT sosem - abban van a most futott
# lánc, az érdekes.
UPLOAD_MAX_BYTES = 12 * 1024 * 1024

# Ha maga az aktuális napló is nagyobb ennél, csak a VÉGÉT küldjük: a lánc utolsó szakasza
# (a záró kör, a jelentés, a hibák) mindig a fájl végén van.
SINGLE_LOG_TAIL_BYTES = 20 * 1024 * 1024


def log_paths():
    """A feltöltendő naplófájlok, LEGFRISSEBB ELŐSZÖR. Csak a létezők."""
    base = os.path.join(_app_data_dir(), LOG_BASENAME)
    return [p for p in (base, base + '.1') if os.path.isfile(p)]


def _read_tail(path, max_bytes):
    """A fájl utolsó max_bytes bájtja (a lánc vége mindig a fájl végén van)."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            # Az első (fél)sort eldobjuk, hogy ne csonka sorral kezdődjön.
            f.readline()
        return f.read()


def pack_logs(paths, max_bytes=UPLOAD_MAX_BYTES):
    """A naplók egyetlen gzip+base64 csomaggá fűzése.

    Visszatérés: (base64_szöveg, {'files': [...], 'raw': bájt, 'packed': bájt}) vagy
    (None, info) ha nincs mit küldeni."""
    if not paths:
        return None, {'files': [], 'raw': 0, 'packed': 0}
    chunks, used, raw_total = [], [], 0
    for p in paths:
        try:
            data = _read_tail(p, SINGLE_LOG_TAIL_BYTES)
        except Exception as e:
            logging.warning(f"[LOGUP] A napló nem olvasható ({p}): {e}")
            continue
        header = f"\n===== {os.path.basename(p)} ({len(data)} bájt) =====\n".encode('utf-8')
        chunks.append(header + data)
        used.append(os.path.basename(p))
        raw_total += len(data)
        # Minden hozzáadás után ellenőrizzük a TÖMÖRÍTETT méretet: a régebbi naplót csak
        # akkor visszük, ha belefér. Az aktuális (első) mindig megy.
        blob = _gzip_b64(b''.join(chunks))
        if len(blob) > max_bytes and len(chunks) > 1:
            chunks.pop()
            used.pop()
            logging.info(f"[LOGUP] A régebbi napló ({p}) kimarad - a csomag túllépné a "
                         f"{max_bytes / 1048576:.0f} MB korlátot.")
            break
    if not chunks:
        return None, {'files': [], 'raw': 0, 'packed': 0}
    blob = _gzip_b64(b''.join(chunks))
    return blob, {'files': used, 'raw': raw_total, 'packed': len(blob)}


def _gzip_b64(data):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=9, mtime=0) as gz:
        gz.write(data)
    return base64.b64encode(buf.getvalue()).decode('ascii')


# A WMI gyártónév cégjogi farka ('Dell Inc.', 'ASUSTeK COMPUTER INC.') - a mappanévben
# csak zaj. Csak a VÉGÉRŐL vágjuk le, tehát egy 'Inc'-cel kezdődő gyártó sértetlen marad.
VENDOR_SUFFIXES = (
    'inc.', 'inc', 'corporation', 'corp.', 'corp', 'co., ltd.', 'co.,ltd.', 'co. ltd.',
    'co ltd', 'ltd.', 'ltd', 'gmbh', 'computer inc.', 'computer inc', 's.a.', 'llc',
)


def _name_covers_vendor(name, vendor):
    """Igaz, ha a típusnév már magában hordozza a gyártót, tehát az külön kiírva ismétlés
    lenne. Nem elég a sima 'startswith': a WMI gyártóneve gyakran hosszabb alak, mint ami a
    típusnévben szerepel ('ASUSTeK' vs. 'ASUS Vivobook...'), ezért az első 4 karaktert is
    összevetjük - az 'HP'/'Dell'/'LENOVO' eseteket a startswith úgyis lefedi."""
    n, v = (name or '').strip().lower(), (vendor or '').strip().lower()
    if not n or not v:
        return False
    return n.startswith(v) or (len(v) >= 4 and n[:4] == v[:4])


def _trim_vendor_suffix(vendor):
    v = (vendor or '').strip().rstrip(',')
    for suf in sorted(VENDOR_SUFFIXES, key=len, reverse=True):
        if v.lower().endswith(' ' + suf):
            v = v[:-(len(suf) + 1)].strip().rstrip(',')
            break
    return v


def machine_label(run_fn):
    """A gép EMBERI azonosítója a Drive-mappa nevéhez (pl. 'ASRock B450M Pro4').

    MIÉRT NEM ELÉG A WINDOWS GÉPNÉV: a `DESKTOP-8H3K2` semmit nem mond arról, milyen gép
    volt - a szerviz viszont pont ezt keresi vissza ("melyik volt az a B450M-es?"). Két
    forrásból dolgozunk, ebben a sorrendben:
      1. `Win32_ComputerSystem`/`ComputerSystemProduct` - gyári gépeknél ez a jó (Lenovo,
         Dell, HP). Lenovónál a `Model` csak MTM kód ('20L9S0KM00'), a beszédes nevet a
         ProductName adja ('ThinkPad T580'), ezért abból indulunk.
      2. `Win32_BaseBoard` - ÖSSZERAKOTT gépnél az 1. csupa placeholder ('To Be Filled By
         O.E.M.'), és pont az alaplap típusa az, ami azonosít. Ez a bolti bevétel nagy része.
    Sosem dob kivételt: ha semmi nem jön össze, üres stringet ad, és a hívó a gépnevet
    használja."""
    try:
        from app import oemcatalog_core
        m = oemcatalog_core.detect_machine(run_fn) or {}
        ph = oemcatalog_core._is_placeholder
        parts = []
        vendor = (m.get('manufacturer') or '').strip()
        # A beszédes név elsőbbséget élvez a nyers Model kóddal szemben.
        name = (m.get('product_name') or '').strip()
        if ph(name):
            name = (m.get('model') or '').strip()
        vendor = _trim_vendor_suffix(vendor)
        # A gyártót CSAK akkor tesszük ki, ha a típusnév nem tartalmazza már ('HP' +
        # 'HP EliteDesk 800 G2 SFF' -> 'HP HP EliteDesk...' lett volna).
        if not ph(vendor) and not _name_covers_vendor(name, vendor):
            parts.append(vendor)
        if not ph(name) and name.lower() not in (p.lower() for p in parts):
            parts.append(name)
        if not parts:
            # Összerakott gép: az alaplap AZ azonosító.
            bv = _trim_vendor_suffix((m.get('board_vendor') or '').strip())
            bp = (m.get('board_product') or '').strip()
            if not ph(bv) and not _name_covers_vendor(bp, bv):
                parts.append(bv)
            if not ph(bp):
                parts.append(bp)
        label = ' '.join(parts).strip()
        logging.info(f"[LOGUP] Gép-azonosító a napló mappájához: '{label or '(nincs)'}'.")
        return label
    except Exception as e:
        logging.warning(f"[LOGUP] A gép típusát nem sikerült megállapítani (nem kritikus): {e}")
        return ''


def folder_base(machine_name='', label=''):
    """A Drive-mappa nevének GÉP-fele; a dátumot a szkript fűzi hozzá (egy óra, egy
    időzóna - lásd az appscript.txt magyarázatát). Gépnév ELÖL, hogy a Drive név szerinti
    rendezésében egy gép futásai egymás mellé kerüljenek."""
    name = (machine_name or platform.node() or 'ismeretlen').strip()
    label = (label or '').strip()
    return f"{name} - {label}" if label and label.lower() != name.lower() else name


def build_payload(blob, info, machine_name='', build='', outcome='', extra=None, folder=''):
    """A Drive-ra küldött JSON. `action="log"` - a benchmark-sorokat ugyanaz a végpont
    kezeli, a szkript ebből tudja megkülönböztetni a kettőt."""
    payload = {
        'action': 'log',
        'machine': machine_name or platform.node() or 'ismeretlen',
        'build': str(build or ''),
        'outcome': outcome or '',
        'files': info.get('files') or [],
        'raw_bytes': info.get('raw') or 0,
        # A gépenkénti almappa neve. Üresen hagyva a szkript a napló-gyökérbe teszi a
        # fájlt (így egy régebbi kliens sem törik el).
        'folder': folder or '',
        'gz': blob,
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def upload_logs(run, url, machine_name='', build='', outcome='', http=None):
    """A naplók feltöltése. Visszatérés: (siker, üzenet).

    SOSEM dob kivételt: ez a lánc legvégén fut, és egy feltöltési hiba nem ronthatja el
    egy egyébként sikeres fix lezárását."""
    try:
        if not url:
            return False, 'nincs beállítva feltöltési végpont'
        paths = log_paths()
        if not paths:
            return False, 'nincs naplófájl'
        blob, info = pack_logs(paths)
        if not blob:
            return False, 'a naplót nem sikerült becsomagolni'
        ratio = (info['raw'] / info['packed']) if info['packed'] else 0
        logging.info(f"[LOGUP] Feltöltés indul: {info['files']} - {info['raw'] / 1048576:.1f} MB "
                     f"-> {info['packed'] / 1024:.0f} KB ({ratio:.1f}:1 tömörítés)")
        folder = folder_base(machine_name, machine_label(run))
        body = build_payload(blob, info, machine_name, build, outcome, folder=folder)
        sender = http or _default_http
        txt = sender(run, url, 'POST', body)
        try:
            resp = json.loads(txt) if txt and txt.strip() else {}
        except Exception:
            resp = {}
        if isinstance(resp, dict) and resp.get('ok') is False:
            msg = resp.get('error') or 'a szerver hibát jelzett'
            logging.warning(f"[LOGUP] A szerver elutasította a feltöltést: {msg}")
            return False, msg
        where = (resp or {}).get('url') or (resp or {}).get('file') or ''
        logging.info(f"[LOGUP] Feltöltés kész{(' -> ' + where) if where else ''}.")
        return True, where
    except Exception as e:
        # Szándékosan elnyelt: hálózati hiba, lejárt szkript, bármi - a fix ettől még kész.
        logging.warning(f"[LOGUP] A napló feltöltése nem sikerült (nem kritikus): {e}")
        return False, str(e)


def _default_http(run, url, method, body):
    """A benchmark HTTP-rétege (friss-Windows tanúsítvány-fallbackkel). Helyben
    importálva, hogy ez a modul önmagában is tesztelhető maradjon."""
    from app.benchmark_core import _http_request
    return _http_request(run, url, method, body=body, timeout=120)


# ---------------------------------------------------------------------------
# LETÖLTÉS: a Drive-ra feltöltött naplók visszahozása erre a gépre.
#
# MIÉRT KELL JELSZÓ: a végpont címe MINDEN kiadott exe-ben benne van és kiolvasható
# belőle. Feltölteni jelszó nélkül lehet (a lánc ember nélkül fut, nincs ki begépelje),
# letölteni viszont csak jelszóval - a naplókban ügyfélgépek adatai vannak. A jelszót
# SOSEM ágyazzuk az exe-be: azt a technikus gépeli be, különben pont annyit érne, mint
# a jelszó nélküli végpont.
# ---------------------------------------------------------------------------

# A letöltött naplók helye. SZÁNDÉKOSAN NEM az `_app_data_dir()` gyökere: ott van az
# ÉLŐ napló, amit a feltöltő beolvas - idegen gépek naplói közé keveredve előbb-utóbb
# rossz gép naplója menne fel.
DOWNLOAD_SUBDIR = 'letoltott_naplok'


def download_dir():
    return os.path.join(_app_data_dir(), DOWNLOAD_SUBDIR)


def _post(run, url, payload, http=None):
    """Egy JSON-kérés a végpontra. Visszatérés: (dict, hibaszöveg-vagy-üres)."""
    sender = http or _default_http
    txt = sender(run, url, 'POST', json.dumps(payload, ensure_ascii=False))
    try:
        resp = json.loads(txt) if txt and txt.strip() else {}
    except Exception:
        # Az Apps Script hiba esetén HTML hibaoldalt ad vissza - az eleje a beszédes.
        snippet = (txt or '')[:200].replace('\n', ' ')
        return {}, f"a szerver válasza nem JSON ({snippet})"
    if not isinstance(resp, dict):
        return {}, 'váratlan szerver-válasz'
    if resp.get('ok') is False:
        return resp, (resp.get('error') or 'a szerver hibát jelzett')
    return resp, ''


def list_remote_logs(run, url, password, http=None):
    """A Drive-on lévő naplók listája. Visszatérés: (sorok, hibaszöveg).

    Egy sor: {'id','name','folder','size','date','desc'}."""
    if not url:
        return [], 'nincs beállítva végpont'
    if not password:
        return [], 'nincs megadva jelszó'
    resp, err = _post(run, url, {'action': 'loglist', 'pw': password}, http)
    if err:
        logging.warning(f"[LOGDL] A napló-lista lekérése nem sikerült: {err}")
        return [], err
    rows = resp.get('logs') or []
    logging.info(f"[LOGDL] A Drive-on {resp.get('total', len(rows))} napló van, "
                 f"{len(rows)} sor érkezett.")
    return rows, ''


def local_path_for(row, dest_dir=None):
    """Egy távoli napló helye ezen a gépen: <cél>\\<futás mappája>\\<fájlnév>.log

    KICSOMAGOLVA mentjük: a `.gz`-t az elemzéshez úgyis ki kell bontani, és egy olyan
    fájl, amit előbb kézzel ki kell tömöríteni, a gyakorlatban nem lesz elolvasva."""
    base = dest_dir or download_dir()
    folder = _safe_name(row.get('folder') or '')
    name = _safe_name(row.get('name') or 'naplo.log.gz')
    if name.endswith('.gz'):
        name = name[:-3]
    if not name.endswith('.log'):
        name += '.log'
    return os.path.join(base, folder, name) if folder else os.path.join(base, name)


def _safe_name(name):
    """Windows-on tiltott karakterek cseréje (a mappanév a Drive-ról jön)."""
    out = ''.join('-' if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in str(name or ''))
    return out.strip().rstrip('.')[:120]


def download_logs(run, url, password, rows, dest_dir=None, http=None,
                  progress=None, check_cancel=None, skip_existing=True):
    """A megadott naplók letöltése és kicsomagolása. Visszatérés: (letöltve, kihagyva, hibák).

    `progress(index, total, name)` - a hívó ezzel rajzol sávot; `check_cancel()` igazra
    megszakít. Egyetlen fájl hibája sosem állítja meg a többit: egy elérhetetlen napló
    kevesebb baj, mint egy félbehagyott letöltés."""
    dest = dest_dir or download_dir()
    done, skipped, errors = 0, 0, []
    total = len(rows)
    for i, row in enumerate(rows, 1):
        if check_cancel and check_cancel():
            logging.info("[LOGDL] A letöltést a felhasználó megszakította.")
            break
        path = local_path_for(row, dest)
        if skip_existing and os.path.isfile(path) and os.path.getsize(path) > 0:
            skipped += 1
            continue
        if progress:
            progress(i, total, row.get('folder') or row.get('name') or '')
        try:
            resp, err = _post(run, url, {'action': 'logget', 'pw': password,
                                         'id': row.get('id')}, http)
            if err:
                raise RuntimeError(err)
            blob = resp.get('gz')
            if not blob:
                raise RuntimeError('a szerver nem küldött tartalmat')
            data = gzip.decompress(base64.b64decode(blob))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as f:
                f.write(data)
            done += 1
            logging.info(f"[LOGDL] Letöltve: {path} ({len(data) / 1024:.0f} KB kicsomagolva)")
        except Exception as e:
            errors.append(f"{row.get('folder') or row.get('name')}: {e}")
            logging.warning(f"[LOGDL] Nem sikerült letölteni ({row.get('name')}): {e}")
    logging.info(f"[LOGDL] Kész: {done} letöltve, {skipped} már megvolt, {len(errors)} hiba.")
    return done, skipped, errors


# ===========================================================================
# A DEBUG-NAPLÓK TÖRLÉSE (2026-08-31, explicit user decision: "clear log" gomb)
# ===========================================================================
# MIÉRT KELL: a napló 5 MB x 3 fájl, és a technikus gyakran EGY konkrét gép futását
# akarja tisztán látni. Kézzel törölni azért nem lehet, mert a fájl FUT KÖZBEN NYITVA
# van - az Explorerből "A fájlt egy másik program használja" hibát ad.
#
# EZÉRT NEM ELÉG AZ os.remove(): a Windows nem engedi törölni a rotáló handler által
# nyitva tartott fájlt. A helyes sorrend: a handlert LEZÁRJUK (elengedi a fájlt) ->
# törlünk -> a handlert ÚJRANYITJUK. Az újranyitás a handler saját `_open()`-jén megy,
# tehát a `_BomRotatingFileHandler` UTF-8 BOM-ja is a helyére kerül (enélkül a friss
# napló a Jegyzettömbben ékezet-szemétként jelenne meg - lásd driver_tool.py).
#
# ÉS A TÖRLÉS TÉNYE BEKERÜL AZ ÚJ NAPLÓBA (Rule 0): egy üres napló önmagában nem árulja
# el, hogy törölték-e vagy sosem futott a program - és pont ez a különbség dönti el egy
# hibajelentésnél, hogy hiányzó bizonyítékot vagy hiányzó futást keresünk.

def clear_logs():
    """A debug-naplók (`DriverVarázsló_debug.log` + rotált másai) törlése.

    Visszatérés: (törölt_fájlok_száma, felszabadított_bájt, hibák_listája).

    A letöltött IDEGEN naplókat (`letoltott_naplok`) SZÁNDÉKOSAN nem bántja: azok más
    gépek bizonyítékai, amiket a technikus külön kért le - egy "napló törlése" gombtól
    senki nem várja, hogy azokat is elviszi."""
    import glob as _glob
    base = os.path.join(_app_data_dir(), LOG_BASENAME)
    # A rotált fájlok `.1`, `.2` végűek (backupCount=2), de gyűjtsük mintával, hogy egy
    # későbbi backupCount-változás se hagyjon itt fájlt.
    targets = sorted(set([base] + _glob.glob(base + '.*')))
    targets = [p for p in targets if os.path.isfile(p)]
    if not targets:
        logging.info("[LOGCLEAR] Nincs törölhető naplófájl.")
        return 0, 0, []

    sizes = {}
    for p in targets:
        try:
            sizes[p] = os.path.getsize(p)
        except OSError:
            sizes[p] = 0
    # Még a régi naplóba: ha valaki később ezt a fájlt menti ki, lássa a szándékot.
    logging.warning(f"[LOGCLEAR] NAPLÓ-TÖRLÉS kérve: {[os.path.basename(p) for p in targets]} "
                    f"({sum(sizes.values()) / 1048576:.1f} MB).")

    # A fájlt nyitva tartó handlerek lezárása. Csak azok, amik TÉNYLEG ezekre a fájlokra
    # mutatnak - egy jövőbeli másik fájl-handlert nem szabad mellékesen elkaszálni.
    handlers = []
    try:
        for h in list(logging.getLogger().handlers):
            fn = getattr(h, 'baseFilename', None)
            if fn and os.path.normcase(fn) == os.path.normcase(base):
                handlers.append(h)
    except Exception as e:
        logging.warning(f"[LOGCLEAR] A naplóző handlerek felderítése nem sikerült: {e}")

    for h in handlers:
        try:
            h.acquire()
            h.close()          # elengedi a fájlt: enélkül a törlés WinError 32-vel bukna
        except Exception as e:
            logging.debug(f"[LOGCLEAR] A handler lezárása nem sikerült: {e}")

    removed, freed, errors = 0, 0, []
    try:
        for p in targets:
            try:
                os.remove(p)
                removed += 1
                freed += sizes.get(p, 0)
            except Exception as e:
                errors.append(f"{os.path.basename(p)}: {e}")
    finally:
        # ÚJRANYITÁS MINDENKÉPPEN, akkor is, ha a törlés elhasalt - egy naplózás nélkül
        # továbbfutó program a lehető legrosszabb kimenet ebben a projektben.
        for h in handlers:
            try:
                h.stream = h._open()
            except Exception as e:
                errors.append(f"a naplózás újraindítása: {e}")
            finally:
                try:
                    h.release()
                except Exception:
                    pass

    # Az ÚJ naplóba (ezért van a handler-újranyitás után): mi tűnt el és mikor.
    logging.warning(f"[LOGCLEAR] Napló törölve: {removed} fájl, {freed / 1048576:.1f} MB "
                    f"felszabadítva. Hibák: {errors or 'nincs'}")
    return removed, freed, errors
