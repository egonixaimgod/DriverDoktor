"""DriverVarázsló GUI - Windows & Office nézet: aktiválási állapot, gyári kulcs, aktiválás.

MIT OLD MEG A SZERVIZBEN: újratelepítés után a leggyakoribb kérdés, hogy "miért nem
aktivált magától" - a válasz szinte mindig a licenc CSATORNÁJÁBAN van (OEM/Retail/Volume),
és OEM gépnél a kulcs ott van a UEFI MSDM táblájában, csak ki kell olvasni. Ez a nézet
ezeket egy képernyőn megmutatja, és egy gombbal el is végzi az aktiválást.

NINCS BEÍRANDÓ MEZŐ - EGY GOMB, ÉS VÉGIGMEGY (explicit user decision, 2026-08-28:
"ne legyen ures mezo, ne kelljen mezokbe irkalni, ha ranyomok menjen vegig"). A program
magától eldönti, mit használ:
  - VAN gyári kulcs a BIOS-ban -> AZT (és KMS-kiszolgáló nem kell hozzá),
  - NINCS -> a kiadáshoz tartozó nyilvános GVLK + a `winact_core.KMS_HOST` konstans.
A KMS-kiszolgáló címe tehát a FORRÁSBAN van (app/winact_core.py tetején), nem a felületen.

A SIKERT MINDIG A WMI MONDJA MEG, nem az slmgr kimenete - lásd app/winact_core.py fejléc.
"""

# === AUTO-IMPORTS ===
import logging

from app import winact_core
# === /AUTO-IMPORTS ===


class GuiWinActMixin:
    """Windows & Office nézet: aktiválási állapot és aktiválás.
    A DriverToolApi része (összerakás: app/gui/api.py)."""

    # ---------------------------------------------------------------- állapot
    def get_activation_status(self):
        """A teljes aktiválási kép (Windows + Office). Szinkron: két WMI-lekérdezés."""
        logging.info("[API] get_activation_status()")
        if self.target_os_path:
            return {'offline': True}
        try:
            win = winact_core.collect_windows_activation(self._run)
            office = winact_core.collect_office_activation(self._run)
            return {'offline': False, 'windows': win, 'office': office,
                    'plan': self._winact_plan(win),
                    'kms_note': winact_core.KMS_RENEWAL_NOTE}
        except Exception as e:
            logging.error(f"[WINACT] Az állapot lekérdezése hibára futott: {e}", exc_info=True)
            return {'offline': False, 'error': str(e)}

    def _winact_plan(self, win):
        """MIT FOG CSINÁLNI a gomb. A felület ezt kiírja, hogy a technikus a kattintás
        ELŐTT lássa - egy gomb, aminek a hatása nem látszik előre, a legrosszabb fajta."""
        kms = (winact_core.KMS_HOST or '').strip()
        if win.get('oem_key'):
            return {'source': 'oem', 'key': win['oem_key'], 'kms': '', 'ready': True,
                    'text': 'A gépbe égetett GYÁRI kulccsal aktivál (KMS-kiszolgáló nem kell).'}
        if not kms:
            return {'source': 'gvlk', 'key': win.get('gvlk', ''), 'kms': '', 'ready': False,
                    'text': ('Ezen a gépen NINCS gyári kulcs, KMS-kiszolgáló pedig nincs beállítva - '
                            'így nem lehet aktiválni. A címet az app/winact_core.py fájl tetején, '
                            'a KMS_HOST sorba kell beírni.')}
        return {'source': 'gvlk', 'key': win.get('gvlk', ''), 'kms': kms, 'ready': True,
                'text': f"Nincs gyári kulcs, ezért a(z) {win.get('gvlk_name')} kulccsal és a "
                        f"{kms} KMS-kiszolgálóval aktivál."}

    # ------------------------------------------------------------- aktiválás
    def activate_windows(self):
        """EGY KATTINTÁS: kulcs telepítése -> KMS-kiszolgáló (csak ha kell) -> aktiválás,
        majd ELLENŐRZÉS a WMI-ből. Nincs paramétere: a program magától dönt (lásd
        `_winact_plan` és a modul fejléce)."""
        if self.target_os_path:
            self.emit('toast', {'message': '❌ Offline módban nem elérhető!', 'type': 'error'})
            return

        def worker():
            task = 'winact'
            self.emit('task_start', {'task': task, 'title': 'Windows aktiválása'})
            try:
                before = winact_core.collect_windows_activation(self._run)
                self.emit('task_progress', {'task': task, 'log':
                          f"Kiadás: {before.get('edition') or 'ismeretlen'}\n"
                          f"Jelenlegi állapot: {before.get('status_text')}"})

                # KULCSVÁLASZTÁS. Ha a gépnek VAN gyári kulcsa a BIOS-ban, AZT használjuk:
                # a gépnek már van érvényes licence, és a GVLK ráhúzása lecserélné egy
                # KMS-kliens kulcsra, ami KMS-kiszolgáló nélkül nem is aktiválna - vagyis
                # egy működő licencből csinálnánk nem működőt. A GVLK a tartalék.
                plan = self._winact_plan(before)
                use_key, use_kms = plan['key'], plan['kms']

                if plan['source'] == 'oem':
                    self.emit('task_progress', {'task': task, 'log':
                              '🔑 Ezen a gépen GYÁRI kulcs van a BIOS-ban, ezért azt használjuk. '
                              'Ez a kulcs mindig működni fog, és KMS-kiszolgáló sem kell hozzá.'})
                elif not plan['ready']:
                    # Nem kezdünk bele: a GVLK felrakása KMS nélkül csak elrontaná a
                    # jelenlegi állapotot, aktiválni pedig úgysem tudna.
                    self.emit('task_progress', {'task': task, 'log': '❌ ' + plan['text']})
                    self.emit('task_complete', {'task': task, 'status': '❌ Nincs beállítva KMS-kiszolgáló'})
                    return
                else:
                    self.emit('task_progress', {'task': task, 'log':
                              f"ℹ️ Nincs gyári kulcs a BIOS-ban, ezért a kiadáshoz tartozó nyilvános "
                              f"KMS-kulcs (GVLK) megy fel: {before.get('gvlk_name')}"})

                # --- 1/3 kulcs telepítése
                self.emit('task_progress', {'task': task, 'log': f'\n1/3 - Termékkulcs telepítése: {use_key}'})
                ok, out = winact_core.install_product_key(self._run, use_key)
                self.emit('task_progress', {'task': task, 'log': f'   {out}'})
                if not ok:
                    self.emit('task_progress', {'task': task, 'log':
                              '❌ A kulcs telepítése nem sikerült - az aktiválás nem folytatható.'})
                    self.emit('task_complete', {'task': task, 'status': '❌ A kulcs telepítése sikertelen'})
                    self.emit('activation_status', self.get_activation_status())
                    return

                # --- 2/3 KMS-kiszolgáló (opcionális)
                if use_kms:
                    self.emit('task_progress', {'task': task, 'log': f'\n2/3 - KMS-kiszolgáló beállítása: {use_kms}'})
                    ok, out = winact_core.set_kms_host(self._run, use_kms)
                    self.emit('task_progress', {'task': task, 'log': f'   {out}'})
                    if not ok:
                        self.emit('task_progress', {'task': task, 'log':
                                  '❌ A KMS-kiszolgáló beállítása nem sikerült.'})
                        self.emit('task_complete', {'task': task, 'status': '❌ KMS-beállítás sikertelen'})
                        self.emit('activation_status', self.get_activation_status())
                        return
                else:
                    self.emit('task_progress', {'task': task, 'log':
                              '\n2/3 - KMS-kiszolgáló nem kell, ez a lépés kimarad '
                              '(az aktiválás a Microsoft felé megy).'})

                # --- 3/3 aktiválás
                self.emit('task_progress', {'task': task, 'log': '\n3/3 - Aktiválás...', 'indeterminate': True})
                ok, out = winact_core.activate(self._run)
                self.emit('task_progress', {'task': task, 'log': f'   {out}'})

                # --- ELLENŐRZÉS. Az slmgr kimenete lokalizált, ezért a WMI dönt.
                self.emit('task_progress', {'task': task, 'log': '\nEllenőrzés (a rendszer licenc-állapota)...'})
                after = winact_core.collect_windows_activation(self._run)
                self.emit('activation_status', self.get_activation_status())

                if after.get('activated'):
                    msg = '\n✅ KÉSZ - a Windows AKTIVÁLVA van.'
                    if use_kms:
                        msg += f"\nℹ️ {winact_core.KMS_RENEWAL_NOTE}"
                    self.emit('task_progress', {'task': task, 'log': msg})
                    self.emit('task_complete', {'task': task, 'status': '✅ A Windows aktiválva'})
                else:
                    # Nem hallgatjuk el: egy "lefutott, de nem aktivált" állapot a
                    # legrosszabb, amit a technikus utólag fedez fel az ügyfélnél.
                    self.emit('task_progress', {'task': task, 'log':
                              # A RÉSZLETES állapot, nem a jelvényé: az 5-ös kódnál a
                              # jelvény már "Aktiválva", és ez a sor ellentmondana neki.
                              f"\n❌ NEM sikerült - a rendszer licenc-állapota: "
                              f"{after.get('status_detail') or after.get('status_text')}\n"
                              + self._winact_hint(after, use_kms)})
                    self.emit('task_complete', {'task': task, 'status': '❌ Az aktiválás nem sikerült'})
            except Exception as e:
                logging.error(f"[WINACT] Az aktiválás hibára futott: {e}", exc_info=True)
                self.emit('task_progress', {'task': task, 'log': f'❌ Hiba: {e}'})
                self.emit('task_complete', {'task': task, 'status': '❌ Hiba'})

        self._safe_thread('winact', worker)

    def clear_kms_server(self):
        """A beállított KMS-kiszolgáló törlése (vissza a Microsoft alapértelmezettre)."""
        if self.target_os_path:
            self.emit('toast', {'message': '❌ Offline módban nem elérhető!', 'type': 'error'})
            return

        def worker():
            ok, out = winact_core.clear_kms_host(self._run)
            self.emit('toast', {'message': ('✅ A KMS-kiszolgáló törölve.' if ok
                                            else f'❌ Nem sikerült: {out}'),
                                'type': 'success' if ok else 'error'})
            self.emit('activation_status', self.get_activation_status())

        self._safe_thread('winact-ckms', worker)

    def open_activation_tool(self, which):
        """A Windows saját aktiválási felületei. A kulcsból LOOKUP van, nem futtatás -
        így a frontendről nem lehet tetszőleges programot elindíttatni."""
        tools = {
            'settings': ['cmd', '/c', 'start', '', 'ms-settings:activation'],
            'changekey': ['cmd', '/c', 'start', '', 'ms-settings:activation'],
            'phone': ['cmd', '/c', 'start', '', 'slui.exe', '4'],
            'troubleshoot': ['cmd', '/c', 'start', '', 'ms-settings:activation'],
        }
        cmd = tools.get(str(which or ''))
        if not cmd:
            logging.warning(f"[WINACT] Ismeretlen aktiválási eszköz: {which}")
            return {'success': False}
        try:
            self._run(cmd, timeout=30)
            return {'success': True}
        except Exception as e:
            logging.warning(f"[WINACT] Az eszköz indítása nem sikerült ({which}): {e}")
            return {'success': False, 'error': str(e)}

    # ------------------------------------------------------------ segédek
    def _winact_hint(self, state, kms_host):
        """Miért nem sikerült - a leggyakoribb okok, konkrét teendővel. Egy puszta
        hibakód a technikusnak semmit nem mond."""
        if kms_host:
            return ('Leggyakoribb ok: a KMS-kiszolgáló nem érhető el a hálózatról (tűzfal, '
                    'VPN, elgépelt név), vagy nem ad ki licencet erre a kiadásra.')
        if state.get('oem_key'):
            return ('Ezen a gépen VAN gyári kulcs a BIOS-ban, és azzal próbáltunk aktiválni. '
                    'Ha így sem megy, jellemzően nem a kulcshoz való kiadás van fenn '
                    '(pl. Home kulcs, de Pro telepítve), vagy nincs internet.')
        if 'retail' in (state.get('channel') or '').lower():
            return ('Retail licenc: ha a kulcs jó, de nem aktivál, jellemzően a gép '
                    'hardvere változott - a Beállítások > Aktiválás alatti hibaelhárító, '
                    'vagy a Microsoft-fiókhoz kötött digitális licenc a megoldás.')
        return ('Ellenőrizd az internetkapcsolatot és azt, hogy a kulcs a telepített '
                'kiadáshoz való (Home kulcs nem megy Pro-ra és fordítva).')
