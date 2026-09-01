"""DriverVarázsló GUI - GYÁRTÓI (OEM) KATALÓGUS: a negyedik driver-forrás.

A DriverToolApi része (összerakás: app/gui/api.py). A nem-UI logika az
app/oemcatalog_core.py-ban van (a `_core` konvenció szerint), itt csak a letöltés,
a telepítés és a felület felé menő jelentés van.

MIÉRT LÉTEZIK: lásd az app/oemcatalog_core.py fejlécét - röviden: van olyan gyári driver,
amit sem a WU Agent, sem a Microsoft Update Catalog nem szállít, mert a gépgyártó a saját
csatornáján adja. Ez a kör onnan szerzi meg, NULLÁRÓL letöltve - nem a gép régi driverét
teszi vissza (az tiltott, lásd CLAUDE.md "re-driver from ZERO").

HOL A HELYE A SORBAN: a WU és a Microsoft-katalógus UTÁN, a lánc záró körében. Így csak
arra fut, amit a többi forrás nem oldott meg, és nem ír felül frissebb drivert.
"""
import os
import time
import shutil
import logging
import tempfile

from app import oemcatalog_core
from app.common import download_with_cert_fallback
from app.wu_core import inf_package_applies
from app.wu_core import package_bound_to_device_family
from app.wu_core import _is_inbox_driver
from app.wu_core import release_rank

# Egy csomag letöltésének felső korlátja. A gyári driver packek nagyok (Dellnél több száz
# MB), de a felhasználó a futásidőt vállalja - a hibás eredményt nem.
OEM_DOWNLOAD_TIMEOUT = 1800


class GuiOemCatalogMixin:
    """Gyártói katalógus-kör: gépazonosítás -> csomaglista -> illesztés -> telepítés."""

    def _oem_catalog_round(self, devices, task_id='autofix'):
        """A gyártói katalógus-kör. Visszatérés: (telepített, kihagyott) darabszám.

        SOHA nem dob kivételt kifelé: ez egy KIEGÉSZÍTŐ forrás, a hibája nem akaszthatja
        meg a láncot. Ha a géphez nincs gyártói katalógus (Acer, összerakott PC), a kör
        üresen tér vissza - az nem hiba, a többi forrás akkor is lefutott."""
        installed = skipped = 0
        workdir = None
        try:
            self.emit('task_progress', {'task': task_id, 'log': '\n🏭 GYÁRTÓI KATALÓGUS: a gépgyártó saját driver-csomagjainak keresése...', 'indeterminate': True})
            machine = oemcatalog_core.detect_machine(self._run)
            if not machine.get('vendor'):
                # Ezt KI KELL MONDANI: különben a technikus azt hiszi, a kör lefutott és
                # nem talált semmit, holott el sem indult - és a két állapot mást jelent.
                self.emit('task_progress', {'task': task_id, 'log': f'ℹ️ Ehhez a géphez ({machine.get("manufacturer") or "ismeretlen gyártó"} {machine.get("model") or ""}) nincs gépi olvasható gyártói katalógus - a Windows Update és a Microsoft Update Catalog természetesen lefutott rá.'})
                return 0, 0

            packages = oemcatalog_core.find_oem_packages(
                machine, self._run,
                lambda m: self.emit('task_progress', {'task': task_id, 'log': m}))
            if not packages:
                self.emit('task_progress', {'task': task_id, 'log': 'ℹ️ A gyártói katalógus nem adott csomagot ehhez a modellhez.'})
                return 0, 0

            # A firmware-jelölőnégyzet IDE IS érvényes: a gyártói katalógus tele van
            # firmware-villantó eszközökkel (BIOS, Thunderbolt, SSD, dokkoló), és ezek
            # felügyelet nélküli futtatása visszafordíthatatlan. Alapból KI.
            allow_fw = bool(getattr(self, '_autofix_allow_firmware', False))
            matched = oemcatalog_core.match_packages_to_devices(packages, devices,
                                                               allow_firmware=allow_fw)
            if not matched:
                self.emit('task_progress', {'task': task_id, 'log': f'ℹ️ A gyártói katalógus {len(packages)} csomagja közül egyik sem tartozik a gép jelen lévő eszközeihez.'})
                return 0, 0

            # EGY LÁNCON BELÜL EGY GYÁRTÓI CSOMAGOT CSAK EGYSZER (`oem_done`).
            #
            # Terepen bizonyítva (HP EliteDesk 800 G1, Build 277, 2026-08-26): a
            # `HP driver pack sp92706` MINDEN LÁBON újra letöltődött és felment - 16:14,
            # 16:21, 16:26, 16:31 -, körönként ~7 percet elvéve, mire a technikus
            # megszakította a láncot. A katalógus-kör ugyanezt a hibát már megkapta és
            # javítottuk (`catalog_done`), a gyártói kör viszont védelem nélkül maradt.
            #
            # Miért nem fogta meg az `_oem_already_current`: a TELJES GÉPRE szóló driver
            # packnél nincs konkrét eszköz (`dev is None`), ezért az a függvény eleve
            # `False`-t ad ("telepítsd") - és a pack verziója sem köthető egyetlen eszköz
            # driververziójához. Vagyis a packet semmi nem tudta "már naprakész"-nek látni.
            #
            # Biztonságos: egy láncon belül ugyanannak a csomagnak az újratelepítése
            # definíció szerint fölösleges. A lista a lánc-állapotban él, tehát a stats-fájl
            # törlésekor (lánc eleje/vége) elévül - egy KÉSŐBBI fix újra megpróbálja.
            done = self._autofix_stats_get('oem_done') or []
            done_ids = {str(d) for d in done}
            inst_info = self._get_installed_driver_info()
            todo = []
            for pkg, dev in matched:
                key = f"{pkg.get('vendor', '')}|{pkg.get('id', '')}|{(dev or {}).get('pnp_id', '')}"
                if key in done_ids:
                    skipped += 1
                    logging.info(f"[OEM] Kihagyva (ebben a láncban már próbáltuk): {pkg.get('title')}")
                    continue
                if self._oem_already_current(pkg, dev, inst_info):
                    skipped += 1
                    continue
                todo.append((pkg, dev, key))
            self.emit('task_progress', {'task': task_id, 'log': f'🏭 {len(todo)} gyári csomag telepítendő (a katalógus {len(packages)} csomagjából; {skipped} kihagyva/naprakész).'})
            if not todo:
                return 0, skipped

            # A MEGKÍSÉRELT csomagok MÉG A TELEPÍTÉS ELŐTT bekerülnek a listába: egy
            # összeomlás vagy újraindítás a telepítés közben így sem indítja újra ugyanazt a
            # több száz MB-os letöltést a következő lábon.
            self._autofix_stats_set('oem_done', done + [k for _p, _d, k in todo])
            logging.info(f"[OEM] {len(todo)} csomag megjelölve 'ebben a láncban már próbáltuk'-ként: "
                         f"{[p.get('title') for p, _d, _k in todo][:6]}")

            workdir = tempfile.mkdtemp(prefix='dv_oem_')
            for i, (pkg, dev, _key) in enumerate(todo, 1):
                if self._cancel_flag:
                    logging.warning("[OEM] Felhasználói megszakítás a gyártói körben.")
                    break
                ok = self._oem_install_package(pkg, dev, workdir, i, len(todo), task_id)
                if ok:
                    installed += 1
                else:
                    skipped += 1
            if installed:
                self._run(['pnputil', '/scan-devices'], timeout=300)
            self.emit('task_progress', {'task': task_id, 'log': f'🏭 Gyártói katalógus kész: {installed} csomag telepítve, {skipped} kihagyva.'})
        except Exception as e:
            logging.warning(f"[OEM] A gyártói katalógus-kör hibára futott (nem kritikus): {e}", exc_info=True)
            self.emit('task_progress', {'task': task_id, 'log': 'ℹ️ A gyártói katalógus lekérdezése nem sikerült - a többi forrás eredménye érvényes.'})
        finally:
            if workdir:
                shutil.rmtree(workdir, ignore_errors=True)
        return installed, skipped

    def _oem_already_current(self, pkg, dev, inst_info):
        """Naprakész-e már az eszköz? Csak akkor hagyjuk ki, ha BIZONYÍTHATÓAN az.

        Két feltétel EGYÜTT: az eszköz gyári (nem Windows-alap) driveren fut, ÉS a
        telepített kiadás nem régebbi a katalógusénál. Az inbox driver sosem számít
        naprakésznek - pont az a helyzet, amit ez a kör orvosol."""
        if not dev:
            return False                      # teljes driver pack: mindig felmegy
        info = (inst_info or {}).get(dev.get('pnp_id') or '') or {}
        if not info or _is_inbox_driver(info):
            return False
        cat_ver, inst_ver = pkg.get('version') or '', info.get('version') or ''
        if not cat_ver or not inst_ver:
            return False
        try:
            if release_rank('', inst_ver) >= release_rank('', cat_ver):
                logging.info(f"[OEM] Kihagyva (már naprakész): {pkg.get('title')} - "
                             f"telepített {inst_ver} >= katalógus {cat_ver} ({dev.get('name')})")
                return True
        except Exception as e:
            logging.debug(f"[OEM] Verzió-összevetés sikertelen ({pkg.get('title')}): {e}")
        return False

    def _oem_progress_cb(self, title, task_id):
        """Letöltés-haladás a fix naplójába, ~2 másodpercenként.

        SAJÁT callback, NEM a stressz-nézeté (`_stress_dl_progress_emitter`): az egy
        másik szignatúrájú, másik UI-eseményt kibocsátó függvény. Terepen (Build 272,
        T580) épp ez volt a hiba - a rossz hívás minden gyártói letöltést azonnal
        kivételre futtatott, így a kör mind az 5 lábon NULLA csomagot telepített,
        miközben a képernyőn csak annyi látszott, hogy "a letöltés nem sikerült".
        A gyári csomagok több száz MB-osak is lehetnek, ezért kell a visszajelzés.

        A SZIGNATÚRA `(done, total_bytes)`, MERT A HÍVÓ ÍGY HÍVJA - lásd
        `common.download_with_cert_fallback`: `progress_cb(done, total)`. A `_stress_dl_progress_emitter`
        hármas `(phase, done, total)` alakja EGY MÁSIK hívóé, és ide bemásolva néma hibát okoz:
        a `common.py` minden hívást try/except-be zár, tehát a letöltés nem bukik el - csak
        soha nem jelenik meg semmi. MÉRVE (2026-09-01, Dell Latitude 5580, Build 288): a
        11 perc 33 mp-es Dell-letöltés alatt EGYETLEN karakter sem jelent meg a képernyőn,
        és a naplóba **3936** azonos hibasor került (a fájl ~19%-a), kiszorítva a valódi
        előzményt. Ha ez a szignatúra változik, a hívó oldalt kell vele együtt módosítani."""
        state = {'last': 0.0}

        def cb(done, total_bytes):
            now = time.monotonic()
            is_final = bool(total_bytes) and done >= total_bytes
            if now - state['last'] < 2.0 and not is_final:
                return
            state['last'] = now
            if total_bytes:
                pct = int(done * 100 / total_bytes)
                txt = f'   ⬇️ {title}: {done / 1048576:.0f}/{total_bytes / 1048576:.0f} MB ({pct}%)'
            else:
                txt = f'   ⬇️ {title}: {done / 1048576:.0f} MB'
            self.emit('task_progress', {'task': task_id, 'log': txt})

        return cb

    def _oem_install_package(self, pkg, dev, workdir, idx, total, task_id):
        """Egy gyártói csomag: letöltés -> kicsomagolás -> pnputil telepítés -> ellenőrzés."""
        title = pkg.get('title') or pkg.get('id') or '?'
        dev_name = (dev or {}).get('name') or 'teljes gépre szóló csomag'
        self.emit('task_progress', {'task': task_id, 'log': f'⬇️ ({idx}/{total}) {title} → {dev_name}', 'current': idx, 'total': total})
        logging.info(f"[OEM] Telepítés indul: '{title}' v={pkg.get('version')} "
                     f"[{pkg.get('category')}] url={pkg.get('url')} eszköz={dev_name}")

        exe = os.path.join(workdir, f"oem_{idx}_" + os.path.basename(pkg.get('url') or 'pkg.exe'))
        try:
            ok = download_with_cert_fallback(
                self._run, pkg['url'], exe, timeout=OEM_DOWNLOAD_TIMEOUT,
                log_tag='OEM', progress_cb=self._oem_progress_cb(title, task_id))
        except Exception as e:
            logging.warning(f"[OEM] Letöltés sikertelen ({title}): {e}", exc_info=True)
            ok = False
        if not ok or not os.path.isfile(exe) or os.path.getsize(exe) < 1024:
            self.emit('task_progress', {'task': task_id, 'log': f'   ⚠️ A letöltés nem sikerült - kihagyva: {title}'})
            return False

        ext = os.path.join(workdir, f"ext_{idx}")
        got = oemcatalog_core.extract_vendor_package(
            self._run, exe, ext, pkg.get('extract_cmd') or '',
            lambda m: self.emit('task_progress', {'task': task_id, 'log': '   ' + m}))
        if not got:
            return False

        # JÓZANSÁGI ELLENŐRZÉS (nem vétó): ha az eszköz azonosítója nincs az INF-ekben, az
        # ÖNMAGÁBAN nem ok a kihagyásra - a gyártó a katalógusban deklarálta, hogy ez a
        # csomag ehhez az eszközhöz való, és mérve (T580 UltraNav) az INF más azonosítókat
        # sorol fel, mint amin az eszköz megjelenik. Ezért csak naplózunk.
        if dev:
            verdict = inf_package_applies(got, dev.get('all_hwids') or [])
            logging.info(f"[OEM] INF-józansági próba: {verdict!r} ({title} / {dev_name}) "
                         f"- a döntés a katalógus deklarációján alapul, ez csak napló.")

        res = self._run(['pnputil', '/add-driver', os.path.join(got, '*.inf'),
                         '/subdirs', '/install'], timeout=900, ok_codes=(0, 259, 3010))
        out = (getattr(res, 'stdout', '') or '')
        rc = getattr(res, 'returncode', None)
        added = 'successfully' in out.lower() or rc in (0, 259, 3010)
        if not added:
            logging.warning(f"[OEM] A pnputil elutasította a csomagot (rc={rc}): {title}")
            self.emit('task_progress', {'task': task_id, 'log': f'   ⚠️ A telepítés nem sikerült: {title}'})
            return False

        # KÖTÉS-ELLENŐRZÉS: a "sikeresen hozzáadva" nem azonos azzal, hogy az eszköz át is
        # vette (ugyanaz a csapda, mint a Microsoft-katalógusnál). 3010 esetén a kötés
        # jogosan a következő indításkor történik meg.
        reboot = (rc == 3010) or ('reboot' in out.lower())
        if dev and not reboot:
            if package_bound_to_device_family(out, dev):
                self.emit('task_progress', {'task': task_id, 'log': f'   ✅ Telepítve és aktív: {title}'})
            else:
                self.emit('task_progress', {'task': task_id, 'log': f'   ✅ Telepítve: {title} (az eszköz a következő indítás után veszi át)'})
                logging.info(f"[OEM] A csomag felment, de a kötés most nem igazolható: {title}")
        else:
            self.emit('task_progress', {'task': task_id, 'log': f'   ✅ Telepítve: {title}'})

        # A több-INF-es csomagok fel nem használt INF-jeinek kivezetése - ugyanaz a
        # DriverStore-hízás elleni védelem, mint a Microsoft-katalógusnál (a gyári packek
        # kifejezetten sok INF-et hoznak).
        try:
            if hasattr(self, '_cleanup_unused_staged_infs'):
                self._cleanup_unused_staged_infs(out, title, task_id, defer=reboot)
        except Exception as e:
            logging.debug(f"[OEM] A nem használt INF-ek kivezetése nem sikerült: {e}")
        return True
