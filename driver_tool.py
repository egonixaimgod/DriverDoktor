import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import ctypes
import sys
import os
import winreg
import re
from datetime import datetime
import threading
import logging
import time
import shutil

# Globális logolás beállítása, amely abba a mappába teszi a logot, ahonnan az exe-t futtatják
log_filename = os.path.join(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__), "driver_tool_debug.log")
logging.basicConfig(
    filename=log_filename, 
    level=logging.DEBUG, 
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    encoding='utf-8'
)
logging.info("==================================================")
logging.info("DRIVER TOOL ELINDITVA")
logging.info(f"Futtatasi konyvtar: {os.getcwd()}")
logging.info("==================================================")

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def resource_path(relative_path):
    """ Visszaadja az erőforrás abszolút útvonalát, kezeli a PyInstaller _MEIPASS mappáját """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class DriverCleanerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Third-Party Driver Kezelő és WU Letiltó")
        self.geometry("900x600")
        
        try:
            self.iconbitmap(resource_path("icon.ico"))
        except:
            pass
        
        self.create_widgets()
        self.refresh_drivers()

    def create_widgets(self):
        # Top Frame - Windows Update
        wu_frame = ttk.LabelFrame(self, text="Windows Update Driver Frissítések Beállításai", padding=10)
        wu_frame.pack(fill=tk.X, padx=10, pady=5)

        self.wu_status_lbl = ttk.Label(wu_frame, text="Állapot: Ismeretlen", font=("Arial", 10, "bold"))
        self.wu_status_lbl.pack(side=tk.LEFT, padx=10)

        disable_wu_btn = ttk.Button(wu_frame, text="WU Driver Letöltés LETILTÁSA", command=self.disable_wu_drivers)
        disable_wu_btn.pack(side=tk.LEFT, padx=5)

        enable_wu_btn = ttk.Button(wu_frame, text="WU Driver Letöltés ENGEDÉLYEZÉSE", command=self.enable_wu_drivers)
        enable_wu_btn.pack(side=tk.LEFT, padx=5)

        self.check_wu_status()

        # Middle Frame - Backup
        backup_frame = ttk.LabelFrame(self, text="Biztonsági Mentés (Driver Export és Visszaállítási Pont)", padding=10)
        backup_frame.pack(fill=tk.X, padx=10, pady=5)

        rp_btn = ttk.Button(backup_frame, text="Új Rendszer-visszaállítási Pont Készítése", command=self.create_restore_point)
        rp_btn.pack(side=tk.LEFT, padx=5)

        export_btn = ttk.Button(backup_frame, text="Összes Third-Party Driver Lementése (Exportálás)", command=self.backup_drivers)
        export_btn.pack(side=tk.LEFT, padx=5)

        restore_btn = ttk.Button(backup_frame, text="Lementett Driverek Visszaállítása (Automatikus Eszközfelismertetés)", command=self.restore_drivers)
        restore_btn.pack(side=tk.LEFT, padx=5)

        # Bottom Frame - Drivers
        drv_frame = ttk.LabelFrame(self, text="Telepített Harmadik Fél (Third-party) Driverek", padding=10)
        drv_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        columns = ("published", "original", "provider", "class", "version")
        self.tree = ttk.Treeview(drv_frame, columns=columns, show="headings", selectmode="extended")
        
        self.tree.heading("published", text="Közzétett Név (oem.inf)")
        self.tree.heading("original", text="Eredeti Név")
        self.tree.heading("provider", text="Gyártó")
        self.tree.heading("class", text="Eszközosztály")
        self.tree.heading("version", text="Verzió/Dátum")

        self.tree.column("published", width=120)
        self.tree.column("original", width=150)
        self.tree.column("provider", width=200)
        self.tree.column("class", width=150)
        self.tree.column("version", width=200)

        scrollbar = ttk.Scrollbar(drv_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Buttons under tree
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        refresh_btn = ttk.Button(btn_frame, text="Lista Frissítése", command=self.refresh_drivers)
        refresh_btn.pack(side=tk.LEFT, padx=5)

        select_all_btn = ttk.Button(btn_frame, text="Összes Kijelölése", command=self.select_all_drivers)
        select_all_btn.pack(side=tk.LEFT, padx=5)

        delete_btn = ttk.Button(btn_frame, text="Kiválasztott Driver(ek) TÖRLÉSE", command=self.delete_selected_drivers)
        delete_btn.pack(side=tk.RIGHT, padx=5)

    def get_third_party_drivers(self):
        try:
            # Hide console window
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            result = subprocess.run(['pnputil', '/enum-drivers'], capture_output=True, text=True, startupinfo=startupinfo, errors='replace')
            output = result.stdout
            
            drivers = []
            current_driver = {}
            
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    if current_driver:
                        drivers.append(current_driver)
                        current_driver = {}
                    continue
                
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip()
                    
                    if "Published Name" in key or "Közzétett név" in key:
                        current_driver["published"] = val
                    elif "Original Name" in key or "Eredeti név" in key:
                        current_driver["original"] = val
                    elif "Provider Name" in key or "Szolgáltató neve" in key:
                        current_driver["provider"] = val
                    elif "Class Name" in key or "Osztály neve" in key:
                        current_driver["class"] = val
                    elif "Driver Version" in key or "Illesztőprogram verziója" in key:
                        current_driver["version"] = val

            if current_driver:
                drivers.append(current_driver)
                
            return drivers
        except Exception as e:
            messagebox.showerror("Hiba", f"Nem sikerült lekérdezni a drivereket:\n{str(e)}")
            return []

    def refresh_drivers(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        drivers = self.get_third_party_drivers()
        for d in drivers:
            if "published" in d:
                self.tree.insert("", tk.END, values=(
                    d.get("published", ""),
                    d.get("original", ""),
                    d.get("provider", ""),
                    d.get("class", ""),
                    d.get("version", "")
                ))

    def select_all_drivers(self):
        for item in self.tree.get_children():
            self.tree.selection_add(item)

    def delete_selected_drivers(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Figyelmeztetés", "Kérlek, válassz ki legalább egy drivert a törléshez!")
            return
            
        if not messagebox.askyesno("Megerősítés", f"Biztosan törölni szeretnéd a kiválasztott {len(selected)} drivert és az eszközökről is eltávolítod?"):
            return
            
        prog_win = tk.Toplevel(self)
        prog_win.title("Törlés folyamatban...")
        prog_win.geometry("450x150")
        prog_win.transient(self)
        prog_win.grab_set()

        lbl = ttk.Label(prog_win, text=f"{len(selected)} driver végleges eltávolítása folyamatban...\nKérlek várj!", justify=tk.CENTER)
        lbl.pack(pady=10)

        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=350, mode='determinate')
        progress.pack(pady=10)
        progress.config(maximum=len(selected))
        
        status_lbl = ttk.Label(prog_win, text="Inicializálás...", font=("Arial", 8))
        status_lbl.pack(pady=5)

        items_to_delete = [self.tree.item(item, "values")[0] for item in selected]

        def worker():
            success_count = 0
            fail_count = 0
            
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            logging.info(f"Kijelolt driverek torlese indult ({len(items_to_delete)} db)")
            for i, published_name in enumerate(items_to_delete):
                def update_status(txt=f"{published_name} törlése ({i+1}/{len(items_to_delete)})...", val=i):
                    status_lbl.config(text=txt)
                    progress['value'] = val
                self.after(0, update_status)
                
                try:
                    res = subprocess.run(['pnputil', '/delete-driver', published_name, '/uninstall', '/force'], 
                                       capture_output=True, text=True, startupinfo=startupinfo, errors='replace')
                    if res.returncode == 0 or "Deleted" in res.stdout or "törölve" in res.stdout:
                        success_count += 1
                        logging.info(f"SIKER: {published_name} torolve. Kimenet: {res.stdout.strip()}")
                    else:
                        fail_count += 1
                        logging.error(f"HIBA: {published_name} torlesekor. Return code: {res.returncode}. Kimenet: {res.stdout.strip()}")
                        print(f"Hiba a {published_name} törlésekor: {res.stdout}")
                except Exception as e:
                    fail_count += 1
                    logging.exception(f"Kivétel a {published_name} torlese kozben: {e}")
                    print(f"Kivétel a {published_name} törlésekor: {e}")

            logging.info(f"Torles befejezve. Sikeres: {success_count}, Sikertelen: {fail_count}")

            def finish_delete():
                if prog_win.winfo_exists():
                    prog_win.destroy()
                messagebox.showinfo("Eredmény", f"Sikeresen törölve: {success_count}\nNem sikerült: {fail_count}\n\nMost a program újraellenőrzi a hardvereket a gyári illesztők betöltéséhez.")
                
                # Második lépés: indítsunk egy új ablakot a scan-devices-hoz!
                self._run_hardware_scan_window()

            self.after(0, finish_delete)

        threading.Thread(target=worker, daemon=True).start()

    def _run_hardware_scan_window(self):
        scan_win = tk.Toplevel(self)
        scan_win.title("Hardverek ellenőrzése...")
        scan_win.geometry("450x150")
        scan_win.transient(self)
        scan_win.grab_set()

        lbl = ttk.Label(scan_win, text="Hiányzó Windows alapértelmezett driverek scannelése...\nEzután mennie kell a Touchpadnek alap driverekkel is!", justify=tk.CENTER)
        lbl.pack(pady=10)

        progress = ttk.Progressbar(scan_win, orient=tk.HORIZONTAL, length=350, mode='indeterminate')
        progress.pack(pady=10)
        progress.start(15)

        status_lbl = ttk.Label(scan_win, text="Kérlek várj...", font=("Arial", 8))
        status_lbl.pack(pady=5)

        def scan_worker():
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                time.sleep(1) # Pici pihenő
                subprocess.run(['pnputil', '/scan-devices'], startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
                time.sleep(3) # Várjunk, amíg a Windows a háttérben telepíti az eszközöket
            except Exception as ex:
                print(f"Hiba a PnP hardver scan során: {ex}")

            def finish_scan():
                if scan_win.winfo_exists():
                    scan_win.destroy()
                messagebox.showinfo("Kész", "Az alapértelmezett Windows illesztők (pl. Generic Touchpad) beállítása befejeződött!\nMost már működnie kell az eszközöknek.")
                self.refresh_drivers()

            self.after(0, finish_scan)

        threading.Thread(target=scan_worker, daemon=True).start()

    def check_wu_status(self):
        try:
            policy_disabled = False
            search_disabled = False
            
            # 1. Policy key (Windows 10/11)
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate", 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, "ExcludeWUDriversInQualityUpdate")
                    if val == 1: policy_disabled = True
            except FileNotFoundError:
                pass
                
            # 2. DriverSearching key (Eszköztelepítési beállítások)
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching", 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, "SearchOrderConfig")
                    if val == 0: search_disabled = True
            except FileNotFoundError:
                pass
                
            if policy_disabled and search_disabled:
                self.wu_status_lbl.config(text="Állapot: Teljesen LETILTVA (Házirend és Eszközbeállítás is)", foreground="red")
            elif policy_disabled:
                self.wu_status_lbl.config(text="Állapot: Házirend által LETILTVA (Képen: bekapcsolva)", foreground="red")
            elif search_disabled:
                self.wu_status_lbl.config(text="Állapot: Eszközbeállításokban LETILTVA", foreground="red")
            else:
                self.wu_status_lbl.config(text="Állapot: Driver frissítés ENGEDÉLYEZVE", foreground="green")
        except Exception as e:
            self.wu_status_lbl.config(text="Állapot: Ismeretlen", foreground="black")

    def disable_wu_drivers(self):
        try:
            # Policy - ExcludeWUDriversInQualityUpdate (Windows 10/11)
            key_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 1)
            
            # SearchOrderConfig
            key_path2 = r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching"
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path2, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 0)
                
            messagebox.showinfo("Siker", "Windows Update driver telepítés sikeresen LETILTVA.")
            self.check_wu_status()
        except PermissionError:
            messagebox.showerror("Hiba", "Nincs jogosultság a Registry írásához. Futtasd Rendszergazdaként!")
        except Exception as e:
            messagebox.showerror("Hiba", f"Hiba történt:\n{str(e)}")

    def enable_wu_drivers(self):
        try:
            key_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key, "ExcludeWUDriversInQualityUpdate")
            except FileNotFoundError:
                pass

            key_path2 = r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching"
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path2, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 1)

            messagebox.showinfo("Siker", "Windows Update driver telepítés sikeresen VISSZAÁLLÍTVA.")
            self.check_wu_status()
        except PermissionError:
            messagebox.showerror("Hiba", "Nincs jogosultság a Registry írásához. Futtasd Rendszergazdaként!")
        except Exception as e:
            messagebox.showerror("Hiba", f"Hiba történt:\n{str(e)}")

    def create_restore_point(self):
        desc = f"Driver_Cleaner_Backup_{datetime.now().strftime('%Y%md_%H%M%S')}"
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            # PowerShell Command to create a restore point
            cmd = f'powershell.exe -ExecutionPolicy Bypass -NoProfile -Command "Checkpoint-Computer -Description \'{desc}\' -RestorePointType \'MODIFY_SETTINGS\'"'
            
            messagebox.showinfo("Folyamatban", "Rendszer-visszaállítási pont létrehozása elindult...\nEz eltarthat egy percig, kérlek várj!")
            res = subprocess.run(cmd, shell=True, startupinfo=startupinfo, capture_output=True, text=True, errors='replace')
            
            if res.returncode == 0:
                messagebox.showinfo("Siker", f"A '{desc}' nevű visszaállítási pont sikeresen létrejött!")
            else:
                messagebox.showerror("Hiba", f"Nem sikerült létrehozni a visszaállítási pontot. Biztosan engedélyezve van a Rendszervédelem a Windowsban?\n\nKimenet: {res.stderr}")
        except Exception as e:
            messagebox.showerror("Hiba", f"Kivétel történt:\n{str(e)}")

    def backup_drivers(self):
        dest_dir = filedialog.askdirectory(title="Válassz egy mappát a driverek kimentéséhez")
        if not dest_dir:
            return
            
        backup_folder = os.path.join(dest_dir, f"Driver_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(backup_folder, exist_ok=True)
        
        # Létrehozunk egy felugró ablakot a progress barnak
        prog_win = tk.Toplevel(self)
        prog_win.title("Exportálás folyamatban...")
        prog_win.geometry("500x180")
        prog_win.transient(self)
        prog_win.grab_set()  # Letiltja a többi ablak kattintását, amíg ez megy

        lbl = ttk.Label(prog_win, text=f"Driverek kimentése folyamatban ide:\n{backup_folder}\nKérlek várj...", justify=tk.CENTER)
        lbl.pack(pady=10)

        # Determinate csúszka (0-tól maxig megy)
        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=400, mode='determinate')
        progress.pack(pady=10)
        
        status_lbl = ttk.Label(prog_win, text="DISM indítása...", font=("Arial", 8))
        status_lbl.pack(pady=5)

        # Elsődleges tipp a maximumra a listából
        total_guess = len(self.tree.get_children())
        if total_guess > 0:
            progress.config(maximum=total_guess)

        def worker():
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                # Popen-nel futtatjuk, így tudjuk olvasni a kimenetet menet közben
                process = subprocess.Popen(['dism', '/online', '/export-driver', f'/destination:{backup_folder}'], 
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, 
                                           startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, errors='replace')
                
                success = False
                output_log = []
                current_val = 0
                
                for line in process.stdout:
                    line = line.strip()
                    if not line: continue
                    output_log.append(line)
                    
                    # DISM kimenet keresése pl.: "1 of 22" vagy "1 / 22"
                    m = re.search(r'(\d+)\s*(?:/|of|ből)\s*(\d+)', line.lower())
                    if m:
                        val = int(m.group(1))
                        mx = int(m.group(2))
                        def update_prog(v=val, mg=mx, txt=line):
                            progress.config(maximum=max(mg, 1))
                            progress['value'] = v
                            short_txt = txt if len(txt) < 65 else txt[:62] + "..."
                            status_lbl.config(text=short_txt)
                        self.after(0, update_prog)
                    elif ".inf" in line.lower():
                        current_val += 1
                        def step_prog(v=current_val, txt=line):
                            if progress['maximum'] < v: progress.config(maximum=v+5)
                            progress['value'] = v
                            short_txt = txt if len(txt) < 65 else txt[:62] + "..."
                            status_lbl.config(text=short_txt)
                        self.after(0, step_prog)
                    else:
                        def set_txt(txt=line):
                            short_txt = txt if len(txt) < 65 else txt[:62] + "..."
                            status_lbl.config(text=short_txt)
                        self.after(0, set_txt)

                process.wait()
                full_out = "\n".join(output_log)
                if process.returncode == 0 or "successful" in full_out.lower() or "siker" in full_out.lower():
                    success = True

                def finish():
                    if prog_win.winfo_exists():
                        prog_win.destroy()
                    if success:
                        msg = f"A harmadik fél (third-party) driverek sikeresen lementve ide:\n{backup_folder}\n\nHa baj van, Sergei Strelec WinPE-ben a dism++ szoftverrel visszarakhatod őket!"
                        messagebox.showinfo("Sikeres Export", msg)
                    else:
                        messagebox.showerror("Hiba", f"A dism hibaüzenettel tért vissza:\nLásd a logot vagy futtasd kézzel.")
                self.after(0, finish)

            except Exception as e:
                def on_err(err=e):
                    if prog_win.winfo_exists():
                        prog_win.destroy()
                    messagebox.showerror("Kivétel", f"Váratlan hiba az exportálás során:\n{str(err)}")
                self.after(0, on_err)

        # Külön szálon indítjuk, hogy a GUI reszponzív maradjon és lássuk a csúszkát
        threading.Thread(target=worker, daemon=True).start()

    def restore_drivers(self):
        answer = messagebox.askyesnocancel(
            "Visszaállítási Mód",
            "ÉLŐRENDSZERRE (erre a futó Windowsra) akarod visszatenni a drivereket?\n\n"
            "IGEN: Jelenlegi futó rendszerre (Élő mód: PnP Util)\n"
            "NEM: Másik/Halott meghajtóra (Offline WinPE mód: DISM)\n"
            "MÉGSE: Megszakítás"
        )
        
        if answer is None: return
        elif answer: self.run_online_restore()
        else: self.run_offline_restore()

    def run_online_restore(self):
        source_dir = filedialog.askdirectory(title="ÉLŐ MÓD: Válassz egy korábban kimentett driver mappát")
        if not source_dir: return
        self._start_restore_thread(online=True, source_dir=source_dir, target_dir=None)

    def run_offline_restore(self):
        target_dir = filedialog.askdirectory(title=r"OFFLINE MÓD: 1. Válaszd ki a HALOTT WINDOWS MEGHAJTÓJÁT (pl. C:\ vagy D:\)")
        if not target_dir: return
        
        # Tisztítsuk meg a kiválasztott útvonalat, hogy mindig a meghajtó gyökerét kapjuk (pl. D:\)
        target_dir = os.path.abspath(target_dir)
        drive_root = os.path.splitdrive(target_dir)[0] + "\\"
        
        if not os.path.exists(os.path.join(drive_root, "Windows")):
            if not messagebox.askyesno("Figyelem", f"A kiválasztott meghajtón nem találok 'Windows' mappát:\n{drive_root}\n\nBiztosan ezen a meghajtón van a halott rendszer?"):
                return
                
        source_dir = filedialog.askdirectory(title="OFFLINE MÓD: 2. Válassz ki a kimentett driver mappát, amit betöltünk")
        if not source_dir: return
        
        # Kényszerítjük a gyökérkönyvtárat, hogy az elérési útvonalak (ProgramData, Windows\System32) helyesek legyenek!
        self._start_restore_thread(online=False, source_dir=source_dir, target_dir=drive_root)

    def _start_restore_thread(self, online, source_dir, target_dir):
        prog_win = tk.Toplevel(self)
        title_txt = "Élő rendszer frissítése..." if online else f"Offline WinPE Integrálás: {target_dir}"
        prog_win.title(title_txt)
        prog_win.geometry("550x180")
        prog_win.transient(self)
        prog_win.grab_set()

        lbl_txt = "Illesztőprogramok rátelepítése a jelenlegi gépre...\nKérlek várj!" if online else f"Illesztőprogramok befűzése a(z) {target_dir} meghajtóra...\nEz eltarthat egy darabig!"
        lbl = ttk.Label(prog_win, text=lbl_txt, justify=tk.CENTER)
        lbl.pack(pady=10)

        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=450, mode='indeterminate')
        progress.pack(pady=10)
        progress.start(15)
        
        status_lbl = ttk.Label(prog_win, text="Parancs indítása...", font=("Arial", 8))
        status_lbl.pack(pady=5)

        def worker():
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                if online:
                    cmd = ['pnputil', '/add-driver', os.path.join(source_dir, "*.inf"), '/subdirs', '/install']
                else:
                    cmd = ['dism', f'/Image:{target_dir}', '/Add-Driver', f'/Driver:{source_dir}', '/Recurse', '/ForceUnsigned']
                
                logging.info(f"Futtatas ({'Online' if online else 'Offline'}): {' '.join(cmd)}")
                
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, 
                                           startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, errors='replace')
                
                for line in process.stdout:
                    line = line.strip()
                    if not line: continue
                    logging.debug(f"[KIMENET] {line}")
                    def update_lbl(txt=line):
                        short_txt = txt if len(txt) < 70 else txt[:67] + "..."
                        status_lbl.config(text=short_txt)
                    self.after(0, update_lbl)

                process.wait()
                logging.info(f"Folyamat befejezodott. Return code: {process.returncode}")

                if online:
                    self.after(0, lambda: status_lbl.config(text="Hardverváltozások keresése az Eszközkezelőben..."))
                    import time
                    time.sleep(1.5)
                    subprocess.run(['pnputil', '/scan-devices'], startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
                    time.sleep(3.5)
                else:
                    # Create an auto-run script and register it in RunOnce for IMMEDIATE execution upon OS logon
                    try:
                        temp_drivers_dir_target = os.path.join(target_dir, "TempRunDrivers")
                        logging.info(f"Driver mappa masolasa live startup telepiteshez: {source_dir} -> {temp_drivers_dir_target}")
                        if os.path.exists(temp_drivers_dir_target):
                            shutil.rmtree(temp_drivers_dir_target, ignore_errors=True)
                        shutil.copytree(source_dir, temp_drivers_dir_target, dirs_exist_ok=True)

                        # Hova rakjuk a bat fajlt? ProgramData egy jo rejtett hely.
                        programdata_dir = os.path.join(target_dir, "ProgramData")
                        if not os.path.exists(programdata_dir):
                            os.makedirs(programdata_dir)
                            
                        bat_path = os.path.join(programdata_dir, "auto_pnputil_scan.bat")
                        logging.info(f"BAT fajl letrehozasa: {bat_path}")
                        
                        bat_content = "@echo off\r\n" \
                                      "set LOGFILE=\"%SystemDrive%\\Users\\Public\\Desktop\\driver_startup_log.txt\"\r\n" \
                                      "echo ---------------------------------------- >> %LOGFILE%\r\n" \
                                      "echo [%DATE% %TIME%] Boot elotti SYSTEM telepites service (No UAC! Azonnali!) >> %LOGFILE%\r\n" \
                                      "echo [%DATE% %TIME%] Ideiglenes szerviz torlese a registrybol is... >> %LOGFILE%\r\n" \
                                      "sc delete DriverRestoreSvc >> %LOGFILE% 2>&1\r\n" \
                                      "echo [%DATE% %TIME%] Driverek betoltese (Csendes mod)... kerlek varj! >> %LOGFILE%\r\n" \
                                      "pnputil /add-driver \"%SystemDrive%\\TempRunDrivers\\*.inf\" /subdirs /install >> %LOGFILE% 2>&1\r\n" \
                                      "echo [%DATE% %TIME%] pnputil scan-devices inditasa... >> %LOGFILE%\r\n" \
                                      "pnputil /scan-devices >> %LOGFILE% 2>&1\r\n" \
                                      "echo [%DATE% %TIME%] Ideiglenes mappak torlese... >> %LOGFILE%\r\n" \
                                      "rd /s /q \"%SystemDrive%\\TempRunDrivers\" >> %LOGFILE% 2>&1\r\n" \
                                      "echo [%DATE% %TIME%] Befejezve. Torlom a scriptet. >> %LOGFILE%\r\n" \
                                      "ping 127.0.0.1 -n 3 > nul\r\n" \
                                      "(goto) 2>nul & del \"%~f0\"\r\n"
                        with open(bat_path, "w", encoding="utf-8") as f:
                            f.write(bat_content)

                        # Modositsuk az OFFLINE Registry SYSTEM kulcsot, hogy bypassoljuk a logint es Service-kent fusson SYSTEM joggal
                        hive_path = os.path.join(target_dir, "Windows", "System32", "config", "SYSTEM")
                        logging.info(f"Registry hive keresese a Service injektalashoz: {hive_path}")
                        if os.path.exists(hive_path):
                            logging.info("Offline registry injektalas a HKLM\\SYSTEM\\ControlSet001\\Services-be...")
                            try:
                                subprocess.run(['reg', 'load', 'HKLM\\OFFLINE_SYSTEM', hive_path], check=True, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                                try:
                                    svc_key = r"HKLM\OFFLINE_SYSTEM\ControlSet001\Services\DriverRestoreSvc"
                                    # Szerviz letrehozasa Registry-ben
                                    subprocess.run(['reg', 'add', svc_key, '/f'], check=True, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                                    # ImagePath: A cmd indit egy hatter folyamatot majd KILEP, igy a SCM nem fagyasztja meg a bootot
                                    cmd_path = r'%SystemRoot%\System32\cmd.exe /c start "" "%SystemDrive%\ProgramData\auto_pnputil_scan.bat"'
                                    subprocess.run(['reg', 'add', svc_key, '/v', 'ImagePath', '/t', 'REG_EXPAND_SZ', '/d', cmd_path, '/f'], check=True, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                                    subprocess.run(['reg', 'add', svc_key, '/v', 'Type', '/t', 'REG_DWORD', '/d', '16', '/f'], check=True, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                                    subprocess.run(['reg', 'add', svc_key, '/v', 'Start', '/t', 'REG_DWORD', '/d', '2', '/f'], check=True, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                                    subprocess.run(['reg', 'add', svc_key, '/v', 'ErrorControl', '/t', 'REG_DWORD', '/d', '1', '/f'], check=True, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                                    subprocess.run(['reg', 'add', svc_key, '/v', 'ObjectName', '/t', 'REG_SZ', '/d', 'LocalSystem', '/f'], check=True, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                                    logging.info("Registry szerviz injektalas sikeres.")
                                finally:
                                    # MINDIG unloadoljuk a hivét, különben a Windows nem fog tudni bebútolni!
                                    subprocess.run(['reg', 'unload', 'HKLM\\OFFLINE_SYSTEM'], check=True, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                            except subprocess.CalledProcessError as reg_err:
                                logging.error(f"Registry hiba történt: {reg_err.stderr if hasattr(reg_err, 'stderr') else str(reg_err)}")
                                raise
                        else:
                            logging.error("SYSTEM hive nem talalhato, fallback startup mappa.")
                            startup_dir = os.path.join(target_dir, "ProgramData", "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
                            if os.path.exists(startup_dir):
                                shutil.copy(bat_path, os.path.join(startup_dir, "auto_pnputil_scan.bat"))

                    except Exception as ex:
                        print(f"Nem sikerült létrehozni a startup scriptet: {ex}")

                def finish():
                    if prog_win.winfo_exists():
                        prog_win.destroy()
                    if online:
                        messagebox.showinfo("Kész", "A driverek automatikus (Élő) felismertetése befejeződött!\nA Touchpadnak már mennie kell.")
                        self.refresh_drivers()
                    else:
                        msg = "Az offline driver integrálás (DISM) a megadott meghajtón befejeződött!\n\nBiztonsági intézkedésként a Rendszerleíróba (SYSTEM Service) beágyaztunk egy ideiglenes gyári driver scannert háttérszolgáltatásként.\nTöbbé nem kér UAC engedélyt, hanem azonnal, a bejelentkezés előtt fel fogja ébreszteni a Touchpadet, a legnagyobb SYSTEM szintű jogosultsággal!"
                        messagebox.showinfo("Offline Kész", msg)

                self.after(0, finish)

            except Exception as e:
                logging.exception(f"Hiba a futtato szalban: {e}")
                def on_err(err=e):
                    if prog_win.winfo_exists():
                        prog_win.destroy()
                    messagebox.showerror("Kivétel", f"Hiba történt:\n{str(err)}")
                self.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    if not is_admin():
        # Felemeljük a jogosultságot UAC ablakkal
        import sys
        params = ' '.join([f'"{arg}"' for arg in sys.argv[1:]])
        if getattr(sys, 'frozen', False):
            # PyInstaller exe
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        else:
            # Python script
            script = sys.argv[0]
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
        sys.exit()

    app = DriverCleanerApp()
    app.mainloop()
