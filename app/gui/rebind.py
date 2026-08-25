"""DriverVarázsló GUI - ESZKÖZ-ÚJRAKÖTÉS ("miért nem a friss drivert használja?").

A DriverToolApi része (összerakás: app/gui/api.py).

MIÉRT LÉTEZIK - terepen kétszer bizonyítva, ThinkPad T580, 2026-08-24 és 08-25:
egy driver FEL TUD MENNI ÚGY, hogy az eszköz mégsem indul el rajta. A gép saját
`setupapi.dev.log`-ja szó szerint ezt írta:

    Installing best driver (oem19.inf) on device 'ACPI\\LEN009B'
    Strong Name=oem19.inf:...:LENOVO_GROUP53_InterTouch_Win8_Inst:19.3.4.228
    Start: ACPI\\LEN009B\\4&27A0EA9D&0
    Device 'ACPI\\LEN009B' not started: Device has problem: 0x0a (CM_PROB_FAILED_START)

A Windows ilyenkor VISSZAESIK a saját általános driverére (itt: `msmouse.inf`, PS/2
egér-emuláció), ami hibátlanul elindul - tehát a ConfigManagerErrorCode 0 lesz, és minden
hibakód-alapú ellenőrzés (a miénk is) tisztának látja a gépet. Közben a tapipad szaggat,
dobálja a kurzort, elveszti a trackinget, a fizikai gombjai nem működnek - mert a
precíziós út helyett PS/2-emulációban fut.

MI GYÓGYÍTJA MEG: az eszköz ÚJRAENUMERÁLÁSA. A technikus terepen véletlenül találta meg -
kivette az SSD-t a gépből, betette máshova, majd visszarakta, és utána hibátlan lett a
tapipad. Nem új driver kellett: a friss eszköz-felderítéskor a Windows NULLÁRÓL választ
drivert, és akkor a gyári csomag már el tud indulni. Ennek pontos szoftveres megfelelője
a `pnputil /remove-device` + `/scan-devices` páros, és ezt csinálja ez a modul - hogy
soha többé ne kelljen hozzányúlni a vashoz.

EZ NEM A TILTOTT "mentsük el a régi drivert és rakjuk vissza" MINTA (lásd CLAUDE.md):
itt a lánc által MOST telepített, a DriverStore-ban ott lévő csomag telepítését fejezzük
be. Semmit nem konzerválunk a gép fix előtti állapotából.
"""
import os
import time
import json
import logging

from app.common import _ps_quote
from app.wu_core import WU_PNP_QUERY_PS
from app.wu_core import _filter_wu_scan_devices
from app.wu_core import _is_inbox_driver
from app.wu_core import _hwid_tokens
from app.wu_core import is_specific_hwid
from app.wu_core import extract_inf_hardware_ids
from app.wu_core import _read_text_best_effort
from app.wu_core import driverstore_package_inf
from app.wu_core import STORAGE_RISK_CLASSES
from app.wu_core import FIRMWARE_RISK_CLASSES

# A PnP-nek kell pár másodperc, mire az újraenumerálás után rákötötte a drivert.
REBIND_SETTLE_SECONDS = 5

# CSAK EZEKET AZ OSZTÁLYOKAT ENUMERÁLJUK ÚJRA - fehérlista, nem feketelista.
#
# Terepen (T580, Build 274) a "minden gyártó-kódos, alapdriveres eszköz" szabály 21
# eszközt jelölt ki, köztük olyanokat, amikhez semmi közünk és amiknek a csomópontját
# kiszedni egyenesen veszélyes:
#     Platformmegbízhatósági modul 2.0 [SecurityDevices]   <- TPM (BitLocker!)
#     Lefelé irányuló PCI Express-kapcsolóport [System]     <- PCIe port, mögötte eszközök
#     xHCI-kompatibilis USB-állomásvezérlő [USB]            <- az EGÉSZ USB egy időre
#     USB-gyökérhub x2, ACPI processzorösszesítő, tápadapter, Intel energiaellátási modul
# Ezek mind a Windows saját busz-/infrastruktúra-driverén futnak, és ez a HELYES állapot -
# gyári driver nem is létezik hozzájuk. A felhasználó tünete (tapipad, gombok, hang, háló)
# egyik esetben sem ezekből jön.
#
# A fehérlistán csak olyan osztály van, ahol (a) létezhet gyári driver, és (b) a csomópont
# pár másodperces eltűnése ártalmatlan. Ha egy jövőbeli eset új osztályt igényel, ide kell
# felvenni - és leírni, miért biztonságos.
REBIND_ALLOWED_CLASSES = {
    'MOUSE', 'HIDCLASS', 'KEYBOARD',        # a fő eset: tapipad, TrackPoint, billentyűzet
    'MEDIA',                                # hangkártya / hang-kodek
    'NET', 'BLUETOOTH',                     # hálózat
    'CAMERA', 'IMAGE', 'BIOMETRIC',         # kamera, szkenner, ujjlenyomat
    'SMARTCARDREADER', 'MONITOR',
}

# A GYÁRTÓT ÉS AZ ESZKÖZT azonosító tokenek. Ezeknek KELL egyezniük ahhoz, hogy két
# hardver-azonosítót ugyanarra az eszközre vonatkozónak tekintsünk. A SUBSYS/REV/COL/MI
# eltérhet (ugyanaz a chip más gépgyártói változatban, illetve a kompozit eszköz
# interfészei), a VEN/DEV (PCI, ACPI) és a VID/PID (USB, HID) viszont nem.
_IDENTITY_PREFIXES = ('VEN_', 'DEV_', 'VID_', 'PID_')


def _identity_tokens(tokens):
    return frozenset(t for t in tokens if t.startswith(_IDENTITY_PREFIXES))


def _strict_hwid_match(inf_id, dev_hwid):
    """SZIGORÚ azonosító-egyezés (a laza `_hwid_matches` helyett - lásd
    _staged_vendor_inf_for indoklását: a laza változat terepen Intel GPS-drivert húzott
    egy USB kompozit eszközre, és a gomb ezután kiszedte a tapipadot)."""
    a, b = _hwid_tokens(inf_id), _hwid_tokens(dev_hwid)
    if not a or not b or a[0] != b[0]:          # busz-előtag nélkül / eltérő buszon: nem
        return False
    ia, ib = _identity_tokens(a[1]), _identity_tokens(b[1])
    if not ia or not ib:
        # Nincs VEN/DEV-szerű tagja valamelyiknek (pl. `ACPI\LEN009B`): csak a teljes
        # tokenkészlet AZONOSSÁGÁT fogadjuk el - részhalmaz itt vaktalálat lenne.
        return a[1] == b[1]
    if ia != ib:
        return False
    # A gyártó+eszköz egyezik; a többi tag (SUBSYS/REV/COL/MI) egyik irányban bővebb lehet.
    return a[1] <= b[1] or b[1] <= a[1]


class GuiRebindMixin:
    """Eszköz-újrakötés: automatikusan (AutoFix záró köre) és kézzel (gomb)."""

    # ------------------------------------------------------------------
    # KÖZÖS MAG - ezt hívja az AutoFix regresszió-javítója ÉS a kézi gomb is
    # ------------------------------------------------------------------
    def _rebind_device(self, pnp, inf_path, dev_name, dev_class, task_id):
        """Egy eszköz visszakötése a stage-elt gyári driverre.

        Visszatérés: 'fixed' | 'needs_reboot' | 'failed'.

        A LÉPCSŐK ÉS AZ INDOKLÁSUK (terepen mérve, ThinkPad T580):
          1) a csomag újratelepítése (`pnputil /add-driver ... /install`) - ez önmagában
             sokszor NEM vált kötést, mert a Windows a meglévő drivert elég jónak látja;
          2) a csomópont ELTÁVOLÍTÁSA (`/remove-device`) + `/scan-devices` - néha elég;
          3) ha nem: ÚJRAINDÍTÁS. **Ez a lényeg.** A technikus terepen az SSD ki-be
             pakolásával javította meg a tapipadot, és annak a hatása nem a csomópont
             eltávolítása volt, hanem hogy UTÁNA A GÉP ÚJRAINDULT és a Windows a teljes
             eszközfát nulláról derítette fel. A Build 273-as futás ezt be is bizonyította:
             a `/remove-device` + `/scan-devices` páros 8 eszközből NULLÁT kötött vissza -
             mert újraindítás nélkül a PnP nem építi újra a köteléket.
             Ezért az eltávolítás után `needs_reboot`-ot adunk vissza: a csomópont ilyenkor
             már NINCS meg, tehát a következő induláskor a Windows frissen felderíti - ez a
             lemez visszadugásának pontos megfelelője.

        A tárolóvezérlőket/lemezeket SOSEM távolítjuk el: ott a csomópont eltűnése a futó
        rendszert viheti el. Beviteli/egyéb eszköznél ez ártalmatlan."""
        if inf_path:
            logging.info(f"[REBIND] 1. lépés - újratelepítés: {dev_name} <- {inf_path}")
            self._run(['pnputil', '/add-driver', inf_path, '/install'],
                      timeout=600, ok_codes=(0, 259, 3010))
            self._run(['pnputil', '/scan-devices'], timeout=300)
            if self._device_on_vendor_driver(pnp):
                logging.warning(f"[REBIND] SIKER (újratelepítéssel): {dev_name}")
                return 'fixed'

        cls = (dev_class or '').strip().upper()
        if cls in STORAGE_RISK_CLASSES or cls in FIRMWARE_RISK_CLASSES:
            logging.info(f"[REBIND] {dev_name} [{cls}]: tároló/firmware - eltávolítás KIHAGYVA "
                         f"(a csomópont eltűnése a futó rendszert vinné).")
            return 'failed'

        logging.warning(f"[REBIND] 2. lépés - a csomópont eltávolítása: {dev_name} [{pnp}]")
        self.emit('task_progress', {'task': task_id, 'log': f'   🔄 {dev_name}: eszköz eltávolítása, hogy a Windows újra felderítse...'})
        rem = self._run(['pnputil', '/remove-device', pnp], timeout=300, ok_codes=(0, 1, 3010))
        removed = getattr(rem, 'returncode', 1) in (0, 3010)
        if not removed:
            # A /remove-device csak Win10 1903-tól létezik; régebbin a letiltás/
            # engedélyezés páros a megfelelője.
            logging.info(f"[REBIND] A /remove-device nem elérhető (rc={getattr(rem, 'returncode', '?')}) "
                         f"- letiltás/engedélyezés jön.")
            ps = (f"$id='{_ps_quote(pnp)}'; "
                  "Disable-PnpDevice -InstanceId $id -Confirm:$false -EA SilentlyContinue; "
                  "Start-Sleep -Seconds 3; "
                  "Enable-PnpDevice -InstanceId $id -Confirm:$false -EA SilentlyContinue")
            r2 = self._run(["powershell", "-NoProfile", "-Command", ps], timeout=300)
            removed = getattr(r2, 'returncode', 1) == 0
        self._run(['pnputil', '/scan-devices'], timeout=300)
        time.sleep(REBIND_SETTLE_SECONDS)
        if self._device_on_vendor_driver(pnp):
            logging.warning(f"[REBIND] SIKER (újrafelderítéssel): {dev_name}")
            return 'fixed'
        if removed:
            # A csomópont eltűnt, de a futó rendszerben nem épült újra a kötés. Az
            # újraindítás ezt oldja meg - ekkor derül fel az eszköz nulláról.
            logging.warning(f"[REBIND] {dev_name}: eltávolítva, a kötés ÚJRAINDÍTÁS után épül fel.")
            return 'needs_reboot'
        logging.error(f"[REBIND] NEM SIKERÜLT és eltávolítani sem lehetett: {dev_name}")
        return 'failed'

    def _device_on_vendor_driver(self, pnp):
        """Gyári (nem Windows-alap) driveren fut-e most az eszköz?"""
        info = (self._get_installed_driver_info() or {}).get(pnp) or {}
        return bool(info) and not _is_inbox_driver(info)

    def _rebind_candidates(self, devices, inst):
        """Mely eszközöket érdemes újra felderíttetni a Windowszal?

        MIÉRT NEM AZ INF-EKBŐL DOLGOZUNK (élő méréssel bizonyítva a T580 lemezén):
        az `extract_inf_hardware_ids` csak az ALÁHÚZÁST tartalmazó azonosítókat tartja meg,
        ezért a `synpd.inf`-ből kiolvasott 16 azonosító közt NINCS ott az `ACPI\\LEN009B` -
        vagyis a csomag-INF alapján épp azt a tapipadot NEM találtuk volna meg, ami miatt
        az egész funkció készült. Ugyanez a laza illesztés viszont a `hdbusext.inf`-et
        ráhúzta a HD Audio vezérlőre. Az INF-alapú párosítás tehát rossz alapon állt:
        egyszerre volt vak és túl bőkezű.

        AMIT HELYETTE CSINÁLUNK - pontosan az, ami a lemez ki-be pakolásakor történik:
        nem mi választunk csomagot, hanem ELTÁVOLÍTJUK a csomópontot, és az újraindítás
        után a WINDOWS választ drivert nulláról, a saját rangsorolásával. Ez nem tud
        rosszabb állapotot előidézni: ha nincs jobb driver, ugyanazt az alapdrivert köti
        vissza, mint eddig.

        Kiket veszünk be: Windows-ALAPDRIVEREN futó, GYÁRTÓ-KÓDOS azonosítójú eszközök.
        Kiket nem: tároló/firmware (a csomópont eltűnése a futó rendszert vinné), és a
        típuskódos azonosítójú eszközök (rendszeridőzítő, PCI-híd - ezekhez gyári driver
        nem is létezik, felesleges bolygatni őket)."""
        out = []
        for d in devices or []:
            info = inst.get(d.get('pnp_id') or '')
            if not info or not _is_inbox_driver(info):
                continue                      # gyári driveren fut - nincs dolgunk vele
            cls = (d.get('pclass') or '').strip().upper()
            if cls not in REBIND_ALLOWED_CLASSES:
                continue                      # lásd a REBIND_ALLOWED_CLASSES indoklását
            if cls in STORAGE_RISK_CLASSES or cls in FIRMWARE_RISK_CLASSES:
                continue
            hwids = [h for h in (d.get('all_hwids') or []) if h and is_specific_hwid(h)]
            if not hwids:
                continue                      # típuskódos: gyári driver nem létezik hozzá
            out.append((d, info))
        return out

    def _staged_vendor_inf_for(self, dev, third_party):
        """Van-e a DriverStore-ban olyan STAGE-ELT gyári csomag, ami EZT az eszközt állítja?

        SZIGORÚ EGYEZÉS, és ez nem óvatoskodás - terepen (T580, Build 273) a laza illesztés
        aktívan KÁRT OKOZOTT. A `_hwid_matches` token-részhalmaz szabálya általános
        eszközökre teljesen oda nem való csomagokat húzott rá:

            USB kompozit eszköz          -> intelgnssdriver.inf   (Intel GPS-driver)
            Intel USB 3.0 vezérlő        -> appleusbvhci.inf      (Apple USB)
            USB kompozit eszköz          -> rtlejf.inf            (Realtek kártyaolvasó)

        A gomb ezután `remove-device`-szal kiszedte ezeket az eszközöket (köztük a tapipad
        HID-gyerekeit), és nem tudta visszakötni őket - vagyis pont azt rontotta el, aminek
        a javítására való. Két szabály zárja ki ezt:

          1) MINDKÉT oldalnak KONKRÉT, gyártó-kódos azonosítónak kell lennie
             (`is_specific_hwid`). Egy `USB\\COMPOSITE`, `USB\\CLASS_03` vagy `*PNP0F13`
             típuskódra bármely gyártó csomagja "illeszkedne" - ezekre soha nem lépünk.
          2) PONTOS token-egyezés kell, nem részhalmaz: az INF-ben szereplő azonosító
             tokenkészletének AZONOSNAK kell lennie az eszközével, vagy az eszközének kell
             bővebbnek lennie ugyanazon a buszon úgy, hogy a gyártó+eszköz (VEN/DEV, VID/PID)
             tokenek mind egyeznek. Így a `SUBSYS`/`REV` eltérés még belefér, egy másik
             gyártó csomagja viszont nem.

        Visszatérés: (INF útvonala, eredeti INF-név) vagy (None, '')."""
        hwids = [h for h in (dev.get('all_hwids') or []) if h and is_specific_hwid(h)]
        if not hwids:
            return None, ''
        for pkg in third_party or []:
            orig = (pkg.get('original') or '').strip()
            if not orig:
                continue
            path = driverstore_package_inf(orig)
            if not path:
                continue
            try:
                ids = extract_inf_hardware_ids(_read_text_best_effort(path))
            except Exception:
                continue
            for inf_id in ids:
                if not is_specific_hwid(inf_id):
                    continue
                for hw in hwids:
                    if _strict_hwid_match(inf_id, hw):
                        logging.info(f"[REBIND] Egyezés: {dev.get('name')} [{hw}] <- {orig} [{inf_id}]")
                        return path, orig
        return None, ''

    # ------------------------------------------------------------------
    # KÉZI GOMB
    # ------------------------------------------------------------------
    def rescan_and_rebind_drivers(self):
        """KÉZI ÚJRASCANNELÉS: azok az eszközök, amik Windows-alapdriveren futnak, pedig
        van hozzájuk STAGE-ELT gyári csomag a gépen - ezeket kötjük vissza a gyárira.

        Ez a gomb arra való, amit a technikus eddig az SSD ki-be pakolásával oldott meg."""
        logging.info("[API] rescan_and_rebind_drivers() - kézi eszköz-újrakötés")
        if self.target_os_path:
            self.emit('toast', {'message': '❌ Offline módban nem elérhető!', 'type': 'error'})
            return

        def worker():
            task = 'rebind'
            self.emit('task_start', {'task': task, 'title': 'Eszközök újrakötése a gyári driverekre'})
            fixed, failed, checked = 0, [], 0
            try:
                self.emit('task_progress', {'task': task, 'log': 'Eszközök és telepített driverek felmérése...', 'indeterminate': True})
                res = self._run(["powershell", "-NoProfile", "-Command", WU_PNP_QUERY_PS], encoding='utf-8')
                devices = _filter_wu_scan_devices(json.loads(res.stdout or '[]'))
                inst = self._get_installed_driver_info() or {}
                third_party = [d for d in (self._get_third_party_drivers() or []) if d.get('original')]
                self.emit('task_progress', {'task': task, 'log': f'{len(devices)} eszköz, {len(third_party)} gyári driver-csomag a gépen.'})

                candidates = self._rebind_candidates(devices, inst)
                logging.info(f"[REBIND] {len(candidates)} jelölt: Windows-alapdriveren fut, "
                             f"gyártó-kódos azonosítóval, nem tároló/firmware.")
                for d, info in candidates:
                    logging.info(f"[REBIND]   jelölt: {d.get('name')} [{d.get('pclass')}] "
                                 f"most: {info.get('inf')} ({info.get('provider')})")

                # A csomagot NEM mi választjuk ki (lásd _rebind_candidates indoklását):
                # eltávolítjuk a csomópontot, és a Windows dönt az újraindítás után. Ha
                # történetesen van stage-elt gyári csomag, amit szigorúan az eszközhöz
                # tudunk kötni, azt előbb megpróbáljuk telepíteni - hátha reboot nélkül is
                # megoldódik. De ez csak gyorsítás, nem feltétel.
                todo = []
                for d, info in candidates:
                    checked += 1
                    path, orig = self._staged_vendor_inf_for(d, third_party)
                    todo.append((d, info, path, orig or '(a Windows választ)'))
                if not todo:
                    self.emit('task_progress', {'task': task, 'log': '\n✅ Nincs olyan eszköz, ami alapdriveren futna, pedig van hozzá gyári csomag a gépen.'})
                    self.emit('task_progress', {'task': task, 'log': 'Ha valamelyik eszköz mégis rosszul működik, ahhoz a gépen NINCS gyári driver - a "Driver Keresés és Telepítés" menüben kerestethetsz hozzá.'})
                    self.emit('task_complete', {'task': task, 'status': 'Nincs javítanivaló'})
                    return

                self.emit('task_progress', {'task': task, 'log': f'\n🔧 {len(todo)} eszközhöz VAN gyári driver a gépen, mégis alapdriveren fut - visszakötés:'})
                pending = []
                for i, (d, info, path, orig) in enumerate(todo, 1):
                    if self._cancel_flag:
                        break
                    name = d.get('name') or d.get('pnp_id')
                    self.emit('task_progress', {'task': task, 'log': f'\n({i}/{len(todo)}) {name}\n   most: {info.get("inf")} ({info.get("provider")}) → gyári: {orig}',
                                                'current': i, 'total': len(todo)})
                    state = self._rebind_device(d.get('pnp_id'), path, name, d.get('pclass'), task)
                    if state == 'fixed':
                        fixed += 1
                        after = (self._get_installed_driver_info() or {}).get(d.get('pnp_id')) or {}
                        self.emit('task_progress', {'task': task, 'log': f'   ✅ Sikerült - most a gyári driveren fut ({after.get("inf")}).'})
                    elif state == 'needs_reboot':
                        pending.append(name)
                        self.emit('task_progress', {'task': task, 'log': '   🔄 Eltávolítva - a Windows az ÚJRAINDÍTÁS után deríti fel újra (ez a lemez visszadugásának megfelelője).'})
                    else:
                        failed.append(name)
                        self.emit('task_progress', {'task': task, 'log': '   ❌ Nem sikerült - az eszköz a Windows alapdriverén marad.'})

                self.emit('task_progress', {'task': task, 'log': f'\n📊 Kész: {fixed} eszköz azonnal visszakötve.'})
                if failed:
                    self.emit('task_progress', {'task': task, 'log': f'⚠️ {len(failed)} eszközt nem sikerült: {", ".join(failed[:6])}'})
                    self.emit('task_progress', {'task': task, 'log': '👉 Ezekhez a gyártó letöltőoldaláról telepíts drivert kézzel.'})
                if pending:
                    # EZT KI KELL MONDANI ÉS FEL KELL AJÁNLANI: a csomópontok már NINCSENEK
                    # meg, tehát ezek az eszközök AZ ÚJRAINDÍTÁSIG nem működnek. Enélkül a
                    # technikus egy elrontott gépet venne át - pontosan az a hiba, ami a
                    # Build 273-as futásban megtörtént.
                    self.emit('task_progress', {'task': task, 'log': f'\n🔄 {len(pending)} eszköz ÚJRAINDÍTÁST igényel: {", ".join(pending[:6])}'})
                    self.emit('task_progress', {'task': task, 'log': '❗ FONTOS: ezek az eszközök az újraindításig NEM működnek - a Windows ekkor deríti fel őket újra, és ekkor kapják meg a gyári drivert. Pontosan ez történik akkor is, amikor kihúzod és visszadugod a lemezt.'})
                self.emit('task_complete', {'task': task,
                                            'status': f'✅ {fixed} azonnal javítva' + (f', {len(pending)} újraindítás után' if pending else ''),
                                            'need_reboot': bool(pending)})
                if pending:
                    time.sleep(1)
                    self.emit('ask_reboot', None)
            except Exception as e:
                logging.error(f"[REBIND] Hiba a kézi újrakötésben: {e}", exc_info=True)
                self.emit('task_error', {'task': task, 'error': str(e)})

        self._safe_thread('rebind', worker)
