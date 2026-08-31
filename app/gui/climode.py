"""DriverVarázsló GUI - átváltás CLI módba (a felső sáv kapcsolója).

MIÉRT (explicit user decision, 2026-08-29): a bolt régi gépein a grafikus felület
használhatatlanul lassú, a CLI viszont mindenhol elindul. A technikusnak ezért kell egy
kapcsoló, amivel a program ÚJRAINDUL szöveges módban - ne kelljen parancssorból,
`--cli` kapcsolóval kézzel indítania.

MIÉRT ÚJ FOLYAMAT ÉS NEM "átrajzolás": a CLI-nek saját konzolablak kell (a windowed exe-nek
alapból nincs `sys.stdout`-ja, lásd common.ensure_console), a futó WebView2-ablakot pedig
nem lehet konzollá alakítani. Egy új példány indítása `--cli`-vel az egyetlen tiszta út,
és egyben azt is garantálja, hogy a nehéz WebView2 réteg TÉNYLEG kikerül a képből - a
mostani folyamat kilép.
"""

# === AUTO-IMPORTS ===
import os
import sys
import logging
import subprocess

from app.common import _app_exe_path
from app.common import acquire_app_mutex
from app.common import release_app_mutex
# === /AUTO-IMPORTS ===


class GuiCliModeMixin:
    """A felső sáv "CLI mód" kapcsolója. A DriverToolApi része (összerakás: app/gui/api.py)."""

    def switch_to_cli_mode(self):
        """Újraindítja a programot szöveges (CLI) módban, saját konzolablakban.

        A futó grafikus példány ezután kilép - két példány egyszerre amúgy sem futhat (a
        program egypéldányos mutexet használ), és a felhasználó szándéka egyértelmű."""
        logging.info("[API] switch_to_cli_mode() - átváltás CLI módra")
        exe = _app_exe_path()

        # AZ EGYPÉLDÁNYOS MUTEXET EL KELL ENGEDNI AZ INDÍTÁS ELŐTT. E nélkül az új
        # folyamat azonnal kilép a "A DriverVarázsló már fut a rendszeren!" üzenettel -
        # a mostani (grafikus) példány ugyanis még fogja a mutexet, és csak másodpercekkel
        # később lép ki. Terepen pontosan ez történt (2026-08-29).
        released = release_app_mutex()

        try:
            # A `cmd /c start` KÖZBEIKTATÁSA NEM KÖRÜLMÉNYESKEDÉS, HANEM KÖTELEZŐ.
            # A kilépésünk `cleanup_zombies()`-on át megy, ami `taskkill /F /T /PID <self>`
            # - vagyis a TELJES folyamatfát kilövi (ez a lógó dism/pnputil folyamatok miatt
            # van így). Egy közvetlenül indított gyerek ennek a fának a része lenne, tehát
            # az új CLI ablakot a saját kilépésünk ölné meg pár másodperccel az indítás
            # után. A `start` viszont maga indítja el a folyamatot, majd a `cmd` azonnal
            # kilép - mire a taskkill lefut, a CLI szülője már halott, így nem tartozik a
            # fánkba. Az üres "" a start ELSŐ paramétere: az az ablakcím, enélkül az
            # idézőjeles útvonalat venné annak, és nem indítana semmit.
            if getattr(sys, 'frozen', False):
                inner = f'start "" "{exe}" --cli'
            else:
                # Forrásból futtatva a Python értelmezőn keresztül.
                inner = f'start "" "{sys.executable}" "{exe}" --cli'
            # A PARANCSOT SZTRINGKÉNT ADJUK ÁT, NEM LISTAKÉNT. Listával a Python
            # `list2cmdline`-ja visszaperjelezi a belső idézőjeleket (`start \"\" \"C:\...\"`),
            # a `cmd` pedig a `\"` -t útvonal-kezdetnek veszi -> `\\` -> a felhasználó
            # "A hálózati elérési út nem található" hibát kap (terepen pontosan ez történt,
            # 2026-08-29; a hibaablak CÍME is `\\` volt). Sztringként a Windows a
            # CreateProcess-nek szó szerint adja tovább, tehát pont az megy ki, amit írunk.
            cmd = f'cmd /c {inner}'
            # DETACHED_PROCESS ÉS NEM CREATE_NO_WINDOW (2026-08-31, terepi hiba).
            # A `CREATE_NO_WINDOW` nem "konzol nélkül" indít, hanem konzollal, csak
            # ELREJTVE. A segéd-`cmd` így kapott egy rejtett konzolt, amit a `start`-tal
            # indított exe MEGÖRÖKÖLT - a `--cli` ág `AttachConsole(-1)`-e ezért SIKERRel
            # járt, a `sys.stdout` egy valódi (cp852-es, tty) streamre került... ami a
            # REJTETT konzolra írt. A napló pontosan ezt mutatta: `ANSI=True`,
            # `Unicode=False`, a menü lefutott - a felhasználó viszont üres fekete ablakot
            # látott. A `DETACHED_PROCESS` egyáltalán nem ad konzolt, így nincs mit
            # örökölni: az `AttachConsole` elbukik, és a program SAJÁT, LÁTHATÓ konzolt
            # nyit (`ensure_console`).
            logging.info(f"[CLI-MODE] Indítás (DETACHED_PROCESS): {cmd}")
            subprocess.Popen(cmd, creationflags=subprocess.DETACHED_PROCESS,
                             cwd=os.path.dirname(exe) or None,
                             close_fds=True)
        except Exception as e:
            # Az indítás elhasalt: a mutexet VISSZA KELL VENNI, különben ez a példány
            # mutex nélkül futna tovább, és a program bárhányszor elindítható lenne.
            if released:
                acquire_app_mutex()
            logging.error(f"[CLI-MODE] A CLI mód indítása nem sikerült: {e}", exc_info=True)
            self.emit('toast', {'message': f'❌ A CLI mód indítása nem sikerült: {e}',
                                'type': 'error'})
            return {'success': False, 'error': str(e)}

        # A jelenlegi (grafikus) példány kilép. A kilépés a szokásos úton megy: a
        # cleanup_zombies + os._exit párost a belépési pont végzi, ezért itt csak
        # jelezzük a felületnek, hogy záródik - a tényleges kilépést a JS kéri.
        self.emit('toast', {'message': '🖥️ CLI mód indul egy új ablakban...', 'type': 'success'})
        return {'success': True}

    def exit_app(self):
        """A program azonnali lezárása (a CLI-re váltás után hívja a felület).

        `os._exit(0)`, mert a WebView2 szál és a daemon-szálak nem mindig bomlanak le
        rendesen (lásd CLAUDE.md "Process model").

        SZÁNDÉKOSAN NINCS `taskkill /T` (folyamatfa-kilövés), amit a belépési pont
        `cleanup_zombies()`-a használ: itt épp azért lépünk ki, hogy egy MÁSIK folyamat
        (a CLI ablak) átvegye a munkát. Igaz, hogy a `cmd /c start` miatt az már nem is
        tartozik a fánkba, de két, egymásra épülő védelem közül az egyiket sem érdemes
        feleslegesen kockáztatni - a fa-kilövés itt nem old meg semmit, viszont el tudná
        vinni az imént indított ablakot."""
        logging.info("[API] exit_app() - kilépés (CLI módra váltás után)")
        try:
            logging.shutdown()
        except Exception:
            pass
        # `taskkill /F` A SAJÁT PID-RE, DE **/T NÉLKÜL**. A `/T` a folyamatfát vinné, abban
        # pedig benne lenne az imént indított CLI ablak. A sima `/F` viszont kell: nélküle
        # (csak `os._exit`) a PyInstaller bootloadere megpróbálja törölni a `_MEIxxxxx` temp
        # mappát, ami a még betöltött DLL-ek miatt nem sikerül, és a felhasználó egy
        # "Failed to remove temporary directory" figyelmeztetést kap - terepen pontosan ez
        # jelent meg (2026-08-31). A program minden más kilépési pontja is így, azonnali
        # kilövéssel zárul (lásd CLAUDE.md "Process model").
        try:
            subprocess.run(['taskkill', '/F', '/PID', str(os.getpid())],
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
        except Exception as e:
            logging.debug(f"[CLI-MODE] taskkill nem futott le: {e}")
        os._exit(0)
