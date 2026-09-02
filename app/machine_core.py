"""A gép gyártófüggetlen azonosítása (WMI).

EREDET: ez a blokk az `app/oemcatalog_core.py`-ban élt, amíg a gyártói (Lenovo/Dell/HP)
driver-katalógus létezett. Azt a forrást 2026-09-02-án **teljesen eltávolítottuk**
(explicit user decision - lásd CLAUDE.md), a gépazonosítás viszont ATTÓL FÜGGETLENÜL
kell: a napló-feltöltés ebből rakja össze a Drive-mappa emberi nevét
('DESKTOP-8H3K2 - HP EliteDesk 800 G2 SFF - 2026-09-02 10-06'). Ezért került ide,
saját modulba, ahelyett hogy a törléssel együtt elveszett volna.

Sosem dob: hiba esetén üres mezőkkel tér vissza, és a hívó a nyers gépnevet használja.
"""

# === AUTO-IMPORTS ===
import json
import logging
# === /AUTO-IMPORTS ===

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
# A `vendor` mezőt ma már csak naplózásra/kiírásra használjuk (a gyártói katalógus,
# ami korábban ez alapján választott szolgáltatót, megszűnt).
VENDOR_PATTERNS = (
    ('lenovo', ('lenovo',)),
    ('dell', ('dell',)),
    ('hp', ('hp', 'hewlett')),
)

# Placeholder gyártónevek. ÖSSZERAKOTT GÉPEN ez a normális eset, nem hiba - és pont
# ilyenkor az ALAPLAP az egyetlen érdemi azonosító (a bolti bevétel nagy része ilyen).
PLACEHOLDER_VALUES = (
    'to be filled by o.e.m.', 'default string', 'system manufacturer',
    'system product name', 'o.e.m.', 'not specified', 'none', '',
)


def is_placeholder(v):
    return str(v or '').strip().lower() in PLACEHOLDER_VALUES


# Régi név, hogy a meglévő hívások ne törjenek el.
_is_placeholder = is_placeholder


def detect_machine(run_fn):
    """A gép gyártófüggetlen azonosítása. MINDIG ad vissza dictet (üres vendorral is).

    Visszatérés: {'vendor','manufacturer','model','sku','product_name','serial',
                  'board_vendor','board_product','build','os_tag'}"""
    info = {}
    try:
        res = run_fn(["powershell", "-NoProfile", "-Command", MACHINE_QUERY_PS],
                     encoding='utf-8', timeout=120)
        raw = (getattr(res, 'stdout', '') or '').strip()
        if raw:
            info = json.loads(raw) or {}
    except Exception as e:
        logging.warning(f"[GEP] A gépazonosítás lekérdezése sikertelen: {e}")

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
        # Windows 11 = 22000-es buildtől.
        'os_tag': 'Win11' if build >= 22000 else 'Win10',
    }
    if is_placeholder(manufacturer) or is_placeholder(model):
        logging.info(f"[GEP] A gépazonosító mezők általánosak (összerakott gép?): "
                     f"gyártó='{manufacturer}', modell='{model}', alaplap="
                     f"'{machine['board_vendor']} {machine['board_product']}'.")
    logging.info(f"[GEP] Gép: gyártó='{manufacturer}' modell='{model}' "
                 f"SKU='{machine['sku']}' (OS: {machine['os_tag']}, build {build})")
    return machine
