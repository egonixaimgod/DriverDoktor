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
        self.title("Windows Driver Szerviz & Tisztító Eszköz")
        self.geometry("780x560")
        self.minsize(600, 450)

        # Let's apply a more modern style if possible
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
            style.configure(".", background="#FFFFFF")
            style.configure("TFrame", background="#FFFFFF")
            style.configure("TLabel", background="#FFFFFF")
            style.configure("TButton", background="#0078D7", foreground="white")
        except:
            pass
        
        # Configure fonts
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TLabelframe.Label", font=("Segoe UI", 11), foreground="#003366")
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        style.configure("Danger.TButton", font=("Segoe UI", 10), foreground="red")
        
        try:
            self.iconbitmap(resource_path("icon.ico"))
        except:
            pass
        
        self.create_widgets()
        self.refresh_drivers()

    def create_widgets(self):
        # 0. Initialize variables missed during UI refactor
        import os
        self.sys_drive = os.path.splitdrive(os.environ.get('WINDIR', 'C:\\\\'))[0] + "\\\\"
        if not hasattr(self, 'target_os_path'):
            self.target_os_path = None

        # 1. Top Bar - OS Selector
        top_bar = tk.Frame(self, bg="#FFFFFF", padx=10, pady=10)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        
        target_title_lbl = ttk.Label(top_bar, text="Vizsgált Célpont:", font=("Segoe UI", 12, "bold"), foreground="#666666")
        target_title_lbl.pack(side=tk.LEFT, padx=(0, 5))
        
        self.target_lbl = ttk.Label(top_bar, text=f"JELENLEGI RENDSZER ({self.sys_drive})", font=("Segoe UI", 16, "bold"), foreground="#2e7d32")
        self.target_lbl.pack(side=tk.LEFT, padx=10)

        change_os_btn = ttk.Button(top_bar, text="Halott gép / Offline Windows választása (Külső lemez)", command=self.change_target_os, width=45)
        change_os_btn.pack(side=tk.LEFT, padx=5)

        reset_os_btn = ttk.Button(top_bar, text="Vissza (Jelenlegi rendszer)", command=self.reset_target_os)
        reset_os_btn.pack(side=tk.LEFT, padx=5)


        # 2. Main Body Splitter
        main_body = tk.Frame(self, bg="#F3F3F3")
        main_body.pack(fill=tk.BOTH, expand=True)


        # 3. Sidebar on the left
        sidebar_frame = tk.Frame(main_body, bg="#E5F3FF", width=250)
        sidebar_frame.pack(side=tk.LEFT, fill=tk.Y)
        sidebar_frame.pack_propagate(False)
        
        ttk.Label(sidebar_frame, text="Kategóriák", font=("Segoe UI", 12, "bold"), foreground="#003366", background="#E5F3FF").pack(pady=15, padx=10, anchor="w")

        btn_drivers = ttk.Button(sidebar_frame, text="📦 Kezelés", command=lambda: self.switch_view("drivers"))
        btn_drivers.pack(fill=tk.X, padx=10, pady=5)
        
        btn_backup = ttk.Button(sidebar_frame, text="💾 Mentés és Extrém", command=lambda: self.switch_view("backup"))
        btn_backup.pack(fill=tk.X, padx=10, pady=5)

        btn_wu = ttk.Button(sidebar_frame, text="🔄 Windows Update", command=lambda: self.switch_view("wu"))
        btn_wu.pack(fill=tk.X, padx=10, pady=5)


        # 4. Content Area on the right
        self.content_frame = tk.Frame(main_body, bg="#FFFFFF")
        self.content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 5. Views
        self.driver_view = tk.Frame(self.content_frame, bg="#FFFFFF")
        self.backup_view = tk.Frame(self.content_frame, bg="#FFFFFF")
        self.wu_view = tk.Frame(self.content_frame, bg="#FFFFFF")

        # variables:
        self.list_all_var = tk.BooleanVar(value=False)

        # -----------------------------
        # DRIVER VIEW CONTENT (Drivers list & removal)
        # -----------------------------
        drv_frame = ttk.LabelFrame(self.driver_view, text="Telepített Driverek Kezelése", padding=10)
        drv_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        columns = ("published", "original", "provider", "class", "version")
        self.tree = ttk.Treeview(drv_frame, columns=columns, show="headings", selectmode="extended")
        
        self.tree.heading("published", text="Közzétett Név (oem.inf)")
        self.tree.heading("original", text="Eredeti Név")
        self.tree.heading("provider", text="Gyártó")
        self.tree.heading("class", text="Eszközosztály")
        self.tree.heading("version", text="Verzió/Dátum")

        self.tree.column("published", width=120)
        self.tree.column("original", width=150)
        self.tree.column("provider", width=120)
        self.tree.column("class", width=100)
        self.tree.column("version", width=150)

        scrollbar = ttk.Scrollbar(drv_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.focus_set()
        self.tree.bind("<Delete>", lambda e: self.delete_selected_drivers())
        self.tree.bind("<F5>", lambda e: self.refresh_drivers())
        self.tree.bind("<Control-a>", lambda e: self.select_all_drivers())
        self.tree.bind("<Control-A>", lambda e: self.select_all_drivers())

        # Button frame for the grid
        btn_frame = tk.Frame(self.driver_view, bg="#FFFFFF")
        btn_frame.pack(fill=tk.X, pady=5)

        # Use grid for responsive layout
        refresh_btn = ttk.Button(btn_frame, text="Lista Frissítése (F5)", command=self.refresh_drivers)
        refresh_btn.grid(row=0, column=0, padx=5, pady=5)

        select_all_btn = ttk.Button(btn_frame, text="Összes Kijelölése", command=self.select_all_drivers)
        select_all_btn.grid(row=0, column=1, padx=5, pady=5)

        self.list_all_chk = ttk.Checkbutton(btn_frame, text="Minden Driver (Veszélyes!)", variable=self.list_all_var, command=self.on_list_all_toggle)
        self.list_all_chk.grid(row=0, column=2, padx=5, pady=5)

        delete_btn = ttk.Button(btn_frame, text="Kiválasztott Driver(ek) TÖRLÉSE (Del)", command=self.delete_selected_drivers, style="Danger.TButton")
        delete_btn.grid(row=1, column=0, columnspan=3, pady=(0, 5), sticky="ew", padx=5)

        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)

        # -----------------------------
        # BACKUP & WIM VIEW CONTENT
        # -----------------------------
        backup_frame = ttk.LabelFrame(self.backup_view, text="Biztonsági Mentés (Driver Export és Visszaállítás)", padding=10)
        backup_frame.pack(fill=tk.X, padx=10, pady=10)

        rp_btn = ttk.Button(backup_frame, text="Új Rendszer-vissz. Pont", command=self.create_restore_point)
        rp_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        export_btn = ttk.Button(backup_frame, text="Összes Lementése (Export)", command=self.backup_drivers)
        export_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        restore_btn = ttk.Button(backup_frame, text="Lementett Driverek Visszaállítása", command=self.restore_drivers)
        restore_btn.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        backup_frame.columnconfigure(0, weight=1)
        backup_frame.columnconfigure(1, weight=1)

        wim_frame = ttk.LabelFrame(self.backup_view, text="Extrém Helyreállítás: Gyári Windows (Alap) Driverek Kinyerése", padding=10)
        wim_frame.pack(fill=tk.X, padx=10, pady=10)

        wim_lbl = ttk.Label(wim_frame, text="Ha minden gyári driver törlődött (Billentyűzet, Touchpad, Standard USB), a Windows ISO-ból (install.wim) visszahozhatod!", font=("Segoe UI", 8), wraplength=480)
        wim_lbl.pack(pady=(0, 10))

        wim_btn = ttk.Button(wim_frame, text="Alap Driverek Kinyerése (install.wim)", command=self.extract_wim_drivers)
        wim_btn.pack(pady=5)


        # -----------------------------
        # WINDOWS UPDATE VIEW CONTENT
        # -----------------------------
        wu_frame = ttk.LabelFrame(self.wu_view, text="Windows Update Driver Frissítések Beállításai", padding=10)
        wu_frame.pack(fill=tk.X, padx=10, pady=5)

        self.wu_status_lbl = ttk.Label(wu_frame, text="Állapot: Ismeretlen", font=("Segoe UI", 10, "bold"))
        self.wu_status_lbl.grid(row=0, column=0, columnspan=2, pady=5)

        disable_wu_btn = ttk.Button(wu_frame, text="WU Letöltés LETILTÁSA", command=self.disable_wu_drivers)
        disable_wu_btn.grid(row=1, column=0, padx=5, pady=5, sticky="ew")

        enable_wu_btn = ttk.Button(wu_frame, text="WU Letöltés ENGEDÉLYEZÉSE", command=self.enable_wu_drivers)
        enable_wu_btn.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        wu_frame.columnconfigure(0, weight=1)
        wu_frame.columnconfigure(1, weight=1)


        # Show drivers by default
        self.driver_view.pack(fill=tk.BOTH, expand=True)

    def switch_view(self, view_name):
        self.driver_view.pack_forget()
        self.backup_view.pack_forget()
        self.wu_view.pack_forget()
        
        if view_name == "drivers":
            self.driver_view.pack(fill=tk.BOTH, expand=True)
            self.tree.focus_set()
        elif view_name == "backup":
            self.backup_view.pack(fill=tk.BOTH, expand=True)
        elif view_name == "wu":
            self.wu_view.pack(fill=tk.BOTH, expand=True)

    def change_target_os(self):
        d = filedialog.askdirectory(title="Válaszd ki a halott Windows meghajtóját (pl. C:\ vagy D:\, amin a Windows mappa van!)")
        if d:
            d = os.path.abspath(d).replace("/", "\\")
            if not os.path.exists(os.path.join(d, "Windows")):
                if not messagebox.askyesno("Nincs Windows mappa", f"Nem találok 'Windows' mappát ezen az útvonalon:\n{d}\n\nEgy biztos, hogy ezt választod? (Fura PE környezetben lehet máshol van)"):
                    return
            self.target_os_path = d
            self.target_lbl.config(text=f"OFFLINE MÓD ({self.target_os_path})", foreground="#c62828", font=("Segoe UI", 16, "bold"))
            messagebox.showinfo("Célpont Frissítve", f"Mostantól a(z) {d} meghajtó offline drivereit listázza és törli a program (DISM segítségével)!")
            self.refresh_drivers()

    def reset_target_os(self):
        self.target_os_path = None
        self.target_lbl.config(text=f"JELENLEGI RENDSZER ({self.sys_drive})", foreground="#2e7d32", font=("Segoe UI", 16, "bold"))
        self.refresh_drivers()

    def get_offline_drivers(self, all_drivers=False):
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # Switch back to DISM for offline reliability (Powershell get-windowsdriver fails often in WinPE)
            cmd = ['dism', f'/Image:{self.target_os_path}', '/Get-Drivers']
            if all_drivers:
                cmd.append('/all')
                
            res = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
            
            drivers = []
            current_driver = {}
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line:
                    if current_driver and "published" in current_driver:
                        # Ha megvan a közzétett név, mentsük el a drivert
                        drivers.append(current_driver)
                        current_driver = {}
                    continue
                
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip().lower()
                    val = parts[1].strip()
                    
                    if "közzétett" in key or "published" in key:
                        if current_driver and "published" in current_driver:
                            drivers.append(current_driver)
                            current_driver = {}
                        current_driver["published"] = val
                        # Alapértékek, ha nem lennének meg
                        current_driver["original"] = ""
                        current_driver["provider"] = ""
                        current_driver["class"] = ""
                        current_driver["version"] = ""
                    elif "eredeti" in key or "original" in key:
                        current_driver["original"] = val
                    elif "szolgáltató" in key or "gyártó" in key or "provider" in key:
                        current_driver["provider"] = val
                    elif "osztály" in key or "class" in key:
                        current_driver["class"] = val
                    elif "verzió" in key or "version" in key:
                        current_driver["version"] = val
                        
            if current_driver and "published" in current_driver:
                drivers.append(current_driver)
                
            return drivers
        except Exception as e:
            logging.error(f"Hiba az Offline driver lekérdezésben (DISM Get-Drivers): {e}")
            return []

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

    def on_list_all_toggle(self):
        if self.list_all_var.get():
            warn_msg = ("A Windows gyári / alapvető (inbox) drivereinek listázását választottad!\n\n"
                        "HA EZEKET TÖRÖLGETJÜK, EL LEHET BASZARINTANI A GÉPET!\n"
                        "(Pl. Kékhalál induláskor, nem működő egér/billentyűzet, USB portok halála)\n\n"
                        "Biztosan bekapcsolod ezt a 'Minden Driver' nézetet?")
            if not messagebox.askyesno("VESZÉLYES FUNKCIÓ BEKAPCSOLÁSA", warn_msg, icon='warning'):
                self.list_all_var.set(False)
                return
        self.refresh_drivers()

    def get_all_drivers(self):
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            cmd = ['powershell', '-NoProfile', '-Command', 
                   'Get-WindowsDriver -Online -All | Select-Object ProviderName, ClassName, Version, Driver, OriginalFileName | ConvertTo-Json -Depth 2 -WarningAction SilentlyContinue']
            res = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
            
            import json
            out = res.stdout.strip()
            if not out: return []
            
            # Powershell gives pure JSON
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
                
            drivers = []
            for d in data:
                drivers.append({
                    "published": d.get("Driver", ""),
                    "original": d.get("OriginalFileName", ""),
                    "provider": d.get("ProviderName", ""),
                    "class": d.get("ClassName", ""),
                    "version": d.get("Version", "")
                })
            return drivers
        except Exception as e:
            logging.error(f"Hiba a gyári driver lekérdezésben (Powershell Get-WindowsDriver): {e}")
            return []

    def refresh_drivers(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        is_all = hasattr(self, 'list_all_var') and self.list_all_var.get()
        
        if hasattr(self, 'target_os_path') and self.target_os_path:
            drivers = self.get_offline_drivers(all_drivers=is_all)
        else:
            if is_all:
                drivers = self.get_all_drivers()
            else:
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
            messagebox.showwarning("Figyelmeztetes", "Kerlek, valassz ki legalabb egy drivert a torleshez!")
            return
            
        if not messagebox.askyesno("Megerosites", f"Biztosan torolni szeretned a kivalasztott {len(selected)} drivert es az eszkozokrol is eltavolitod?"):
            return
            
        prog_win = tk.Toplevel(self)
        prog_win.title("Torles folyamatban...")
        prog_win.geometry("600x350")
        prog_win.transient(self)
        prog_win.grab_set()

        lbl = ttk.Label(prog_win, text=f"{len(selected)} driver vegleges eltavolitasa folyamatban...\nKerlek varj!", justify=tk.CENTER)
        lbl.pack(pady=5)

        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=500, mode='determinate')
        progress.pack(pady=5)
        progress.config(maximum=len(selected))
        
        status_lbl = ttk.Label(prog_win, text="Inicializalas...", font=("Arial", 8))
        status_lbl.pack(pady=5)
        
        text_frame = tk.Frame(prog_win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10))
        log_text = tk.Text(text_frame, height=10, state=tk.DISABLED, bg="#F3F3F3", font=("Consolas", 8))
        log_scroll = ttk.Scrollbar(text_frame, command=log_text.yview)
        log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def append_log(msg):
            logging.info(msg)
            log_text.config(state=tk.NORMAL)
            log_text.insert(tk.END, msg + "\n")
            log_text.see(tk.END)
            log_text.config(state=tk.DISABLED)

        items_to_delete = [self.tree.item(item, "values")[0] for item in selected]

        def worker():
            success_count = 0
            fail_count = 0
            
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            self.after(0, lambda: append_log(f"Kijelolt driverek torlese indult ({len(items_to_delete)} db)"))
            for i, published_name in enumerate(items_to_delete):
                def update_status(txt=f"{published_name} torlese ({i+1}/{len(items_to_delete)})...", val=i):
                    status_lbl.config(text=txt)
                    progress['value'] = val
                self.after(0, update_status)
                
                try:
                    is_offline = hasattr(self, 'target_os_path') and self.target_os_path
                    is_oem = published_name.lower().startswith("oem")
                    
                    self.after(0, lambda m=f"-> Torles megkezdese: {published_name} (Offline: {bool(is_offline)}, OEM: {bool(is_oem)})": append_log(m))
                    
                    if is_offline and is_oem:
                        res = subprocess.run(['dism', f'/Image:{self.target_os_path}', '/Remove-Driver', f'/Driver:{published_name}'],
                                           capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                    elif not is_offline:
                        res = subprocess.run(['pnputil', '/delete-driver', published_name, '/uninstall', '/force'], 
                                           capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        class DummyRes: 
                            returncode = 1
                            stdout = ""
                        res = DummyRes()

                    if res.returncode == 0 or "Deleted" in res.stdout or "törölve" in res.stdout or "t\xf6r\xf6lve" in res.stdout or "successfully" in res.stdout.lower():
                        success_count += 1
                        self.after(0, lambda m=f"   [SIKER] {published_name} letorolve.": append_log(m))
                    else:
                        if hasattr(self, 'list_all_var') and self.list_all_var.get() and not is_oem:
                            self.after(0, lambda m=f"   [KISERLET] Inbox {published_name} eroszakos torlese FileRepository-bol...": append_log(m))
                            import glob
                            if is_offline:
                                rep_path = os.path.join(self.target_os_path, "Windows", "System32", "DriverStore", "FileRepository")
                            else:
                                rep_path = r"C:\Windows\System32\DriverStore\FileRepository"
                            
                            base_name = published_name.replace(".inf", "")
                            dirs = glob.glob(os.path.join(rep_path, f"{base_name}*.inf_*"))
                            
                            if dirs:
                                for d in dirs:
                                    try:
                                        self.after(0, lambda m=f"   [TORLES] Mappa: {d}": append_log(m))
                                        subprocess.run(f'takeown /f "{d}" /r /d y', shell=True, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
                                        subprocess.run(f'icacls "{d}" /grant administrators:F /t', shell=True, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
                                        shutil.rmtree(d, ignore_errors=True)
                                        subprocess.run(f'rmdir /s /q "{d}"', shell=True, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
                                    except Exception as ex:
                                        self.after(0, lambda m=f"   [HIBA] {d} mappa torlesekor: {ex}": append_log(m))
                                success_count += 1
                                self.after(0, lambda m=f"   [SIKER (Eroszakos)] {published_name} letorolve.": append_log(m))
                            else:
                                fail_count += 1
                                self.after(0, lambda m=f"   [HIBA] Nem talaltam mappat ennel: {rep_path}": append_log(m))
                        else:
                            fail_count += 1
                            self.after(0, lambda m=f"   [HIBA] {published_name} torlese sikertelen. Code: {res.returncode}": append_log(m))
                            out_clean = res.stdout.strip().replace(chr(10), ' ')[:100]
                            self.after(0, lambda m=f"   [LOG] {out_clean}...": append_log(m))
                except Exception as e:
                    fail_count += 1
                    self.after(0, lambda m=f"   [KIVETEL] {published_name} torlesekor: {e}": append_log(m))

            self.after(0, lambda: progress.configure(value=len(items_to_delete)))
            self.after(0, lambda: append_log(f"--- FOLYAMAT VEGE. Sikeres: {success_count}, Sikertelen: {fail_count} ---"))

            def finish_delete():
                if prog_win.winfo_exists():
                    prog_win.destroy()
                messagebox.showinfo("Eredmeny", f"Sikeresen torolve: {success_count}\nNem sikerult: {fail_count}\n\nMost a program ujraellenorzi a hardvereket.")
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
                
            # Restart Windows Update Service to apply changes and unfreeze it
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run("net stop wuauserv & net start wuauserv", shell=True, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
            
            messagebox.showinfo("Siker", "Windows Update driver telepítés sikeresen LETILTVA.\n\n(A Windows Update szolgáltatás újraindult a háttérben.)")
            self.check_wu_status()
        except PermissionError:
            messagebox.showerror("Hiba", "Nincs jogosultság a Registry írásához. Futtasd Rendszergazdaként!")
        except Exception as e:
            messagebox.showerror("Hiba", f"Hiba történt:\n{str(e)}")

    def enable_wu_drivers(self):
        try:
            key_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
            try:
                # Kifejezetten 0-ra állítjuk, hogy a policy garantáltan törlődjön a gyorsítótárból is
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 0)
            except Exception:
                pass

            key_path2 = r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching"
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path2, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 1)

            # Töröljük a teljes Update letiltást abban az esetben, ha valami más program esetleg betette
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU", 0, winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key, "NoAutoUpdate")
            except: pass

            # A végtelen frissítés-keresés (beragadás) javítása érdekében újraindítjuk a WU szolgáltatást
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run("net stop wuauserv && net start wuauserv", shell=True, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)

            messagebox.showinfo("Siker", "Windows Update driver telepítés sikeresen VISSZAÁLLÍTVA.\n\n(A Windows Update szolgáltatást újraindítottuk, így az 'örökké tartó' keresés megszűnik és megtalálja a frissítéseket!)")
            self.check_wu_status()
        except PermissionError:
            messagebox.showerror("Hiba", "Nincs jogosultság a Registry írásához. Futtasd Rendszergazdaként!")
        except Exception as e:
            messagebox.showerror("Hiba", f"Hiba történt:\n{str(e)}")

    def create_restore_point(self):
        desc = f"Driver_Cleaner_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
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

    def extract_wim_drivers(self):
        msg = "Ezzel az opcióval egy hivatalos Windows ISO 'sources\\install.wim' fájljából bányásszuk ki a TISZTA Windows drivereket (Standard USB Hdd, PS/2 Billentyűzet, Touchpad).\nEzután az 'Lementett Driverek Visszaállítása -> Offline (Nem)' opcióval rá is küldheted a halott gépre.\n\nAkarod folytatni?"
        if not messagebox.askyesno("ISO / WIM Alap Driver Kinyerés", msg): return
        
        wim_path = filedialog.askopenfilename(title="Válaszd ki a Windows ISO 'install.wim' fájlját!", filetypes=[("Windows Image (.wim)", "*.wim")])
        if not wim_path: return
        
        if wim_path.lower().endswith(".esd"):
            messagebox.showerror("Hiba", "Az ESD fájl formátumot a Windows nem tudja közvetlenül kicsomagolni. Kérlek, szerez egy olyan ISO-t, amiben 'install.wim' van (pl. Rufus letöltés)!")
            return
            
        dest_dir = filedialog.askdirectory(title="Válassz egy IDEIGLENES mappát, ahova kicsomagoljuk a teljes gyári driver készletet")
        if not dest_dir: return
        
        target_folder = os.path.join(dest_dir, f"Windows_Gyari_Alap_Driverek_{datetime.now().strftime('%Y%m%d_%H%M')}")
        os.makedirs(target_folder, exist_ok=True)
        
        mount_dir = os.path.join(dest_dir, "WIM_Mount_Temp")
        if os.path.exists(mount_dir):
            shutil.rmtree(mount_dir, ignore_errors=True)
        os.makedirs(mount_dir, exist_ok=True)
        
        # Kiszedjük a fájl utakat és gondoskodunk a szóköz/backslash hibákról cmd paraméternek
        wim_path = os.path.abspath(wim_path).replace("/", "\\")
        mount_dir = os.path.abspath(mount_dir).replace("/", "\\")
        dest_dir = os.path.abspath(dest_dir).replace("/", "\\")
        target_folder = os.path.abspath(target_folder).replace("/", "\\")
        
        prog_win = tk.Toplevel(self)
        prog_win.title("WIM csatolás folyamatban...")
        prog_win.geometry("550x180")
        prog_win.transient(self)
        prog_win.grab_set()

        lbl = ttk.Label(prog_win, text=f"Windows Image csatolása és gyári driverek kinyerése...\nEz több percig is eltarthat, a háttérben folyik a művelet!", justify=tk.CENTER)
        lbl.pack(pady=10)
        
        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=450, mode='indeterminate')
        progress.pack(pady=10)
        progress.start(15)

        status_lbl = ttk.Label(prog_win, text="WIM fájl csatolása (Mount)...", font=("Arial", 8))
        status_lbl.pack(pady=5)
        
        def worker():
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                # 1. Mount image
                self.after(0, lambda: status_lbl.config(text="1/3: Képfájl csatolása a Temp mappába (Türelem, 4-5 perc is lehet!)..."))
                logging.info(f"WIM mountolasa: {wim_path}")
                mount_cmd = [
                    "dism", "/Mount-Image",
                    f"/ImageFile:{wim_path}",
                    "/Index:1",
                    f"/MountDir:{mount_dir}",
                    "/ReadOnly"
                ]
                res = subprocess.run(mount_cmd, capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                if res.returncode != 0:
                    raise Exception(f"DISM Mount Hiba: {res.stdout.strip()} Hiba_stderr: {res.stderr.strip()}")
                
                # 2. Másolás robocopy-val (az XCOPY vagy shutil gyakran hibázik hosszú file nevek miatt)
                self.after(0, lambda: status_lbl.config(text="2/3: Gyári DriverStore másolása (1-2 GB adat)..."))
                driverstore_path = os.path.join(mount_dir, "Windows", "System32", "DriverStore", "FileRepository")
                logging.info(f"DriverStore masolasa innen: {driverstore_path}")
                if os.path.exists(driverstore_path):
                    target_cmd = os.path.normpath(target_folder).replace("\\", "/")
                    robo_cmd = f'robocopy "{driverstore_path}" "{target_cmd}" /E /R:0 /W:0 /NFL /NDL /NJH /NJS /nc /ns /np'
                    subprocess.run(robo_cmd, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, shell=True)
                else:
                    raise Exception("A FileRepository (gyári driver mappa) nem található a csatolt WIM fájlban!")
                
                # 3. Biztonságos Unmount
                self.after(0, lambda: status_lbl.config(text="3/3: WIM leválasztása (Takarítás)..."))
                logging.info("WIM unmountolasa...")
                unmount_cmd = ["dism", "/Unmount-Image", f"/MountDir:{mount_dir}", "/Discard"]
                subprocess.run(unmount_cmd, capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                
                try:
                    shutil.rmtree(mount_dir, ignore_errors=True)
                except: pass

                def finish():
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showinfo("Kinyerés Kész", f"A TISZTA gyári driverek (alap USB, PS/2 Billentyűzet, Alaplapi chipek, Generic Touchpad) sikeresen kimentve ide:\n{target_folder}\n\nKövetkező lépés:\nKattints a 'Lementett Driverek Visszaállítása' gombra -> 'NEM' (Offline mód), és válaszd ki a halott gép meghajtóját, forrásnak pedig add meg ezt az új mappát!")
                self.after(0, finish)

            except Exception as e:
                logging.error(f"Hiba WIM kinyeresekor: {e}")
                err_unmount = ["dism", "/Unmount-Image", f"/MountDir:{mount_dir}", "/Discard"]
                subprocess.run(err_unmount, capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    shutil.rmtree(mount_dir, ignore_errors=True)
                except: pass
                def show_err(err=e):
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba történt", f"Nem sikerült kibontani a WIM fájlt a következő hiba miatt:\n{str(err)}")
                self.after(0, show_err)

        threading.Thread(target=worker, daemon=True).start()

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
        prog_win.geometry("900x650")
        prog_win.minsize(700, 480)
        prog_win.transient(self)
        prog_win.grab_set()

        lbl_txt = ("Illesztőprogramok rátelepítése a jelenlegi gépre...\nKérlek várj!" 
                   if online else f"Illesztőprogramok befűzése a(z) {target_dir} meghajtóra...\nEz eltarthat egy darabig!")
        lbl = ttk.Label(prog_win, text=lbl_txt, justify=tk.CENTER, font=("Segoe UI", 11, "bold"))
        lbl.pack(pady=5)

        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, mode='indeterminate')
        progress.pack(pady=5, fill=tk.X, padx=20)
        progress.start(15)
        
        status_lbl = ttk.Label(prog_win, text="Folyamat indítása... Készülünk az illesztőprogramokra...", font=("Segoe UI", 9))
        status_lbl.pack(pady=2)

        # Hatalmas szovegdoboz, hogy a felhasznalo LASSA a folyamatot reszletesen
        log_frame = tk.Frame(prog_win, bg="#000000")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        log_text = tk.Text(log_frame, wrap=tk.WORD, font=("Consolas", 10), bg="#1E1E1E", fg="#00FF00")
        log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        log_text.config(yscrollcommand=scrollbar.set)
        
        # Auto-scroll toggler
        auto_scroll = tk.BooleanVar(value=True)
        chk = tk.Checkbutton(prog_win, text="Automatikus görgetés (Auto-Scroll)", variable=auto_scroll)
        chk.pack(anchor="w", padx=20)
        
        close_btn = ttk.Button(prog_win, text="Bezárás", command=prog_win.destroy, state=tk.DISABLED)
        close_btn.pack(pady=10)

        def worker():
            log_handle = None
            try:
                # Ebbe a log fajlba 100% bizonyossággal beleteszi a kimenetet, meg a crash is bekerül!
                debug_log_path = os.path.join(os.path.abspath('.'), 'driver_tool_gui_restore.log')
                log_handle = open(debug_log_path, 'w', encoding='utf-8')
            except Exception:
                pass

            def write_log(msg):
                import logging
                if log_handle:
                    try:
                        log_handle.write(msg + '\n')
                        log_handle.flush() # AZONNALI Iras a pendriverra!
                    except:
                        pass
                logging.info(f"[RESTORE] {msg}")
                def gui_up():
                    try:
                        log_text.insert(tk.END, msg + '\n')
                        if auto_scroll.get():
                            log_text.see(tk.END)
                        short_txt = msg.strip() if len(msg.strip()) < 100 else msg.strip()[:97] + "..."
                        status_lbl.config(text=short_txt)
                    except:
                        pass
                self.after(0, gui_up)

            try:
                write_log(f"=== {'ONLINE' if online else 'OFFLINE'} DRIVER RESTORE INDÍTÁSA ===")
                write_log(f"Forrás könyvtár: {source_dir}")
                write_log(f"Célpont / OS Meghajtó: {target_dir}")
                write_log("Felkészülés a parancsok futtatására...")

                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                import os
                
                # Szigorú backslash konverzió a natív parancssori eszközöknek
                norm_source = os.path.normpath(source_dir).replace('/', '\\')
                norm_target = os.path.normpath(target_dir).replace('/', '\\')

                is_inbox_restore = (not online) and ("Windows_Gyari_Alap_Driverek" in norm_source)

                if is_inbox_restore:
                    write_log("Gyári Windows (inbox) driverek felismerve!")
                    write_log("A DISM offline /Add-Driver nem képes inbox drivereket telepíteni => Boot Service módszer aktiválva.")
                    write_log("A driverek a célrendszerre másolódnak, és az ELSŐ BOOTOLÁSKOR automatikusan telepítődnek online PnP-vel.")
                elif online:
                    cmd = ['pnputil', '/add-driver', f"{norm_source}\\*.inf", '/subdirs', '/install']
                    write_log(f"Végrehajtandó parancssor: {' '.join(cmd)}")
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, 
                                               startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, errors='replace')
                    for line in process.stdout:
                        line = line.strip()
                        if not line: continue
                        write_log(line)
                    process.wait()
                    write_log(f"\n--- Alapfolyamat befejeződött, visszatérési kód (Return Code): {process.returncode} ---")
                else:
                    scratch_dir = os.path.join(norm_target, "Scratch")
                    try:
                        os.makedirs(scratch_dir, exist_ok=True)
                        write_log(f"Scratch mappa létrehozva: {scratch_dir}")
                    except Exception as e:
                        write_log(f"Figyelem: Scratch mappa létrehozása sikertelen ({scratch_dir}): {e}")
                    
                    cmd = ['dism', f'/Image:{norm_target}', '/Add-Driver', f'/Driver:{norm_source}', '/Recurse', '/ForceUnsigned', f'/ScratchDir:{scratch_dir}']
                    write_log(f"Végrehajtandó parancssor: {' '.join(cmd)}")
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, 
                                               startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, errors='replace')
                    for line in process.stdout:
                        line = line.strip()
                        if not line: continue
                        write_log(line)
                    process.wait()
                    write_log(f"\n--- Alapfolyamat befejeződött, visszatérési kód (Return Code): {process.returncode} ---")

                if True:
                    if online:
                        write_log("Hardverváltozások keresése és eszközök frissítése az Eszközkezelőben...")
                        import time
                        time.sleep(1.5)
                        scan_proc = subprocess.run(['pnputil', '/scan-devices'], startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, errors='replace')
                        write_log("SCAN_DEVICES Kész! Kimenet:\n" + scan_proc.stdout)
                        time.sleep(3.5)
                    else:
                        import shutil
                        temp_drivers_dir_target = os.path.join(target_dir, "TempRunDrivers")
                        write_log(f"Készül a Boot-idejű automatikus PnP telepítő... Ideiglenes fájlfa másolása:\n {source_dir} -> {temp_drivers_dir_target}")
                        
                        if os.path.exists(temp_drivers_dir_target):
                            shutil.rmtree(temp_drivers_dir_target, ignore_errors=True)
                        try:
                            shutil.copytree(source_dir, temp_drivers_dir_target, dirs_exist_ok=True)
                            write_log(f"Másolás SIKERES a TempRunDrivers alá.")
                        except Exception as ee:
                            write_log(f"HIBA a temp mappa másolása közben: {ee}")

                        programdata_dir = os.path.join(target_dir, "ProgramData")
                        os.makedirs(programdata_dir, exist_ok=True)
                            
                        bat_path = os.path.join(programdata_dir, "auto_pnputil_scan.bat")
                        bat_content = "@echo off\r\n" \
                                      "set LOGFILE=\"%SystemDrive%\\Users\\Public\\driver_startup_log.txt\"\r\n" \
                                      "echo ---------------------------------------- >> %LOGFILE%\r\n" \
                                      "echo [%DATE% %TIME%] Boot elotti SYSTEM telepites service (No UAC! Azonnali!) >> %LOGFILE%\r\n" \
                                      "echo [%DATE% %TIME%] Ideiglenes szerviz torlese a registrybol is... >> %LOGFILE%\r\n" \
                                      "sc delete DriverRestoreSvc >> %LOGFILE% 2>&1\r\n" \
                                      "echo [%DATE% %TIME%] Varakozas a Windows PlugAndPlay szolgaltatasara (15 sec max)... >> %LOGFILE%\r\n" \
                                      "ping 127.0.0.1 -n 15 > nul\r\n" \
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
                        write_log(f"BAT fájl regisztrálva a rendszerbe: {bat_path}")

                        hive_path = os.path.join(target_dir, "Windows", "System32", "config", "SYSTEM")
                        if os.path.exists(hive_path):
                            write_log(f"Offline registry beinjektálása a HKLM\\OFFLINE_SYSTEM hive-ba ({hive_path})...")
                            import winreg
                            try:
                                subprocess.run(['reg', 'load', 'HKLM\\OFFLINE_SYSTEM', hive_path], check=True, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                                try:
                                    key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, r'OFFLINE_SYSTEM\ControlSet001\Services\DriverRestoreSvc')
                                    winreg.SetValueEx(key, 'Type', 0, winreg.REG_DWORD, 16)
                                    winreg.SetValueEx(key, 'Start', 0, winreg.REG_DWORD, 2)
                                    winreg.SetValueEx(key, 'ErrorControl', 0, winreg.REG_DWORD, 1)
                                    bat_target_path = r'%SystemDrive%\ProgramData\auto_pnputil_scan.bat'
                                    winreg.SetValueEx(key, 'ImagePath', 0, winreg.REG_EXPAND_SZ, bat_target_path)
                                    winreg.SetValueEx(key, 'ObjectName', 0, winreg.REG_SZ, 'LocalSystem')
                                    winreg.CloseKey(key)
                                    write_log("Sikeresen felprogramoztuk az Offline Windows Registry-t az auto-installhoz (Boot Service)!")
                                except Exception as rx:
                                    write_log("HIBA A REGISTRY VÁLTOZÓK ÍRÁSÁNÁL: " + str(rx))
                                finally:
                                    subprocess.run(['reg', 'unload', 'HKLM\\OFFLINE_SYSTEM'], check=False, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                            except subprocess.CalledProcessError as e:
                                write_log(f"REGISTRY MOUNT SIKERTELEN: Hibakód: {e.returncode}. Kimenet: {e.output}")
                        else:
                            write_log(f"FIGYELEM MS HIBA: Az offline rendszerleíró adatbázis nem található itt: {hive_path}")

                self.after(0, lambda: progress.stop())
                write_log("==== MINDEN FOLYAMAT BEFEJEZŐDÖTT ====")
                self.after(0, lambda: status_lbl.config(text="A visszaállítás befejeződött (az ablak biztonságosan bezárható)!"))
                
                def finish_state():
                    try:
                        close_btn.config(state=tk.NORMAL)
                        if hasattr(self, 'refresh_drivers'): self.refresh_drivers()
                        
                        # Set log frame color based on result code to visually inform user
                        if process.returncode == 0:
                            log_text.config(fg="#00FF00")   # green
                        else:
                            log_text.config(fg="#FFFF00")   # yellow/warning

                    except: pass
                self.after(0, finish_state)

            except Exception as e:
                import traceback
                error_msg = f"KATASZTRÓFÁLIS PROGRAMHIBA: {e}\n{traceback.format_exc()}"
                write_log(error_msg)
                
                def crash_gui():
                    try:
                        progress.stop()
                        status_lbl.config(text="KRITIKUS HIBA TÖRTÉNT! NÉZD MEG A LOGOT!", foreground="red")
                        log_text.config(fg="red")
                        close_btn.config(state=tk.NORMAL)
                    except: pass
                self.after(0, crash_gui)
            finally:
                if log_handle:
                    try:
                        log_handle.close()
                    except: pass

        import threading
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

    # Globális logolás beállítása miután már biztosan admin jogosultságunk van
    log_filename = os.path.join(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__), "driver_tool_debug.log")
    try:
        logging.basicConfig(
            filename=log_filename, 
            level=logging.DEBUG, 
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            encoding='utf-8'
        )
    except Exception as e:
        print(f"Logolasi hiba: {e}")
        logging.basicConfig(level=logging.DEBUG)

    logging.info("==================================================")
    logging.info("DRIVER TOOL ELINDITVA")
    logging.info(f"Futtatasi konyvtar: {os.getcwd()}")
    logging.info("==================================================")

    app = DriverCleanerApp()
    app.mainloop()
