"""Energiaséma teljesítmény-módba állítása - a lánc záró lépése.

MIÉRT (explicit user decision, 2026-09-01): a szervizből kiadott gép ne legyen lassú.
A felhasználó szavaival: *"azt allitsa mar be az autofix vegen h a laptopok se legyenek
lassuak utana, mehet a teljesitmeny centrikus meg minden maxra huzva, ne saveljen aramot
a gep utana"*. A frissen bedriverezett gép legrosszabb visszajelzése az, hogy "gyorsabb
volt, mielőtt behoztam" - miközben a valódi ok jellemzően nem a driver, hanem az, hogy a
Windows Kiegyensúlyozott vagy Energiatakarékos sémán áll.

A DÖNTÉS ÉRDEMI RÉSZE A SÉMA-VÁLTÁS: a "Nagy teljesítményű" séma definíció szerint hozza
a processzor 100%-os minimumát, a kikapcsolt PCIe-energiagazdálkodást és a nem parkoló
lemezt. A modul ezen felül EXPLICIT is beállítja ezeket - egy OEM-image ugyanis
felülírhatja a séma alapértékeit (mérve nem egyszer: Dell/Lenovo gyári image saját
értékeket tesz a beépített sémákba is), és ilyenkor a puszta séma-váltás nem elég.

AMIHEZ SZÁNDÉKOSAN NEM NYÚLUNK: az alvás- és kijelző-időzítők. Azok NEM lassítják a
gépet, viszont az elállításuk valódi kellemetlenség az ügyfélnek (soha el nem alvó
képernyő, fölösleges melegedés), és a legtöbben hibaként hoznák vissza. A "ne legyen
lassú" kérést a processzor/busz/lemez beállításai teljesítik, nem az alvás tiltása.

NYELVFÜGGETLENSÉG: a `powercfg /getactivescheme` kimenete LOKALIZÁLT ("Energiaséma
GUID-ja:" magyarul), ezért kizárólag a GUID-ot olvassuk ki regexszel, és soha nem hozunk
döntést a szövegből. Ugyanaz a szabály, ami miatt a `delete_succeeded` magyar szótöve
egyszer már hamis sikert okozott ebben a projektben; a `powercfg` alias-kulcsszavak
(SUB_PROCESSOR, PROCTHROTTLEMIN...) viszont MINDEN nyelven azonosak, azok biztonságosak.

Ez a modul semmit nem dob: minden hiba naplózódik és a hívó `applied`/`failed` listát kap.
Egy energiaséma-beállítás soha nem buktathat el egy egyébként sikeres driver-láncot.
"""

# === AUTO-IMPORTS ===
import re
import logging
# === /AUTO-IMPORTS ===

# A Windows beépített "Nagy teljesítményű" sémája. A GUID minden Windows-nyelven azonos.
HIGH_PERFORMANCE_GUID = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
BALANCED_GUID = '381b4222-f694-41f0-9685-ff5bb260df2e'

# A teljesítményt ÉRDEMBEN befolyásoló beállítások: (alcsoport, beállítás, AC, DC, címke).
#
# Az alias-kulcsszavak nyelvfüggetlenek. Az AC (hálózat) és DC (akkumulátor) érték külön
# állítható, és ez itt szándékos: a felhasználó kérése az volt, hogy a gép akkumulátoron
# se legyen lassú, ezért a DC oldal is teljesítmény-orientált.
#
# A DISKIDLE=0 jelentése "soha" (nem nulla perc): a lemez leparkolása utáni felpörgés az
# egyik legjobban ÉRZÉKELHETŐ lassulás egy HDD-s gépen.
PERFORMANCE_SETTINGS = [
    ('SUB_PROCESSOR', 'PROCTHROTTLEMIN', 100, 100, 'processzor minimális állapota'),
    ('SUB_PROCESSOR', 'PROCTHROTTLEMAX', 100, 100, 'processzor maximális állapota'),
    ('SUB_PCIEXPRESS', 'ASPM', 0, 0, 'PCI Express energiagazdálkodás'),
    ('SUB_DISK', 'DISKIDLE', 0, 0, 'merevlemez leállítása'),
]

# A USB szelektív felfüggesztésnek nincs stabil alias-a, GUID-dal kell hivatkozni rá.
# Kikapcsolva: az USB-eszközök (egér, billentyűzet, dokkoló) nem "ébredeznek" használatkor.
USB_SUBGROUP_GUID = '2a737441-1930-4402-8d77-b2bebba308a3'
USB_SELECTIVE_SUSPEND_GUID = '48e6b7a6-50f5-4782-a5d4-53bb8f07e226'

_GUID_RE = re.compile(r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                      r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12})')


def parse_active_scheme(stdout):
    """A `powercfg /getactivescheme` kimenetéből a GUID + a zárójeles séma-név.

    Tiszta függvény, offline tesztelhető. A NÉV csak naplózásra/kiírásra való - döntést
    soha nem hozunk belőle, mert lokalizált."""
    if not stdout:
        return None, ''
    m = _GUID_RE.search(stdout)
    if not m:
        return None, ''
    name = ''
    # A záró `*` az aktív sémát jelöli a `powercfg /list` kimenetében
    # ("... (Teljesítménycentrikus) *"). A /getactivescheme nem teszi ki, de a parser
    # mindkét kimenetet kapja, ezért megengedjük.
    nm = re.search(r'\(([^)]*)\)\s*\*?\s*$', stdout.strip())
    if nm:
        name = nm.group(1).strip()
    return m.group(1).lower(), name


def read_active_scheme(run_fn):
    """Az aktív energiaséma (guid, név). Hiba esetén (None, '')."""
    try:
        res = run_fn(['powercfg', '/getactivescheme'])
        if res.returncode != 0:
            logging.warning(f"[POWER] Az aktív séma lekérdezése sikertelen "
                            f"(returncode={res.returncode}): {(res.stderr or '')[:200]}")
            return None, ''
        guid, name = parse_active_scheme(res.stdout)
        logging.info(f"[POWER] Jelenlegi energiaséma: {guid} ({name or 'névtelen'})")
        return guid, name
    except Exception as e:
        logging.warning(f"[POWER] Az aktív séma lekérdezése kivételre futott: {e}")
        return None, ''


def ensure_high_performance_scheme(run_fn):
    """A Nagy teljesítményű séma aktívvá tétele. Visszatérés: True, ha sikerült.

    Ha a séma nincs a gépen, LÉTREHOZZUK a beépített sablonból (`/duplicatescheme`) -
    számos OEM-image, és a modern készenlétet (Modern Standby) használó laptopok egy
    része, egyszerűen nem listázza. A duplikálás után a séma új GUID-ot kap, ezért az
    aktiválás annak a GUID-jával megy, nem a sablonéval."""
    res = run_fn(['powercfg', '/setactive', HIGH_PERFORMANCE_GUID])
    if res.returncode == 0:
        logging.info("[POWER] A Nagy teljesítményű séma aktiválva.")
        return True

    logging.info(f"[POWER] A Nagy teljesítményű séma nincs a gépen "
                 f"(returncode={res.returncode}) - létrehozás a beépített sablonból.")
    dup = run_fn(['powercfg', '/duplicatescheme', HIGH_PERFORMANCE_GUID])
    if dup.returncode != 0:
        logging.warning(f"[POWER] A séma létrehozása sem sikerült "
                        f"(returncode={dup.returncode}): {(dup.stdout or '')[:200]}")
        return False
    new_guid, _ = parse_active_scheme(dup.stdout)
    if not new_guid:
        logging.warning("[POWER] A létrehozott séma GUID-ja nem olvasható ki a kimenetből.")
        return False
    res2 = run_fn(['powercfg', '/setactive', new_guid])
    ok = res2.returncode == 0
    logging.info(f"[POWER] Létrehozott séma ({new_guid}) aktiválása: "
                 f"{'sikeres' if ok else 'SIKERTELEN'}")
    return ok


def apply_performance_plan(run_fn, log=None):
    """A gép teljesítmény-módba állítása. Visszatérés: eredmény-dict.

    Kulcsok: ok (bool - a séma aktív lett-e), previous_guid, previous_name,
    applied (címkék listája), failed (címkék listája).

    SOHA NEM DOB: a hívó egy már sikeres lánc legvégén hívja, és egy energiaséma-hiba
    nem teheti hibássá a driver-telepítést."""
    say = log or (lambda _m: None)
    out = {'ok': False, 'previous_guid': None, 'previous_name': '',
           'applied': [], 'failed': []}
    try:
        prev_guid, prev_name = read_active_scheme(run_fn)
        out['previous_guid'], out['previous_name'] = prev_guid, prev_name

        if not ensure_high_performance_scheme(run_fn):
            say('⚠️ A Nagy teljesítményű energiasémát nem sikerült beállítani - a gép '
                'energiabeállításai változatlanok maradtak.')
            return out
        out['ok'] = True

        # Az alias-os beállítások. Egy hiányzó beállítás nem hiba: több alcsoport
        # gép- és Windows-kiadásfüggő (pl. a SUB_PCIEXPRESS asztali gépeken hiányozhat).
        for sub, setting, ac, dc, label in PERFORMANCE_SETTINGS:
            ok_ac = run_fn(['powercfg', '/setacvalueindex', 'SCHEME_CURRENT',
                            sub, setting, str(ac)]).returncode == 0
            ok_dc = run_fn(['powercfg', '/setdcvalueindex', 'SCHEME_CURRENT',
                            sub, setting, str(dc)]).returncode == 0
            if ok_ac or ok_dc:
                out['applied'].append(label)
                logging.info(f"[POWER] Beállítva: {label} (AC={ac} {'ok' if ok_ac else 'HIBA'}, "
                             f"DC={dc} {'ok' if ok_dc else 'HIBA'})")
            else:
                out['failed'].append(label)
                logging.info(f"[POWER] Nem elérhető ezen a gépen: {label} ({sub}/{setting})")

        # USB szelektív felfüggesztés - GUID-dal, mert nincs stabil alias-a.
        u_ac = run_fn(['powercfg', '/setacvalueindex', 'SCHEME_CURRENT',
                       USB_SUBGROUP_GUID, USB_SELECTIVE_SUSPEND_GUID, '0']).returncode == 0
        u_dc = run_fn(['powercfg', '/setdcvalueindex', 'SCHEME_CURRENT',
                       USB_SUBGROUP_GUID, USB_SELECTIVE_SUSPEND_GUID, '0']).returncode == 0
        if u_ac or u_dc:
            out['applied'].append('USB szelektív felfüggesztés')
            logging.info("[POWER] Beállítva: USB szelektív felfüggesztés kikapcsolva.")
        else:
            out['failed'].append('USB szelektív felfüggesztés')

        # A módosítások CSAK egy újbóli /setactive után lépnek életbe - e nélkül a
        # beállítások bekerülnek a sémába, de a futó rendszerre nem érvényesülnek.
        run_fn(['powercfg', '/setactive', 'SCHEME_CURRENT'])
        logging.info(f"[POWER] Teljesítmény-mód kész. Beállítva: {len(out['applied'])}, "
                     f"nem elérhető: {len(out['failed'])}.")
    except Exception as e:
        logging.warning(f"[POWER] A teljesítmény-mód beállítása kivételre futott "
                        f"(a lánc ettől még sikeres): {e}", exc_info=True)
    return out
