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
from app.wu_core import _hwid_matches
from app.wu_core import extract_inf_hardware_ids
from app.wu_core import _read_text_best_effort
from app.wu_core import driverstore_package_inf
from app.wu_core import STORAGE_RISK_CLASSES
from app.wu_core import FIRMWARE_RISK_CLASSES

# A PnP-nek kell pár másodperc, mire az újraenumerálás után rákötötte a drivert.
REBIND_SETTLE_SECONDS = 5


class GuiRebindMixin:
    """Eszköz-újrakötés: automatikusan (AutoFix záró köre) és kézzel (gomb)."""

    # ------------------------------------------------------------------
    # KÖZÖS MAG - ezt hívja az AutoFix regresszió-javítója ÉS a kézi gomb is
    # ------------------------------------------------------------------
    def _rebind_device(self, pnp, inf_path, dev_name, dev_class, task_id):
        """Egy eszköz visszakötése a stage-elt gyári driverre. Visszatérés: sikerült-e.

        Két lépcső, és a MÁSODIK az, ami terepen ténylegesen megjavította a tapipadot:
          1) a csomag újratelepítése (`pnputil /add-driver ... /install`) - ez önmagában
             sokszor NEM vált kötést, mert a Windows a meglévő drivert elég jónak látja;
          2) az eszköz ÚJRAENUMERÁLÁSA (`/remove-device` + `/scan-devices`) - ez választat
             drivert nulláról, pontosan úgy, mintha ki-be dugnánk az eszközt.

        A tárolóvezérlőket/lemezeket SOSEM enumeráljuk újra: ott a csomópont pillanatnyi
        eltűnése a futó rendszert viheti el. Beviteli/egyéb eszköznél ez ártalmatlan."""
        if inf_path:
            logging.info(f"[REBIND] 1. lépés - újratelepítés: {dev_name} <- {inf_path}")
            self._run(['pnputil', '/add-driver', inf_path, '/install'],
                      timeout=600, ok_codes=(0, 259, 3010))
            self._run(['pnputil', '/scan-devices'], timeout=300)
            if self._device_on_vendor_driver(pnp):
                logging.warning(f"[REBIND] SIKER (újratelepítéssel): {dev_name}")
                return True

        cls = (dev_class or '').strip().upper()
        if cls in STORAGE_RISK_CLASSES or cls in FIRMWARE_RISK_CLASSES:
            logging.info(f"[REBIND] {dev_name} [{cls}]: tároló/firmware - újraenumerálás KIHAGYVA "
                         f"(a csomópont eltűnése a futó rendszert vinné).")
            return False

        logging.warning(f"[REBIND] 2. lépés - eszköz újraenumerálása: {dev_name} [{pnp}]")
        self.emit('task_progress', {'task': task_id, 'log': f'   🔄 {dev_name}: újraenumerálás (mintha ki-be dugnánk)...'})
        rem = self._run(['pnputil', '/remove-device', pnp], timeout=300, ok_codes=(0, 1, 3010))
        if getattr(rem, 'returncode', 1) not in (0, 3010):
            # A /remove-device csak Win10 1903-tól létezik; régebbin a letiltás/
            # engedélyezés páros ugyanezt a hatást éri el.
            logging.info(f"[REBIND] A /remove-device nem elérhető (rc={getattr(rem, 'returncode', '?')}) "
                         f"- letiltás/engedélyezés jön.")
            ps = (f"$id='{_ps_quote(pnp)}'; "
                  "Disable-PnpDevice -InstanceId $id -Confirm:$false -EA SilentlyContinue; "
                  "Start-Sleep -Seconds 3; "
                  "Enable-PnpDevice -InstanceId $id -Confirm:$false -EA SilentlyContinue")
            self._run(["powershell", "-NoProfile", "-Command", ps], timeout=300)
        self._run(['pnputil', '/scan-devices'], timeout=300)
        time.sleep(REBIND_SETTLE_SECONDS)
        ok = self._device_on_vendor_driver(pnp)
        logging.warning(f"[REBIND] {'SIKER' if ok else 'NEM SIKERÜLT'} (újraenumerálással): {dev_name}")
        return ok

    def _device_on_vendor_driver(self, pnp):
        """Gyári (nem Windows-alap) driveren fut-e most az eszköz?"""
        info = (self._get_installed_driver_info() or {}).get(pnp) or {}
        return bool(info) and not _is_inbox_driver(info)

    def _staged_vendor_inf_for(self, dev, third_party):
        """Van-e a DriverStore-ban olyan STAGE-ELT gyári csomag, ami EZT az eszközt állítja?

        Miért az INF-ekből dolgozunk: a `pnputil` nem mondja meg, melyik stage-elt csomag
        melyik hardverre való. A csomag INF-jei viszont felsorolják a hardver-azonosítóikat,
        és a gép harmadik féltől származó csomagjainak listája már megvan (dism), tehát a
        keresés a néhány tucat GYÁRI csomagra korlátozódik - nem a teljes DriverStore-ra."""
        hwids = [h for h in (dev.get('all_hwids') or []) if h]
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
                for hw in hwids:
                    if _hwid_matches(inf_id, hw):
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

                # Csak az alapdriveres eszközök érdekesek - ami gyárin fut, azzal nincs dolgunk.
                candidates = []
                for d in devices:
                    info = inst.get(d.get('pnp_id') or '')
                    if not info or not _is_inbox_driver(info):
                        continue
                    cls = (d.get('pclass') or '').strip().upper()
                    if cls in STORAGE_RISK_CLASSES or cls in FIRMWARE_RISK_CLASSES:
                        continue          # ezekhez nem nyúlunk (lásd _rebind_device)
                    candidates.append((d, info))
                logging.info(f"[REBIND] {len(candidates)} eszköz fut alapdriveren (a tároló/firmware nélkül).")

                todo = []
                for d, info in candidates:
                    checked += 1
                    path, orig = self._staged_vendor_inf_for(d, third_party)
                    if path:
                        todo.append((d, info, path, orig))
                if not todo:
                    self.emit('task_progress', {'task': task, 'log': '\n✅ Nincs olyan eszköz, ami alapdriveren futna, pedig van hozzá gyári csomag a gépen.'})
                    self.emit('task_progress', {'task': task, 'log': 'Ha valamelyik eszköz mégis rosszul működik, ahhoz a gépen NINCS gyári driver - a "Driver Keresés és Telepítés" menüben kerestethetsz hozzá.'})
                    self.emit('task_complete', {'task': task, 'status': 'Nincs javítanivaló'})
                    return

                self.emit('task_progress', {'task': task, 'log': f'\n🔧 {len(todo)} eszközhöz VAN gyári driver a gépen, mégis alapdriveren fut - visszakötés:'})
                for i, (d, info, path, orig) in enumerate(todo, 1):
                    if self._cancel_flag:
                        break
                    name = d.get('name') or d.get('pnp_id')
                    self.emit('task_progress', {'task': task, 'log': f'\n({i}/{len(todo)}) {name}\n   most: {info.get("inf")} ({info.get("provider")}) → gyári: {orig}',
                                                'current': i, 'total': len(todo)})
                    if self._rebind_device(d.get('pnp_id'), path, name, d.get('pclass'), task):
                        fixed += 1
                        after = (self._get_installed_driver_info() or {}).get(d.get('pnp_id')) or {}
                        self.emit('task_progress', {'task': task, 'log': f'   ✅ Sikerült - most a gyári driveren fut ({after.get("inf")}).'})
                    else:
                        failed.append(name)
                        self.emit('task_progress', {'task': task, 'log': '   ❌ Nem sikerült - az eszköz a Windows alapdriverén marad.'})

                self.emit('task_progress', {'task': task, 'log': f'\n📊 Kész: {fixed} eszköz visszakötve a gyári driverre.'})
                if failed:
                    self.emit('task_progress', {'task': task, 'log': f'⚠️ {len(failed)} eszközt nem sikerült: {", ".join(failed[:6])}'})
                    self.emit('task_progress', {'task': task, 'log': '👉 Ezekhez a gyártó letöltőoldaláról telepíts drivert kézzel.'})
                self.emit('task_complete', {'task': task, 'status': f'✅ {fixed} eszköz javítva'})
            except Exception as e:
                logging.error(f"[REBIND] Hiba a kézi újrakötésben: {e}", exc_info=True)
                self.emit('task_error', {'task': task, 'error': str(e)})

        self._safe_thread('rebind', worker)
