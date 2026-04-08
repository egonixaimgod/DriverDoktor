BUILD_NUMBER = 20

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
    except Exception:
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
        self.title("ULTIMATE DRIVER GYILKOLO (es telepito) SZERVIZ TOOL")
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
        except Exception:
            pass
        
        # Configure fonts
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TLabelframe.Label", font=("Segoe UI", 11), foreground="#003366")
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        style.configure("Danger.TButton", font=("Segoe UI", 10), foreground="red")
        # Unified green progress bar style
        style.configure("Green.Horizontal.TProgressbar", troughcolor='#E0E0E0', background='#22AA22')
        
        # Ablak ikon beállítása (ico + PhotoImage fallback)
        icon_path = resource_path("icon_red.ico")
        try:
            self.iconbitmap(icon_path)
        except Exception:
            pass
        # PhotoImage fallback - ha az iconbitmap nem működik (pl. PyInstaller)
        try:
            from PIL import Image, ImageTk
            _icon_img = Image.open(icon_path)
            _icon_img = _icon_img.resize((32, 32), Image.LANCZOS)
            self._app_icon = ImageTk.PhotoImage(_icon_img)
            self.iconphoto(True, self._app_icon)
        except Exception:
            pass
        
        self.create_widgets()
        self.refresh_drivers()

    def create_widgets(self):
        # 0. Initialize variables missed during UI refactor
        import os
        self.sys_drive = os.path.splitdrive(os.environ.get('WINDIR', 'C:\\'))[0] + "\\"
        if not hasattr(self, 'target_os_path'):
            self.target_os_path = None

        # 1. Top Bar - OS Selector
        top_bar = tk.Frame(self, bg="#FFFFFF", padx=10, pady=10)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        
        target_title_lbl = ttk.Label(top_bar, text="Vizsgált Célpont:", font=("Segoe UI", 12, "bold"), foreground="#666666")
        target_title_lbl.pack(side=tk.LEFT, padx=(0, 5))
        
        self.target_lbl = ttk.Label(top_bar, text=f"JELENLEGI RENDSZER ({self.sys_drive})", font=("Segoe UI", 16, "bold"), foreground="#2e7d32")
        self.target_lbl.pack(side=tk.LEFT, padx=10)

        change_os_btn = ttk.Button(top_bar, text="Másik lemez kiválasztása", command=self.change_target_os, width=45)
        change_os_btn.pack(side=tk.LEFT, padx=5)

        reset_os_btn = ttk.Button(top_bar, text="Vissza (Jelenlegi lemez)", command=self.reset_target_os)
        reset_os_btn.pack(side=tk.LEFT, padx=5)


        # 2. Main Body Splitter
        main_body = tk.Frame(self, bg="#F3F3F3")
        main_body.pack(fill=tk.BOTH, expand=True)


        # 3. Sidebar on the left
        sidebar_frame = tk.Frame(main_body, bg="#E5F3FF", width=250)
        sidebar_frame.pack(side=tk.LEFT, fill=tk.Y)
        sidebar_frame.pack_propagate(False)
        
        ttk.Label(sidebar_frame, text="Kategóriák", font=("Segoe UI", 12, "bold"), foreground="#003366", background="#E5F3FF").pack(pady=15, padx=10, anchor="w")

        btn_drivers = ttk.Button(sidebar_frame, text="📦 Driverek kezelése", command=lambda: self.switch_view("drivers"))
        btn_drivers.pack(fill=tk.X, padx=10, pady=5)
        
        btn_backup = ttk.Button(sidebar_frame, text="💾 Mentés és Visszaállítás", command=lambda: self.switch_view("backup"))
        btn_backup.pack(fill=tk.X, padx=10, pady=5)

        btn_wu = ttk.Button(sidebar_frame, text="🔄 Windows Update", command=lambda: self.switch_view("wu"))
        btn_wu.pack(fill=tk.X, padx=10, pady=5)

        btn_hw = ttk.Button(sidebar_frame, text="🖥️ Hardver Infó & Telepítés", command=lambda: self.switch_view("hw"))
        btn_hw.pack(fill=tk.X, padx=10, pady=5)

        btn_autofix = ttk.Button(sidebar_frame, text="⚡ 1 Kattintásos Driver Fix", command=lambda: self.switch_view("autofix"))
        btn_autofix.pack(fill=tk.X, padx=10, pady=5)

        # 4. Content Area on the right
        self.content_frame = tk.Frame(main_body, bg="#FFFFFF")
        self.content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 5. Views
        self.driver_view = tk.Frame(self.content_frame, bg="#FFFFFF")
        self.backup_view = tk.Frame(self.content_frame, bg="#FFFFFF")
        self.wu_view = tk.Frame(self.content_frame, bg="#FFFFFF")
        self.hw_view = tk.Frame(self.content_frame, bg="#FFFFFF")
        self.autofix_view = tk.Frame(self.content_frame, bg="#FFFFFF")

        # variables:
        self.list_all_var = tk.BooleanVar(value=False)

        # -----------------------------
        # DRIVER VIEW CONTENT (Drivers list & removal)
        # -----------------------------
        drv_frame = ttk.LabelFrame(self.driver_view, text="Telepített Driverek Kezelése (Alapból csak a third party, windows telepítés után felrakott drivereket listázza, ha azt akarod hogy a gép összes driverét listázza akkor jobb alul a minden driver gombbal ezt is megteheted!)", padding=10)
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

        # Status bar a driver lista felett / alatt
        drv_status_frame = tk.Frame(self.driver_view, bg="#FFFFFF")
        drv_status_frame.pack(fill=tk.X, padx=5, pady=(2, 0))
        self.drv_status_lbl = ttk.Label(drv_status_frame, text="", font=("Segoe UI", 9))
        self.drv_status_lbl.pack(side=tk.LEFT, padx=5)
        self.drv_progress = ttk.Progressbar(drv_status_frame, orient=tk.HORIZONTAL, length=200,
                                             mode='indeterminate', style="Green.Horizontal.TProgressbar")
        self.drv_progress.pack(side=tk.RIGHT, padx=5)
        self.drv_progress.pack_forget()  # Alapból rejtett

        # Button frame for the grid
        btn_frame = tk.Frame(self.driver_view, bg="#FFFFFF")
        btn_frame.pack(fill=tk.X, pady=5)

        # Use grid for responsive layout
        refresh_btn = ttk.Button(btn_frame, text="Lista Frissítése (F5)", command=self.refresh_drivers)
        refresh_btn.grid(row=0, column=0, padx=5, pady=5)

        select_all_btn = ttk.Button(btn_frame, text="Összes Kijelölése", command=self.select_all_drivers)
        select_all_btn.grid(row=0, column=1, padx=5, pady=5)

        self.list_all_chk = ttk.Checkbutton(btn_frame, text="Minden Driver megjelenítése", variable=self.list_all_var, command=self.on_list_all_toggle)
        self.list_all_chk.grid(row=0, column=2, padx=5, pady=5)

        delete_btn = tk.Button(btn_frame, text="⚠ Kiválasztott Driver(ek) TÖRLÉSE ⚠", command=self.delete_selected_drivers,
                            bg="#CC0000", fg="white", activebackground="#990000", activeforeground="white",
                            font=("Segoe UI", 11, "bold"), relief=tk.RAISED, bd=2, padx=15, pady=6, cursor="hand2")
        delete_btn.grid(row=1, column=0, columnspan=3, pady=(5, 8), sticky="ew", padx=5)

        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)

        # -----------------------------
        # BACKUP & WIM VIEW CONTENT
        # -----------------------------
        backup_frame = ttk.LabelFrame(self.backup_view, text="Biztonsági Mentés (Driver Export és Visszaállítás)", padding=10)
        backup_frame.pack(fill=tk.X, padx=10, pady=10)

        rp_btn = ttk.Button(backup_frame, text="Új Rendszer-visszaállítási Pont", command=self.create_restore_point)
        rp_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        export_btn = ttk.Button(backup_frame, text="Third Party Driverek Lementése", command=self.backup_drivers)
        export_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        export_all_btn = ttk.Button(backup_frame, text="ÖSSZES Driver Lementése (Third Party + Windows)", command=self.backup_all_drivers)
        export_all_btn.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        restore_btn = ttk.Button(backup_frame, text="Lementett Driverek Visszaállítása", command=self.restore_drivers)
        restore_btn.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        backup_frame.columnconfigure(0, weight=1)
        backup_frame.columnconfigure(1, weight=1)

        wim_frame = ttk.LabelFrame(self.backup_view, text="Extrém Helyreállítás: Gyári Windows (Alap) Driverek Kinyerése (WINDOWS ISO-BÓL!)", padding=10)
        wim_frame.pack(fill=tk.X, padx=10, pady=10)

        wim_lbl = ttk.Label(wim_frame, text="Ha minden gyári driver törlődött (Billentyűzet, Touchpad, Standard USB), a Windows ISO-ból (install.wim-et betallózva) visszahozhatod!", font=("Segoe UI", 8), wraplength=480)
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

        disable_wu_btn = ttk.Button(wu_frame, text="Windows Update driver letiltas", command=self.disable_wu_drivers)
        disable_wu_btn.grid(row=1, column=0, padx=5, pady=5, sticky="ew")

        enable_wu_btn = ttk.Button(wu_frame, text="Windows Update driver engedélyezés", command=self.enable_wu_drivers)
        enable_wu_btn.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        restart_wu_btn = ttk.Button(wu_frame, text="⚡ Windows Update Szolgáltatások Újraindítása (Gyors Javítás)", command=self.restart_wu_services)
        restart_wu_btn.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        wu_frame.columnconfigure(0, weight=1)
        wu_frame.columnconfigure(1, weight=1)

        # -----------------------------
        # HARDWARE INFO & DRIVERS VIEW CONTENT
        # -----------------------------
        hw_frame = ttk.LabelFrame(self.hw_view, text="Rendszer és Hardver Információk", padding=10)
        hw_frame.pack(fill=tk.BOTH, expand=True, pady=0)

        top_hw_frame = tk.Frame(hw_frame, bg="#FFFFFF")
        top_hw_frame.pack(fill=tk.X, pady=(0, 10))

        self.sys_info_lbl = ttk.Label(top_hw_frame, text="Rendszer információk betöltése...", font=("Segoe UI", 11, "bold"), foreground="#003366")
        self.sys_info_lbl.pack(side=tk.LEFT, anchor="w")

        hardware_btn_frame = tk.Frame(hw_frame, bg="#FFFFFF")
        hardware_btn_frame.pack(fill=tk.X, pady=(0, 10))

        get_hw_btn = ttk.Button(hardware_btn_frame, text="🔍 Hardverek Scannelése", command=self.load_hardware_info)
        get_hw_btn.grid(row=0, column=0, padx=5, pady=5)

        self.install_hw_btn = ttk.Button(hardware_btn_frame, text="🚀 Kijelöltek Telepítése", command=self.install_wu_drivers, state=tk.DISABLED)
        self.install_hw_btn.grid(row=0, column=1, padx=5, pady=5)

        self.select_all_hw_btn = ttk.Button(hardware_btn_frame, text="☑ Összes kiválasztása", command=self._select_all_hw, state=tk.DISABLED)
        self.select_all_hw_btn.grid(row=0, column=2, padx=5, pady=5)

        self.deselect_all_hw_btn = ttk.Button(hardware_btn_frame, text="☐ Kijelölés törlése", command=self._deselect_all_hw, state=tk.DISABLED)
        self.deselect_all_hw_btn.grid(row=0, column=3, padx=5, pady=5)

        # Progress bar + részletes állapot
        progress_frame = tk.Frame(hw_frame, bg="#FFFFFF")
        progress_frame.pack(fill=tk.X, pady=(0, 6))

        self.hw_progress = ttk.Progressbar(progress_frame, mode='indeterminate', length=300, style="Green.Horizontal.TProgressbar")
        self.hw_progress.pack(side=tk.LEFT, padx=(0, 10))

        self.hw_status_lbl = tk.Label(progress_frame, text="", font=("Segoe UI", 9), fg="#555555", bg="#FFFFFF", anchor="w")
        self.hw_status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.hw_tree = ttk.Treeview(hw_frame, columns=("Select", "WUTitle", "HWID"), show="tree headings", height=14)
        self.hw_tree.heading("#0", text="Eszköz / Kategória")
        self.hw_tree.heading("Select", text="✓")
        self.hw_tree.heading("WUTitle", text="Elérhető WU driver csomag")
        self.hw_tree.heading("HWID", text="Azonosító (HWID)")
        self.hw_tree.column("#0", width=260, anchor="w")
        self.hw_tree.column("Select", width=30, anchor="center", stretch=False)
        self.hw_tree.column("WUTitle", width=300, anchor="w")
        self.hw_tree.column("HWID", width=180, anchor="w")

        self.hw_tree.tag_configure("category", font=("Segoe UI", 10, "bold"), background="#E5F3FF")
        self.hw_tree.tag_configure("checked", foreground="#006600")
        self.hw_tree.tag_configure("unchecked", foreground="#333333")
        self.hw_tree.tag_configure("separator", font=("Segoe UI", 9, "bold"), background="#D0D0D0", foreground="#555555")
        self.hw_tree.tag_configure("installed_cat", font=("Segoe UI", 9, "bold"), background="#E8F5E9", foreground="#2E7D32")
        self.hw_tree.tag_configure("installed", foreground="#888888")
        self.hw_tree.bind("<ButtonRelease-1>", self._on_hw_tree_click)

        self._hw_selected = {}  # iid -> pool_idx (int index into hw_updates_pool)

        hw_scrollbar = ttk.Scrollbar(hw_frame, orient=tk.VERTICAL, command=self.hw_tree.yview)
        self.hw_tree.configure(yscrollcommand=hw_scrollbar.set)
        hw_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.hw_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Show drivers by default
        self.driver_view.pack(fill=tk.BOTH, expand=True)

        # -----------------------------
        # AUTOFIX VIEW CONTENT
        # -----------------------------
        autofix_frame = ttk.LabelFrame(self.autofix_view, text="⚡ 1 Kattintásos Automatikus Driver Fix", padding=15)
        autofix_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        autofix_warn = ttk.Label(autofix_frame, text=(
            "Ez a funkció AUTOMATIKUSAN elvégzi a teljes driver újratelepítést:\n\n"
            "1️⃣  Windows Update driver keresés LETILTÁSA (registry + policy)\n"
            "2️⃣  Összes third-party (nem Windows gyári) driver TÖRLÉSE\n"
            "3️⃣  Hardver újraszkennelés (Windows alap driverek visszaállása)\n"
            "4️⃣  Windows Update-ről az összes elérhető driver LETÖLTÉSE és TELEPÍTÉSE\n"
            "5️⃣  Automatikus ÚJRAINDÍTÁS\n\n"
            "⚠️  A folyamat közben NE használd a gépet! A képernyő villoghat!\n"
            "⏱️  Becsült idő: 5-15 perc (internetsebesség és driverek számától függ)"
        ), font=("Segoe UI", 10), wraplength=550, justify=tk.LEFT)
        autofix_warn.pack(pady=(5, 15), anchor="w")

        self.autofix_btn = tk.Button(autofix_frame, text="⚡ INDÍTÁS: Teljes Driver Újratelepítés ⚡",
            command=self.one_click_driver_fix,
            bg="#FF6600", fg="white", activebackground="#CC5200", activeforeground="white",
            font=("Segoe UI", 14, "bold"), relief=tk.RAISED, bd=2, padx=20, pady=12, cursor="hand2")
        self.autofix_btn.pack(pady=(0, 15))

        # Build szám jobb alsó sarokban
        build_lbl = tk.Label(self, text=f"Build {BUILD_NUMBER:03d}", font=("Segoe UI", 8), fg="#999999", bg="#F3F3F3", anchor="e")
        build_lbl.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 2))

    def switch_view(self, view_name):
        self.driver_view.pack_forget()
        self.backup_view.pack_forget()
        self.wu_view.pack_forget()
        self.hw_view.pack_forget()
        self.autofix_view.pack_forget()
        
        if view_name == "drivers":
            self.driver_view.pack(fill=tk.BOTH, expand=True)
            self.tree.focus_set()
        elif view_name == "backup":
            self.backup_view.pack(fill=tk.BOTH, expand=True)
        elif view_name == "wu":
            self.wu_view.pack(fill=tk.BOTH, expand=True)
            self.check_wu_status()
        elif view_name == "hw":
            self.hw_view.pack(fill=tk.BOTH, expand=True)
            self.load_hardware_info()
        elif view_name == "autofix":
            self.autofix_view.pack(fill=tk.BOTH, expand=True)

    def change_target_os(self):
        d = filedialog.askdirectory(title="Válaszd ki a halott Windows meghajtóját (pl. C:\\ vagy D:\\, amin a Windows mappa van!)")
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
            
            result = subprocess.run(['pnputil', '/enum-drivers'], capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
            output = result.stdout
            
            drivers = []
            current_driver = {}
            
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    if current_driver and "published" in current_driver:
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

            if current_driver and "published" in current_driver:
                drivers.append(current_driver)
                
            return drivers
        except Exception as e:
            logging.error(f"Nem sikerült lekérdezni a drivereket: {e}")
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

    def _search_wu_api(self):
        """Windows Update COM API-n keresztül keres elérhető driver frissítéseket.
        Visszaad egy listát dict-ekkel, üres listát ha nincs frissítés, vagy None-t hiba esetén."""
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            ps_cmd = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    $Session = New-Object -ComObject Microsoft.Update.Session
    $Searcher = $Session.CreateUpdateSearcher()
    try {
        $SM = New-Object -ComObject Microsoft.Update.ServiceManager
        $SM.AddService2("7971f918-a847-4430-9279-4a52d1efe18d", 7, "") | Out-Null
    } catch {}
    $Searcher.ServerSelection = 3
    $Searcher.ServiceID = "7971f918-a847-4430-9279-4a52d1efe18d"
    $Result = $Searcher.Search("IsInstalled=0 and Type='Driver'")
    $updates = @()
    foreach ($U in $Result.Updates) {
        $updates += [PSCustomObject]@{
            Title = $U.Title
            DriverModel = $U.DriverModel
            HardwareID = $U.DriverHardwareID
            DriverClass = $U.DriverClass
            DriverProvider = $U.DriverProvider
            UpdateID = $U.Identity.UpdateID
            Size = $U.MaxDownloadSize
        }
    }
    if ($updates.Count -eq 0) { Write-Output "[]" }
    else { $updates | ConvertTo-Json -Depth 2 -Compress }
} catch {
    Write-Error $_.Exception.Message
}
"""
            logging.info("WU COM API PowerShell keresés indítása...")
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, encoding='utf-8', errors='replace',
                startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=300  # 5 perc timeout
            )
            logging.info(f"WU COM API PowerShell vége. ReturnCode: {res.returncode}, stdout len: {len(res.stdout)}")
            if res.stderr:
                logging.warning(f"WU COM API stderr: {res.stderr[:500]}")
            
            # Ha stderr hibát jelez és stdout üres → WU API hiba
            out = res.stdout.strip()
            if not out and res.stderr:
                logging.error("WU COM API hiba: nincs stdout, stderr tartalmaz hibát")
                return None
            if out:
                import json
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                logging.info(f"WU COM API talált {len(data)} db frissítést")
                return data if isinstance(data, list) else None
        except subprocess.TimeoutExpired:
            logging.error("WU COM API keresés timeout (300s)")
        except Exception as e:
            logging.error(f"WU COM API keresés hiba: {e}")
        return None

    def _create_progress_window(self, title, message, width=600, height=350, mode='determinate', maximum=100, has_log=True):
        """Unified progress window with green bar and X/Y counter label."""
        prog_win = tk.Toplevel(self)
        prog_win.title(title)
        prog_win.geometry(f"{width}x{height}")
        prog_win.transient(self)
        prog_win.grab_set()

        lbl = ttk.Label(prog_win, text=message, justify=tk.CENTER, font=("Segoe UI", 10))
        lbl.pack(pady=(10, 5))

        counter_lbl = ttk.Label(prog_win, text="", font=("Segoe UI", 10, "bold"))
        counter_lbl.pack(pady=(0, 2))

        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=width - 80, mode=mode, style="Green.Horizontal.TProgressbar")
        progress.pack(pady=5)
        if mode == 'determinate':
            progress.config(maximum=maximum)
        else:
            progress.start(15)

        status_lbl = ttk.Label(prog_win, text="Inicializálás...", font=("Segoe UI", 9))
        status_lbl.pack(pady=(2, 5))

        log_text = None
        if has_log:
            text_frame = tk.Frame(prog_win)
            text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
            log_text = tk.Text(text_frame, height=10, state=tk.DISABLED, bg="#F3F3F3", font=("Consolas", 9))
            log_scroll = ttk.Scrollbar(text_frame, command=log_text.yview)
            log_text.configure(yscrollcommand=log_scroll.set)
            log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def append_log(msg):
            logging.info(msg)
            if log_text is None:
                return
            log_text.config(state=tk.NORMAL)
            log_text.insert(tk.END, msg + "\n")
            log_text.see(tk.END)
            log_text.config(state=tk.DISABLED)

        return prog_win, progress, status_lbl, counter_lbl, log_text, append_log

    def load_hardware_info(self):
        if hasattr(self, '_hw_scanning') and self._hw_scanning:
            return
        self._hw_scanning = True
        
        self.sys_info_lbl.config(text="🔍 Hardverek ellenőrzése folyamatban... Kérlek várj!")
        self.hw_status_lbl.config(text="⏳ PnP eszközök lekérdezése a Windowstól...")
        self.hw_progress.config(mode='indeterminate')
        self.hw_progress.start(15)
        for item in self.hw_tree.get_children():
            self.hw_tree.delete(item)

        def worker():
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            sys_info_text = "Ismeretlen PC / Laptop"
            
            try:
                ps_cmd = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-WmiObject Win32_ComputerSystem | Select-Object Manufacturer, Model, PCSystemType | ConvertTo-Json"
                res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, encoding='utf-8', startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
                if res.stdout.strip():
                    import json
                    try:
                        data = json.loads(res.stdout.strip())
                        man = data.get("Manufacturer", "").strip()
                        mod = data.get("Model", "").strip()
                        pct = data.get("PCSystemType", -1)
                        is_laptop = (pct == 2)
                        prefix = "💻 Laptop" if is_laptop else "🖥️ Asztali (Desktop)"
                        sys_info_text = f"{prefix} | {man} - {mod}"
                    except json.JSONDecodeError:
                        pass
            except Exception:
                pass
            
            self.after(0, lambda html_t=sys_info_text: self.sys_info_lbl.config(text=html_t))

            self.after(0, lambda: self.install_hw_btn.config(state=tk.DISABLED, text="🚀 Kijelöltek Telepítése"))
            self.after(0, lambda: self.select_all_hw_btn.config(state=tk.DISABLED))
            self.after(0, lambda: self.deselect_all_hw_btn.config(state=tk.DISABLED))
            self.hw_updates_pool = []

            # HWID extrahálás (VEN_XXXX&DEV_YYYY, VID_XXXX&PID_YYYY, ACPI\XXXX)
            def extract_hwid(pnp_id):
                if not pnp_id: return None
                # PCI: VEN_XXXX&DEV_YYYY
                m_pci = re.search(r'(VEN_[0-9A-F]+&DEV_[0-9A-F]+)', pnp_id, re.I)
                if m_pci: return m_pci.group(1)
                # USB: VID_XXXX&PID_YYYY
                m_usb = re.search(r'(VID_[0-9A-F]+&PID_[0-9A-F]+)', pnp_id, re.I)
                if m_usb: return m_usb.group(1)
                # ACPI: ACPI\XXXXX
                m_acpi = re.search(r'(ACPI\\[A-Z0-9_]+)', pnp_id, re.I)
                if m_acpi: return m_acpi.group(1)
                # HDAUDIO: HDAUDIO\FUNC_XX&VEN_XXXX&DEV_XXXX
                m_hda = re.search(r'(HDAUDIO\\FUNC_[0-9A-F]+&VEN_[0-9A-F]+&DEV_[0-9A-F]+)', pnp_id, re.I)
                if m_hda: return m_hda.group(1)
                # HID eszközök VID/PID-vel: HID\VID_XXXX&PID_XXXX
                m_hid = re.search(r'HID\\(VID_[0-9A-F]+&PID_[0-9A-F]+)', pnp_id, re.I)
                if m_hid: return m_hid.group(1)
                # USB eszköz VID/PID prefix nélkül: USB\VID_XXXX&PID_XXXX
                m_usb2 = re.search(r'USB\\(VID_[0-9A-F]+&PID_[0-9A-F]+)', pnp_id, re.I)
                if m_usb2: return m_usb2.group(1)
                # DISPLAY\XXXX (monitor/GPU)
                m_disp = re.search(r'(DISPLAY\\[A-Z0-9]+)', pnp_id, re.I)
                if m_disp: return m_disp.group(1)
                # SWD driver enum eszközök: kihagyjuk (nyomtatók, szoftveres eszközök) — nincs WU driver hozzá
                # STORAGE, USBSTOR, SCSI: kihagyjuk — nincs WU driver hozzá
                return None

            devices_to_check = []

            # 2. MINDEN Plug & Play eszköz lekérdezése, aminek van értelmezhető HWID-ja
            ignored_classes = ['Volume', 'VolumeSnapshot', 'DiskDrive', 'CDROM', 'Monitor', 'Battery', 'SoftwareDevice', 'SoftwareComponent', 'Processor', 'Computer', 'LegacyDriver', 'Endpoint', 'AudioEndpoint', 'PrintQueue', 'Printer', 'WPD']
            
            # Kicsit bolondbiztosabb lekérdezés: minden eszközt lehúzunk, pythonban szűrjük a $null miatti bugok helyett
            def pull_pnp():
                self.after(0, lambda: self.sys_info_lbl.config(text=f"{sys_info_text} | ⏳ Hardverlista letöltése a Windowstól... (Várj)"))
                try:
                    logging.info("Indul a powershell lekérdezés: Get-WmiObject Win32_PnPEntity")
                    cmd_pnp = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-WmiObject Win32_PnPEntity | Select-Object Name, PNPClass, PNPDeviceID | ConvertTo-Json -Compress"
                    res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd_pnp], capture_output=True, encoding='utf-8', errors='replace', startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
                    
                    logging.info(f"Powershell lekérdezés vége! ReturnCode: {res.returncode}")
                    if res.returncode != 0:
                        logging.error(f"PNP Powershell Hiba kód={res.returncode}. STDERR kim: {res.stderr}\nSTDOUT kim: {res.stdout[:300]}")
                    
                    if res.stdout:
                        import json
                        out = json.loads(res.stdout)
                        logging.info(f"JSON decodolas sikeres! {len(out) if isinstance(out, list) else 1} elem parseolva.")
                        return out if isinstance(out, list) else [out]
                    else:
                        logging.error("NINCS STDOUT (Üres a JSON). Valami megfogta a PowerShellt.")
                except Exception as ex:  # noqa: bare except fixed
                    import traceback
                    logging.error(f"PNP Query Váratlan Python Hiba:\n{traceback.format_exc()}")
                return []
            
            pnp_data = pull_pnp()
            logging.info(f"PnP feldolgozando elemek szama: {len(pnp_data)}")
            self.after(0, lambda _n=len(pnp_data): self.hw_status_lbl.config(text=f"📋 {_n} PnP eszköz szűrése..."))
            
            # Diagnosztika: első 5 nyers PnP elem kiloggolása
            for _di, _dd in enumerate(pnp_data[:5]):
                logging.info(f"PnP MINTA [{_di}]: Name={_dd.get('Name','?')!r}, PNPClass={_dd.get('PNPClass','?')!r}, PNPDeviceID={_dd.get('PNPDeviceID','?')!r}")
            
            seen_hwids = set()
            skipped_no_pid = 0
            skipped_virtual = 0
            skipped_root = 0
            skipped_class = 0
            skipped_no_hwid = 0
            skipped_dup = 0
            skipped_no_hwid_samples = []
            for d in pnp_data:
                n = d.get("Name") or "Ismeretlen Eszköz"
                pid = d.get("PNPDeviceID") or ""
                pclass = d.get("PNPClass") or ""
                
                # Kiszűrjük a virtuális, szoftveres és irreleváns cuccokat
                if not pid:
                    skipped_no_pid += 1
                    continue
                if "virtual" in n.lower() or "pseudo" in n.lower() or "vmware" in n.lower():
                    skipped_virtual += 1
                    continue
                if pid.upper().startswith("ROOT\\"):
                    skipped_root += 1
                    continue
                if pclass in ignored_classes:
                    skipped_class += 1
                    continue
                
                hwid_clean = extract_hwid(pid)
                if not hwid_clean:
                    skipped_no_hwid += 1
                    if len(skipped_no_hwid_samples) < 15:
                        skipped_no_hwid_samples.append(f"{n} | PID={pid} | class={pclass}")
                    continue
                if hwid_clean in seen_hwids:
                    skipped_dup += 1
                    continue
                
                seen_hwids.add(hwid_clean)
                
                # Kategória finomhangolása
                if pclass == "Display": cat = "🎮 Videókártya (VGA)"
                elif pclass == "Media": cat = "🎵 Hangkártya (Audio)"
                elif pclass == "Net": cat = "🌐 Hálózat (LAN/Wi-Fi)"
                elif pclass == "Bluetooth": cat = "🔵 Bluetooth"
                elif pclass == "System": cat = "⚙️ Rendszereszköz"
                elif pclass == "USB": cat = "🔌 USB Vezérlő"
                elif pclass == "Camera" or pclass == "Image": cat = "📷 Webkamera"
                elif pclass == "Mouse" or pclass == "Keyboard" or pclass == "HIDClass": cat = "🖱️ Periféria"
                elif pclass == "Biometric": cat = "🔒 Ujjlenyomat / Biometria"
                else: cat = f"🔧 Egyéb ({pclass})"
                
                devices_to_check.append({"cat": cat, "name": n, "id": hwid_clean, "pnp_id": pid})

            logging.info(f"PnP szures eredmenye: {len(devices_to_check)} eszkoz atment a szuron. "
                         f"Kiszurve: no_pid={skipped_no_pid}, virtual={skipped_virtual}, root={skipped_root}, "
                         f"class={skipped_class}, no_hwid={skipped_no_hwid}, dup={skipped_dup}")
            if skipped_no_hwid_samples:
                logging.info(f"no_hwid miatt kiszurt eszkozok mintai ({len(skipped_no_hwid_samples)}):")
                for _s in skipped_no_hwid_samples:
                    logging.info(f"  SKIP_NO_HWID: {_s}")
            # Átmenő eszközök logja
            for _dd in devices_to_check[:10]:
                logging.info(f"  PASSED: {_dd['name']} => HWID={_dd['id']} cat={_dd['cat']}")
            
            self.after(0, lambda _n=len(devices_to_check): self.hw_status_lbl.config(text=f"✅ {_n} eszköz azonosítva, WU keresés indul..."))

            # WU keresés háttérszálon — a treeview-t NEM töltjük fel előre, csak az eredményt mutatjuk
            def start_wu_search():
                def wu_search_thread():
                  try:
                    total_devs = len(devices_to_check)
                    
                    # Progress bar indítása
                    self.after(0, lambda: self.hw_progress.config(mode='indeterminate'))
                    self.after(0, lambda: self.hw_progress.start(15))
                    self._wu_search_cancelled = False
                    
                    # Eltelt idő kijelző
                    _start_time = time.time()
                    def _update_elapsed():
                        if self._wu_search_cancelled:
                            return
                        elapsed = int(time.time() - _start_time)
                        m, s = divmod(elapsed, 60)
                        time_str = f"{m}:{s:02d}" if m else f"{s} mp"
                        phase = getattr(self, '_wu_phase', '')
                        self.hw_status_lbl.config(text=f"{phase}  ⏱ {time_str}")
                        self.after(1000, _update_elapsed)
                    self.after(0, _update_elapsed)
                    
                    self.after(0, lambda: self.sys_info_lbl.config(
                        text=f"{sys_info_text} | ⏳ Driver keresés folyamatban..."))
                    
                    self.hw_updates_pool = []
                    self._hw_installed_devs = []
                    self.wu_api_mode = True
                    
                    # --- 1. FÁZIS: WU COM API keresés ---
                    self._wu_phase = f"🔍 Fázis 1/2: WU szerver lekérdezése ({total_devs} eszköz)..."
                    logging.info("WU COM API driver keresés indítása...")
                    wu_results = self._search_wu_api()
                    wu_api_success = wu_results is not None  # None = hiba, [] = nincs frissítés (mind telepítve)
                    if wu_results is None:
                        wu_results = []
                    
                    self._wu_phase = f"📋 Fázis 2/2: Eredmények feldolgozása..."
                    matched_hwids = set()
                    if wu_results:
                        logging.info(f"WU COM API {len(wu_results)} db elérhető driver frissítést talált!")
                        _match_idx = 0
                        for wu in wu_results:
                            _match_idx += 1
                            wu_hwid_raw = (wu.get('HardwareID') or '').upper()
                            wu_title = wu.get('Title', '')
                            wu_model = wu.get('DriverModel', '')
                            self.after(0, lambda _i=_match_idx, _tot=len(wu_results), _t=wu_title[:50]:
                                self.hw_status_lbl.config(text=f"📋 Egyeztetés: {_i}/{_tot} — {_t}"))
                            
                            for dev in devices_to_check:
                                if dev['id'] in matched_hwids:
                                    continue
                                dev_hwid = dev['id'].upper()
                                dev_pnp = dev.get('pnp_id', '').upper()
                                
                                if (dev_hwid and dev_hwid in wu_hwid_raw) or \
                                   (wu_hwid_raw and wu_hwid_raw in dev_pnp):
                                    matched_hwids.add(dev['id'])
                                    self.hw_updates_pool.append({
                                        "name": dev['name'],
                                        "cat": dev['cat'],
                                        "hwid": dev['id'],
                                        "wu_title": wu_title,
                                        "pnp_id": dev.get('pnp_id', '')
                                    })
                                    break
                        
                        # WU-hoz nem illeszthető frissítések (más eszközosztály)
                        for wu in wu_results:
                            wu_hwid_raw = (wu.get('HardwareID') or '').upper()
                            if not wu_hwid_raw:
                                continue
                            already_matched = False
                            for dev in devices_to_check:
                                if dev['id'].upper() in wu_hwid_raw or wu_hwid_raw in dev.get('pnp_id', '').upper():
                                    already_matched = True
                                    break
                            if not already_matched:
                                wu_title = wu.get('Title', 'Ismeretlen WU driver')
                                self.hw_updates_pool.append({
                                    "name": wu.get('DriverModel', wu_title),
                                    "cat": "🔄 WU Driver",
                                    "hwid": wu_hwid_raw,
                                    "wu_title": wu_title,
                                    "pnp_id": ''
                                })
                    
                    # Telepített (nincs WU frissítés) eszközök gyűjtése
                    self._hw_installed_devs = [dev for dev in devices_to_check if dev['id'] not in matched_hwids]
                    
                    # --- 2. FÁZIS: Katalógus fallback CSAK ha WU API HIBÁT DOBOTT (nem ha 0 találat) ---
                    if not self.hw_updates_pool and not wu_api_success:
                        self.wu_api_mode = False
                        logging.info("WU COM API nem talált frissítést, fallback: MS Update Catalog webes keresés...")
                        self._wu_phase = f"🌐 Katalógus keresés ({total_devs} eszköz)..."
                        self.after(0, lambda: self.hw_progress.stop())
                        self.after(0, lambda: self.hw_progress.config(mode='determinate', maximum=total_devs, value=0))
                        self.after(0, lambda: self.sys_info_lbl.config(
                            text=f"{sys_info_text} | 🔎 WU API üres, MS katalógus ellenőrzés ({total_devs} eszköz)..."))
                        
                        import urllib.request, urllib.parse, ssl
                        ssl_ctx = ssl.create_default_context()
                        
                        checked_devs = 0
                        lock = threading.Lock()
                        
                        def check_catalog(item_dict):
                            nonlocal checked_devs
                            cat = item_dict['cat']
                            name = item_dict['name']
                            hwid = item_dict['id']
                            pnp_id = item_dict.get('pnp_id', '')
                            try:
                                url = 'https://www.catalog.update.microsoft.com/Search.aspx?q=' + urllib.parse.quote(hwid)
                                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                                html = urllib.request.urlopen(req, context=ssl_ctx, timeout=30).read().decode('utf-8')
                                match_ids = re.findall(r"id=['\"]([a-fA-F0-9\-]+)_link['\"]", html)
                                
                                best_id = match_ids[0] if match_ids else None
                                
                                if best_id:
                                    dl_post_body = f'updateIDs=[{{"size":0,"languages":"","uidInfo":"{best_id}","updateID":"{best_id}"}}]'
                                    dl_req = urllib.request.Request(
                                        'https://www.catalog.update.microsoft.com/DownloadDialog.aspx',
                                        data=dl_post_body.encode('utf-8'),
                                        headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/x-www-form-urlencoded'})
                                    dl_html = urllib.request.urlopen(dl_req, context=ssl_ctx, timeout=30).read().decode('utf-8')
                                    cab_link = re.search(r'downloadInformation\[0\]\.files\[0\]\.url\s*=\s*[\"\']([^\"\']+)[\"\']', dl_html)
                                    
                                    if cab_link:
                                        dl_target = cab_link.group(1)
                                        logging.info(f"Katalógus találat: {name} (HWID={hwid}). Link: {dl_target}")
                                        with lock:
                                            self.hw_updates_pool.append({"name": name, "cat": cat, "hwid": hwid, "url": dl_target, "pnp_id": pnp_id, "wu_title": f"MS Katalógus: {name}"})
                                        return
                            except Exception as e:
                                logging.error(f"Katalógus hiba ({name} / HWID={hwid}): {e}")
                            finally:
                                with lock:
                                    checked_devs += 1
                                    _cd = checked_devs
                                    self.after(0, lambda _c=_cd:
                                        self.hw_progress.config(value=_c))
                                    self.after(0, lambda _c=_cd, _n=name:
                                        self.hw_status_lbl.config(text=f"🔎 {_c}/{total_devs}: {_n[:40]}"))
                        
                        import queue
                        q = queue.Queue()
                        for dev in devices_to_check:
                            q.put(dev)
                        
                        def catalog_worker():
                            while not q.empty():
                                try:
                                    dev = q.get_nowait()
                                except Exception:
                                    break
                                check_catalog(dev)
                                q.task_done()
                        
                        cat_threads = []
                        for _ in range(5):
                            t = threading.Thread(target=catalog_worker, daemon=True)
                            t.start()
                            cat_threads.append(t)
                        for t in cat_threads:
                            t.join(timeout=120)
                        
                        # Katalógus után újraszámoljuk a telepített eszközöket
                        catalog_hwids = {drv['hwid'] for drv in self.hw_updates_pool}
                        self._hw_installed_devs = [dev for dev in devices_to_check if dev['id'] not in catalog_hwids]
                    
                    # --- 3. FÁZIS: Eredmények megjelenítése kategorizálva ---
                    found = len(self.hw_updates_pool)
                    self._wu_search_cancelled = True
                    elapsed_total = int(time.time() - _start_time)
                    _em, _es = divmod(elapsed_total, 60)
                    _time_final = f"{_em} perc {_es} mp" if _em else f"{_es} mp"
                    self.after(0, lambda: self.hw_progress.stop())
                    self.after(0, lambda: self.hw_progress.config(mode='determinate', maximum=100, value=100))
                    
                    mode_txt = "WU API" if self.wu_api_mode else "Katalógus"
                    installed_count = len(self._hw_installed_devs)
                    if found > 0:
                        self.after(0, lambda _tf=_time_final, _f=found, _ic=installed_count:
                            self.hw_status_lbl.config(text=f"✅ Kész! {_f} letölthető + {_ic} telepített driver, idő: {_tf}"))
                        self.after(0, lambda _txt=sys_info_text, _f=found, _t=total_devs, _m=mode_txt:
                            self.sys_info_lbl.config(text=f"{_txt} | ✅ Kész ({_m})! {_f} frissítés elérhető ({_t} eszköz vizsgálva)"))
                        self.after(0, self._populate_hw_results)
                    else:
                        self.after(0, lambda _tf=_time_final, _ic=installed_count:
                            self.hw_status_lbl.config(text=f"✅ Minden driver naprakész! ({_ic} eszköz, idő: {_tf})"))
                        self.after(0, lambda _txt=sys_info_text, _t=total_devs, _m=mode_txt:
                            self.sys_info_lbl.config(text=f"{_txt} | ✅ Kész ({_m})! Minden driver naprakész ({_t} eszköz vizsgálva)"))
                        self.after(0, self._populate_hw_results)  # Telepített eszközök mutatása is
                    
                    self.after(0, lambda: setattr(self, '_hw_scanning', False))
                  except Exception as _wse:
                    logging.error(f"wu_search_thread crash: {_wse}")
                    import traceback
                    logging.error(traceback.format_exc())
                    self._wu_search_cancelled = True
                    self.after(0, lambda: self.hw_progress.stop())
                    self.after(0, lambda: self.hw_progress.config(mode='determinate', maximum=100, value=0))
                    self.after(0, lambda: self.hw_status_lbl.config(text="❌ Hiba történt a WU keresésnél!"))
                    self.after(0, lambda: self.sys_info_lbl.config(text="❌ WU keresés hiba! Próbáld újra."))
                  finally:
                    self.after(0, lambda: setattr(self, '_hw_scanning', False))
                
                threading.Thread(target=wu_search_thread, daemon=True).start()
            
            # Háttérszálon indítjuk a WU keresést
            self.after(0, start_wu_search)

        def safe_worker():
            try:
                worker()
            except Exception as exc:
                logging.error(f"load_hardware_info worker crashed: {exc}")
                import traceback
                logging.error(traceback.format_exc())
                self.after(0, lambda: self.hw_progress.stop())
                self.after(0, lambda: self.hw_progress.config(mode='determinate', maximum=100, value=0))
                self.after(0, lambda: self.hw_status_lbl.config(text="❌ Hiba történt!"))
                self.after(0, lambda: self.sys_info_lbl.config(text="❌ Hardver scan hiba! Próbáld újra."))
                self.after(0, lambda: setattr(self, '_hw_scanning', False))
                self._wu_search_cancelled = True

        threading.Thread(target=safe_worker, daemon=True).start()

    def _populate_hw_results(self):
        """Kategorizált treeview feltöltése: felül letölthető, alul telepített driverek."""
        # Treeview kiürítése
        for item in self.hw_tree.get_children():
            self.hw_tree.delete(item)
        self._hw_selected = {}
        
        # Kategória sorrend
        cat_order = [
            "🎮 Videókártya (VGA)", "🎵 Hangkártya (Audio)", "🌐 Hálózat (LAN/Wi-Fi)",
            "🔵 Bluetooth", "📷 Webkamera", "🖱️ Periféria", "🔒 Ujjlenyomat / Biometria",
            "🔌 USB Vezérlő", "⚙️ Rendszereszköz", "🔄 WU Driver"
        ]
        
        def sort_cats(cat_dict):
            sorted_list = []
            for c in cat_order:
                if c in cat_dict:
                    sorted_list.append(c)
            for c in cat_dict:
                if c not in sorted_list:
                    sorted_list.append(c)
            return sorted_list
        
        # === FELSŐ RÉSZ: Letölthető driverek ===
        if self.hw_updates_pool:
            cats = {}
            for idx, drv in enumerate(self.hw_updates_pool):
                cat = drv.get('cat', '🔧 Egyéb')
                if cat not in cats:
                    cats[cat] = []
                cats[cat].append((idx, drv))
            
            for cat_name in sort_cats(cats):
                items = cats[cat_name]
                cat_iid = self.hw_tree.insert("", tk.END, text=f"⬇️ {cat_name}  ({len(items)} db)", 
                                              values=("", "", ""), tags=("category",), open=True)
                
                for pool_idx, drv in items:
                    wu_title = drv.get('wu_title', '')
                    title_short = wu_title[:55] + '...' if len(wu_title) > 55 else wu_title
                    hwid = drv.get('hwid', '')
                    name = drv.get('name', 'Ismeretlen')
                    
                    iid = self.hw_tree.insert(cat_iid, tk.END, text=f"  {name}",
                                              values=("☑", title_short, hwid), tags=("checked",))
                    self._hw_selected[iid] = pool_idx
            
            # Gombok engedélyezése
            self.install_hw_btn.config(state=tk.NORMAL)
            self.select_all_hw_btn.config(state=tk.NORMAL)
            self.deselect_all_hw_btn.config(state=tk.NORMAL)
        else:
            # Nincs letölthető driver → gombok letiltása
            self.install_hw_btn.config(state=tk.DISABLED, text="🚀 Kijelöltek Telepítése")
            self.select_all_hw_btn.config(state=tk.DISABLED)
            self.deselect_all_hw_btn.config(state=tk.DISABLED)
        
        # === ALSÓ RÉSZ: Már telepített (naprakész) driverek ===
        installed_devs = getattr(self, '_hw_installed_devs', [])
        if installed_devs:
            inst_cats = {}
            for dev in installed_devs:
                cat = dev.get('cat', '🔧 Egyéb')
                if cat not in inst_cats:
                    inst_cats[cat] = []
                inst_cats[cat].append(dev)
            
            # Elválasztó sor
            sep_iid = self.hw_tree.insert("", tk.END, text="━━━━━━━━━━━━ ✅ Telepített / Naprakész driverek ━━━━━━━━━━━━",
                                          values=("", "", ""), tags=("separator",), open=False)
            
            for cat_name in sort_cats(inst_cats):
                items = inst_cats[cat_name]
                cat_iid = self.hw_tree.insert("", tk.END, text=f"✅ {cat_name}  ({len(items)} db)",
                                              values=("", "", ""), tags=("installed_cat",), open=False)
                
                for dev in items:
                    self.hw_tree.insert(cat_iid, tk.END, text=f"  {dev['name']}",
                                        values=("✅", "Naprakész", dev.get('id', '')), tags=("installed",))

    def _on_hw_tree_click(self, event):
        """Kattintásra checkbox toggle a treeview-ban."""
        iid = self.hw_tree.identify_row(event.y)
        
        if not iid:
            return
        
        tags = self.hw_tree.item(iid, 'tags')
        
        # Separator, telepített sorok: nem kattinthatóak
        if 'separator' in tags or 'installed_cat' in tags or 'installed' in tags:
            return
        
        # Kategória sorokra kattintás: összesét toggle alatta
        if 'category' in tags:
            children = self.hw_tree.get_children(iid)
            if not children:
                return
            # Ha bármelyik checked, mindet uncheckre; különben mindet checkre
            any_checked = any(self.hw_tree.item(c, 'values')[0] == '☑' for c in children)
            new_state = '☐' if any_checked else '☑'
            new_tag = 'unchecked' if any_checked else 'checked'
            for child in children:
                vals = list(self.hw_tree.item(child, 'values'))
                vals[0] = new_state
                self.hw_tree.item(child, values=vals, tags=(new_tag,))
            self._recalc_selected()
            return
        
        # Driver sorokra: toggle
        if iid not in self._hw_selected:
            return
        
        vals = list(self.hw_tree.item(iid, 'values'))
        if vals[0] == '☑':
            vals[0] = '☐'
            self.hw_tree.item(iid, values=vals, tags=('unchecked',))
        else:
            vals[0] = '☑'
            self.hw_tree.item(iid, values=vals, tags=('checked',))
        self._recalc_selected()

    def _recalc_selected(self):
        """Számoljuk újra a kijelölt driverek számát és frissítjük a gombot."""
        count = 0
        for iid in self._hw_selected:
            try:
                vals = self.hw_tree.item(iid, 'values')
                if vals and vals[0] == '☑':
                    count += 1
            except Exception:
                pass
        if count > 0:
            self.install_hw_btn.config(text=f"🚀 Kijelöltek Telepítése ({count} db)", state=tk.NORMAL)
        else:
            self.install_hw_btn.config(text="🚀 Kijelöltek Telepítése", state=tk.DISABLED)

    def _select_all_hw(self):
        """Összes driver kiválasztása."""
        for iid in self._hw_selected:
            try:
                vals = list(self.hw_tree.item(iid, 'values'))
                vals[0] = '☑'
                self.hw_tree.item(iid, values=vals, tags=('checked',))
            except Exception:
                pass
        self._recalc_selected()

    def _deselect_all_hw(self):
        """Összes kijelölés törlése."""
        for iid in self._hw_selected:
            try:
                vals = list(self.hw_tree.item(iid, 'values'))
                vals[0] = '☐'
                self.hw_tree.item(iid, values=vals, tags=('unchecked',))
            except Exception:
                pass
        self._recalc_selected()

    def install_wu_drivers(self):
        if not hasattr(self, 'hw_updates_pool') or not self.hw_updates_pool:
            messagebox.showinfo("Nincs frissítés",
                "Nem található telepíthető driver frissítés.\n\n"
                "Lehetséges okok:\n"
                "• Minden driver naprakész a rendszeren\n"
                "• A Windows Update szerver nem érhető el\n"
                "• Próbáld meg újra a 'Hardverek Scannelése' gombbal")
            return
        
        # Kijelölt driverek szűrése
        selected_pool = []
        for iid, pool_idx in self._hw_selected.items():
            try:
                vals = self.hw_tree.item(iid, 'values')
                if vals and vals[0] == '☑' and 0 <= pool_idx < len(self.hw_updates_pool):
                    selected_pool.append(self.hw_updates_pool[pool_idx])
            except Exception:
                pass
        
        if not selected_pool:
            messagebox.showinfo("Nincs kijelölve", "Nincs kijelölt driver a telepítéshez.\nJelöld ki a kívánt drivereket a listában!")
            return
        
        # Kijelölt driverek mentése telepítéshez (nem írjuk felül a teljes pool-t)
        self._install_pool = selected_pool
        
        # WU API mód: a Windows Update COM API-n keresztül telepítünk (megbízhatóbb)
        if hasattr(self, 'wu_api_mode') and self.wu_api_mode:
            self._install_via_wu_api()
        else:
            self._install_via_catalog()

    def _install_via_wu_api(self):
        """Windows Update COM API-n keresztüli letöltés és telepítés."""
        prog_win, progress, status_lbl, counter_lbl, log_text, append_log = self._create_progress_window(
            "WU Driver Telepítés (Windows Update API)",
            f"{len(self._install_pool)} db driver frissítés letöltése és telepítése\nWindows Update COM API-n keresztül...",
            width=650, height=420, mode='indeterminate'
        )

        def worker():
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            # HWID-ok átadása a PS scriptnek, hogy csak a releváns drivereket telepítse
            pool_hwids = [drv.get('hwid', '').upper() for drv in self._install_pool if drv.get('hwid')]
            hwid_list_ps = ','.join(f'"{h}"' for h in pool_hwids)

            ps_script = '$TargetHWIDs = @(' + hwid_list_ps + ')\n' + r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    Write-Output "INIT: Windows Update Session létrehozása..."
    $Session = New-Object -ComObject Microsoft.Update.Session
    $Searcher = $Session.CreateUpdateSearcher()
    
    try {
        $SM = New-Object -ComObject Microsoft.Update.ServiceManager
        $SM.AddService2("7971f918-a847-4430-9279-4a52d1efe18d", 7, "") | Out-Null
    } catch {}
    $Searcher.ServerSelection = 3
    $Searcher.ServiceID = "7971f918-a847-4430-9279-4a52d1efe18d"
    
    Write-Output "SEARCH: Driver frissítések keresése..."
    $Result = $Searcher.Search("IsInstalled=0 and Type='Driver'")
    
    if ($Result.Updates.Count -eq 0) {
        Write-Output "EMPTY: Nem található elérhető driver frissítés."
        return
    }
    
    $ToInstall = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($U in $Result.Updates) {
        # Csak a kiválasztott HWID-okhoz tartozó drivereket telepítsük
        $matchFound = $false
        if ($TargetHWIDs.Count -eq 0) {
            $matchFound = $true
        } else {
            foreach ($hwid in $U.DriverHardwareID) {
                $hUpper = $hwid.ToUpper()
                foreach ($target in $TargetHWIDs) {
                    if ($hUpper.Contains($target) -or $target.Contains($hUpper)) {
                        $matchFound = $true
                        break
                    }
                }
                if ($matchFound) { break }
            }
        }
        if (-not $matchFound) {
            Write-Output "SKIP: $($U.Title) - nem egyezik a kiválasztott eszközökkel"
            continue
        }
        if (-not $U.EulaAccepted) { $U.AcceptEula() }
        $ToInstall.Add($U) | Out-Null
        Write-Output "FOUND: $($U.Title) [$($U.DriverModel)]"
    }
    
    if ($ToInstall.Count -eq 0) {
        Write-Output "EMPTY: Nem található egyező driver frissítés a kiválasztott eszközökhöz."
        return
    }
    
    $total = $ToInstall.Count
    Write-Output "TOTAL: $total"
    
    $successCount = 0
    $failCount = 0
    
    for ($i = 0; $i -lt $total; $i++) {
        $U = $ToInstall.Item($i)
        $title = $U.Title
        $idx = $i + 1
        
        # Egyedi letöltés
        Write-Output "DLONE: $idx/$total $title"
        $SingleColl = New-Object -ComObject Microsoft.Update.UpdateColl
        $SingleColl.Add($U) | Out-Null
        
        $Downloader = $Session.CreateUpdateDownloader()
        $Downloader.Updates = $SingleColl
        try {
            $DlResult = $Downloader.Download()
        } catch {
            Write-Output "FAIL: [LETÖLTÉS HIBA] $title"
            $failCount++
            continue
        }
        
        if ($DlResult.ResultCode -ne 2 -and $DlResult.ResultCode -ne 3) {
            Write-Output "FAIL: [LETÖLTÉS HIBA kód=$($DlResult.ResultCode)] $title"
            $failCount++
            continue
        }
        
        # Egyedi telepítés
        Write-Output "INSTONE: $idx/$total $title"
        $Installer = $Session.CreateUpdateInstaller()
        $Installer.Updates = $SingleColl
        try {
            $InstResult = $Installer.Install()
        } catch {
            Write-Output "FAIL: [TELEPÍTÉS HIBA] $title"
            $failCount++
            continue
        }
        
        $rc = $InstResult.GetUpdateResult(0).ResultCode
        switch ($rc) {
            2 { Write-Output "OK: [SIKER] $title"; $successCount++ }
            3 { Write-Output "OK: [SIKER/FIGYELEM] $title"; $successCount++ }
            4 { Write-Output "FAIL: [HIBA] $title"; $failCount++ }
            5 { Write-Output "FAIL: [MEGSZAKÍTVA] $title"; $failCount++ }
            default { Write-Output "FAIL: [ISMERETLEN=$rc] $title"; $failCount++ }
        }
    }
    
    Write-Output "DONE: Sikeres=$successCount, Sikertelen=$failCount"
    
} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
}
"""
            self.after(0, lambda: append_log("Windows Update COM API telepítés indítása..."))

            process = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
            )

            success_count = 0
            fail_count = 0
            found_count = 0
            install_total = 0

            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue

                if line.startswith("INIT:") or line.startswith("SEARCH:"):
                    self.after(0, lambda m=line.split(":", 1)[1].strip(): status_lbl.config(text=m))
                    self.after(0, lambda m=line: append_log(m))
                elif line.startswith("FOUND:"):
                    found_count += 1
                    self.after(0, lambda m=f"  📦 {line[6:].strip()}": append_log(m))
                    self.after(0, lambda c=found_count: counter_lbl.config(text=f"Talált driverek: {c}"))
                elif line.startswith("SKIP:"):
                    self.after(0, lambda m=f"  ⏭ {line[5:].strip()}": append_log(m))
                elif line.startswith("TOTAL:"):
                    _m_total = re.search(r'(\d+)', line)
                    if _m_total:
                        install_total = int(_m_total.group(1))
                    def _switch_determinate(t=install_total):
                        try:
                            progress.stop()
                        except Exception:
                            pass
                        progress.config(mode='determinate', maximum=max(t, 1), value=0)
                        counter_lbl.config(text=f"0 / {t}")
                    self.after(0, _switch_determinate)
                    self.after(0, lambda t=install_total: append_log(f"Összesen {t} driver letöltése és telepítése egyenként..."))
                elif line.startswith("DLONE:"):
                    msg = line[6:].strip()
                    self.after(0, lambda m=msg: status_lbl.config(text=f"⬇ Letöltés: {m}"))
                    self.after(0, lambda m=f"  ⬇ Letöltés: {msg}": append_log(m))
                elif line.startswith("INSTONE:"):
                    msg = line[8:].strip()
                    self.after(0, lambda m=msg: status_lbl.config(text=f"⚙ Telepítés: {m}"))
                    self.after(0, lambda m=f"  ⚙ Telepítés: {msg}": append_log(m))
                elif line.startswith("OK:"):
                    success_count += 1
                    done = success_count + fail_count
                    self.after(0, lambda m=f"  ✅ {line[3:].strip()}": append_log(m))
                    self.after(0, lambda d=done, t=install_total, s=success_count, f=fail_count: (
                        progress.config(value=d),
                        counter_lbl.config(text=f"Telepítés: {d} / {t}  (✅ {s}  ❌ {f})")
                    ))
                elif line.startswith("FAIL:"):
                    fail_count += 1
                    done = success_count + fail_count
                    self.after(0, lambda m=f"  ❌ {line[5:].strip()}": append_log(m))
                    self.after(0, lambda d=done, t=install_total, s=success_count, f=fail_count: (
                        progress.config(value=d),
                        counter_lbl.config(text=f"Telepítés: {d} / {t}  (✅ {s}  ❌ {f})")
                    ))
                elif line.startswith("DONE:"):
                    self.after(0, lambda m=f"\n--- {line[5:].strip()} ---": append_log(m))
                elif line.startswith("EMPTY:"):
                    self.after(0, lambda m=line[6:].strip(): append_log(m))
                elif line.startswith("ERROR:"):
                    self.after(0, lambda m=f"❌ HIBA: {line[6:].strip()}": append_log(m))
                else:
                    self.after(0, lambda m=line: append_log(m))

            process.wait()

            # Eszközök újraszkennelése a telepítés után
            if success_count > 0:
                self.after(0, lambda: append_log("Eszközök újraszkennelése..."))
                self.after(0, lambda: status_lbl.config(text="Telepített driverek aktiválása..."))
                subprocess.run(['pnputil', '/scan-devices'], startupinfo=startupinfo,
                              capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                self.after(0, lambda: append_log("✅ Eszközök frissítve!"))

            def finish():
                try:
                    progress.stop()
                except Exception:
                    pass
                if prog_win.winfo_exists():
                    prog_win.destroy()
                total = success_count + fail_count
                if success_count > 0:
                    messagebox.showinfo("Befejezve",
                        f"Driver frissítések telepítve!\n\n"
                        f"✅ Sikeres: {success_count}\n"
                        f"❌ Sikertelen: {fail_count}\n\n"
                        f"Ajánlott a gép újraindítása a változások érvényesítéséhez.")
                else:
                    if fail_count > 0:
                        messagebox.showwarning("Telepítés sikertelen",
                            f"Egy driver sem települt sikeresen.\nSikertelen: {fail_count}\n\n"
                            f"Próbáld újraindítani a gépet és futtasd újra!")
                    else:
                        messagebox.showinfo("Nincs frissítés", "Nem található telepíthető driver frissítés.")

            self.after(0, finish)

        def safe_worker():
            try:
                worker()
            except Exception as e:
                logging.error(f"WU API install worker hiba: {e}")
                def on_error(err=e):
                    try: progress.stop()
                    except Exception: pass
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba", f"Váratlan hiba a WU telepítés közben:\n{str(err)}")
                self.after(0, on_error)

        threading.Thread(target=safe_worker, daemon=True).start()

    def _install_via_catalog(self):
        """MS Update Catalog-ból letöltött CAB fájlok telepítése pnputil-lal (fallback mód)."""
        pool_count = len(self._install_pool)
        prog_win, progress, status_lbl, counter_lbl, log_text, append_log = self._create_progress_window(
            "WU Driver Tömeges Telepítése (Katalógus)",
            f"{pool_count} db Windows Update driver letöltése és telepítése...",
            width=650, height=400, mode='determinate', maximum=pool_count
        )

        def worker():
            import os, urllib.request, ssl, shutil
            import subprocess
            ssl_ctx = ssl.create_default_context()
            
            temp_dir = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'driver_tool_wu')
            os.makedirs(temp_dir, exist_ok=True)
            
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            success_count = 0
            skipped_count = 0
            pool_snapshot = list(self._install_pool)
            
            for i, drv in enumerate(pool_snapshot):
                name = drv['name']
                url = drv.get('url', '')
                hwid = drv['hwid']
                
                if not url:
                    skipped_count += 1
                    self.after(0, lambda m=f"   [KIHAGYÁS] {name} - nincs letöltési link": append_log(m))
                    continue
                
                cab_path = os.path.join(temp_dir, f"drv_{i}.cab")
                ext_path = os.path.join(temp_dir, f"drv_ext_{i}")
                
                self.after(0, lambda val=i, idx=i+1, total=len(pool_snapshot), nm=name: (
                    progress.configure(value=val),
                    status_lbl.config(text=f"Letöltés: {nm}..."),
                    counter_lbl.config(text=f"{idx} / {total}")
                ))
                self.after(0, lambda m=f"-> {name} letöltése a Microsoft szerveréről...": append_log(m))
                
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    with urllib.request.urlopen(req, context=ssl_ctx) as response, open(cab_path, 'wb') as out_file:
                        shutil.copyfileobj(response, out_file)
                except Exception as e:
                    self.after(0, lambda m=f"   [HIBA] Letöltés megszakadt: {e}": append_log(m))
                    continue
                
                os.makedirs(ext_path, exist_ok=True)
                self.after(0, lambda m=f"   Kicsomagolás (expand.exe)...": append_log(m))
                expand_res = subprocess.run(['expand', cab_path, '-F:*', ext_path], capture_output=True, text=True, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
                if expand_res.returncode != 0:
                    self.after(0, lambda m=f"   [ÉRTESÍTÉS] expand.exe figyelmeztetéssel tért vissza: kód={expand_res.returncode}. Log: {expand_res.stdout[:100]}": append_log(m))

                # Nested CAB-ok kicsomagolása (CAB-in-CAB struktúra kezelése)
                import glob
                for inner_cab in glob.glob(os.path.join(ext_path, '*.cab')):
                    inner_ext = inner_cab + '_ext'
                    os.makedirs(inner_ext, exist_ok=True)
                    subprocess.run(['expand', inner_cab, '-F:*', inner_ext], capture_output=True, text=True, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.after(0, lambda m=f"   Belső CAB kicsomagolva: {os.path.basename(inner_cab)}": append_log(m))

                self.after(0, lambda idx=i+1, total=len(pool_snapshot), nm=name: (
                    status_lbl.config(text=f"Telepítés: {nm}..."),
                    counter_lbl.config(text=f"{idx} / {total}")
                ))
                self.after(0, lambda m=f"   Telepítés pnp/dism futtatása...": append_log(m))
                
                is_offline = hasattr(self, 'target_os_path') and self.target_os_path
                is_pe = os.environ.get('SystemDrive', 'C:') == 'X:' or getattr(self, 'sys_drive', '').upper() == 'X:\\'
                
                if is_offline and not is_pe:
                    cmd = ['dism', f'/Image:{self.target_os_path}', '/Add-Driver', f'/Driver:{ext_path}', '/Recurse', '/ForceUnsigned']
                else:
                    cmd = ['pnputil', '/add-driver', f"{ext_path}\\*.inf", '/subdirs', '/install']
                    
                res = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                self.after(0, lambda m=f"   Kimenet: {res.stdout.strip()}": append_log(m))
                
                if res.returncode == 0 or "Added" in res.stdout or "sikeres" in res.stdout.lower() or "successfully" in res.stdout.lower():
                    success_count += 1
                    self.after(0, lambda m=f"   [SIKER] {name} sikeresen feltelepítve!": append_log(m))
                else:
                    self.after(0, lambda m=f"   [HIBA] PnP telepítési hiba. Kód: {res.returncode}. LOG:\n{res.stdout.strip()[:150]}": append_log(m))

            self.after(0, lambda: progress.configure(value=len(pool_snapshot)))
            attempted = len(pool_snapshot) - skipped_count
            self.after(0, lambda: append_log(f"--- FOLYAMAT VÉGE. SIKERES: {success_count}/{attempted} (kihagyva: {skipped_count}) ---"))
            
            is_offline = hasattr(self, 'target_os_path') and self.target_os_path
            is_pe = os.environ.get('SystemDrive', 'C:') == 'X:' or getattr(self, 'sys_drive', '').upper() == 'X:\\'
            
            if success_count > 0 and (not is_offline or is_pe):
                scan_win_ready = threading.Event()

                def show_scan_win():
                    if not prog_win.winfo_exists():
                        scan_win_ready.set()
                        return
                    w = tk.Toplevel(prog_win)
                    w.title("Aktiválás folyamatban")
                    w.geometry("450x170")
                    w.transient(prog_win)
                    w.grab_set()
                    w.update_idletasks()
                    x = prog_win.winfo_x() + (prog_win.winfo_width() // 2) - 225
                    y = prog_win.winfo_y() + (prog_win.winfo_height() // 2) - 85
                    w.geometry(f"+{max(0,x)}+{max(0,y)}")
                    msg = "Eszközök újraszkennelése és frissítése a háttérben...\n\nOlykor a képernyő egy pillanatra villanhat!\nKérlek, várj türelemmel amíg befejezzük."
                    lbl = ttk.Label(w, text=msg, justify=tk.CENTER, font=("Segoe UI", 10, "bold"))
                    lbl.pack(padx=10, pady=(15, 5))
                    _act_pb = ttk.Progressbar(w, orient=tk.HORIZONTAL, length=370, mode='indeterminate', style="Green.Horizontal.TProgressbar")
                    _act_pb.pack(pady=(5, 15))
                    _act_pb.start(15)
                    self.__scan_win = w
                    w.update()
                    scan_win_ready.set()
                
                self.after(0, show_scan_win)
                scan_win_ready.wait(timeout=5.0)
                
                self.after(0, lambda m=f"-> Telepített eszközök újraindítása (Azonnali érvényesítés)...": append_log(m))
                for drv in pool_snapshot:
                    pnp_id = drv.get('pnp_id')
                    if pnp_id:
                        subprocess.run(['pnputil', '/restart-device', pnp_id], startupinfo=startupinfo, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                self.after(0, lambda m=f"-> Hardverváltozások (eszközkezelő) újraszkennelése (pnputil /scan-devices)...": append_log(m))
                self.after(0, lambda txt=f"Sikeres telepítések aktiválása...": status_lbl.config(text=txt))
                subprocess.run(['pnputil', '/scan-devices'], startupinfo=startupinfo, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                self.after(0, lambda m=f"   [KÉSZ] Hardverek frissítése megtörtént a Windowsban!": append_log(m))
                
                def close_scan_win():
                    if hasattr(self, '_DriverCleanerApp__scan_win') and self.__scan_win and self.__scan_win.winfo_exists():
                        self.__scan_win.destroy()
                self.after(0, close_scan_win)

            def finish():
                if prog_win.winfo_exists():
                    prog_win.destroy()
                attempted = len(pool_snapshot) - skipped_count
                if attempted <= 0:
                    messagebox.showinfo("Nincs telepíthető", "Egyetlen driverhez sem volt letöltési link.")
                elif success_count == attempted:
                    messagebox.showinfo("Befejezve", f"Minden letöltött driver ({success_count} db) sikeresen feltelepítve a rendszerre.")
                elif success_count > 0:
                    messagebox.showwarning("Részben sikeres", f"Telepítve: {success_count} / {attempted}\nSikertelen: {attempted - success_count}")
                else:
                    messagebox.showerror("Sikertelen", f"Egy driver sem települt sikeresen ({attempted} db kísérletből).")
                
            self.after(0, finish)

        def safe_worker():
            try:
                worker()
            except Exception as e:
                logging.error(f"Katalógus install worker hiba: {e}")
                def on_error(err=e):
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba", f"Váratlan hiba a telepítés közben:\n{str(err)}")
                self.after(0, on_error)
            finally:
                temp_dir = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'driver_tool_wu')
                try:
                    import shutil as _shutil
                    _shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

        threading.Thread(target=safe_worker, daemon=True).start()

    def refresh_drivers(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        is_all = hasattr(self, 'list_all_var') and self.list_all_var.get()

        # Progress megjelenítése
        mode_text = "MINDEN driver" if is_all else "third-party driverek"
        self.drv_status_lbl.config(text=f"⏳ {mode_text} betöltése... (ez eltarthat {"30-60 mp" if is_all else "pár mp"})")
        self.drv_progress.pack(side=tk.RIGHT, padx=5)
        self.drv_progress.start(15)

        import time as _time
        load_start = _time.time()

        def _refresh_worker():
            if hasattr(self, 'target_os_path') and self.target_os_path:
                drivers = self.get_offline_drivers(all_drivers=is_all)
            else:
                if is_all:
                    drivers = self.get_all_drivers()
                else:
                    drivers = self.get_third_party_drivers()

            elapsed = _time.time() - load_start

            def populate(d_list=drivers, secs=elapsed):
                for d in d_list:
                    if "published" in d:
                        self.tree.insert("", tk.END, values=(
                            d.get("published", ""),
                            d.get("original", ""),
                            d.get("provider", ""),
                            d.get("class", ""),
                            d.get("version", "")
                        ))
                # Progress elrejtése, összesítés kiírása
                self.drv_progress.stop()
                self.drv_progress.pack_forget()
                self.drv_status_lbl.config(text=f"✅ {len(d_list)} driver betöltve ({secs:.1f} mp)")
            self.after(0, populate)

        threading.Thread(target=_refresh_worker, daemon=True).start()

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
            
        del_count = len(selected)
        prog_win, progress, status_lbl, counter_lbl, log_text, append_log = self._create_progress_window(
            "Törlés folyamatban...",
            f"{del_count} driver végleges eltávolítása folyamatban...\nKérlek várj!",
            width=650, height=400, mode='determinate', maximum=del_count
        )

        items_to_delete = [self.tree.item(item, "values")[0] for item in selected]

        def worker():
            success_count = 0
            fail_count = 0
            
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            self.after(0, lambda: append_log(f"Kijelolt driverek torlese indult ({len(items_to_delete)} db)"))
            for i, published_name in enumerate(items_to_delete):
                def update_status(txt=f"{published_name} törlése...", val=i, idx=i+1, total=len(items_to_delete)):
                    status_lbl.config(text=txt)
                    progress['value'] = val
                    counter_lbl.config(text=f"{idx} / {total}")
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

                    if res.returncode == 0 or "Deleted" in res.stdout or "törölve" in res.stdout or "successfully" in res.stdout.lower():
                        success_count += 1
                        self.after(0, lambda m=f"   [SIKER] {published_name} letorolve.": append_log(m))
                    else:
                        if hasattr(self, 'list_all_var') and self.list_all_var.get() and not is_oem:
                            self.after(0, lambda m=f"   [KISERLET] Inbox {published_name} eroszakos torlese FileRepository-bol...": append_log(m))
                            import glob
                            if is_offline:
                                rep_path = os.path.join(self.target_os_path, "Windows", "System32", "DriverStore", "FileRepository")
                            else:
                                rep_path = os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), "System32", "DriverStore", "FileRepository")
                            
                            dirs = glob.glob(os.path.join(rep_path, f"{published_name}_*"))
                            
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
                is_offline = hasattr(self, 'target_os_path') and self.target_os_path
                is_pe = os.environ.get('SystemDrive', 'C:') == 'X:' or getattr(self, 'sys_drive', '').upper() == 'X:\\'
                
                if is_offline or is_pe:
                    messagebox.showinfo("Eredmeny", f"Sikeresen torolve: {success_count}\nNem sikerult: {fail_count}")
                    self.refresh_drivers()
                else:
                    messagebox.showinfo("Eredmeny", f"Sikeresen torolve: {success_count}\nNem sikerult: {fail_count}\n\nMost a program ujraellenorzi a hardvereket.")
                    self._run_hardware_scan_window()

            self.after(0, finish_delete)

        def safe_worker():
            try:
                worker()
            except Exception as e:
                logging.error(f"Driver törlés worker hiba: {e}")
                def on_error(err=e):
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba", f"Váratlan hiba a törlés közben:\n{str(err)}")
                self.after(0, on_error)

        threading.Thread(target=safe_worker, daemon=True).start()

    def _run_hardware_scan_window(self):
        scan_win = tk.Toplevel(self)
        scan_win.title("Hardverek ellenőrzése...")
        scan_win.geometry("500x160")
        scan_win.transient(self)
        scan_win.grab_set()

        lbl = ttk.Label(scan_win, text="Hiányzó Windows alapértelmezett driverek scannelése...\nEzután mennie kell a Touchpadnek alap driverekkel is!", justify=tk.CENTER, font=("Segoe UI", 10))
        lbl.pack(pady=(10, 5))

        progress = ttk.Progressbar(scan_win, orient=tk.HORIZONTAL, length=420, mode='indeterminate', style="Green.Horizontal.TProgressbar")
        progress.pack(pady=5)
        progress.start(15)

        status_lbl = ttk.Label(scan_win, text="Kérlek várj...", font=("Segoe UI", 9))
        status_lbl.pack(pady=5)

        def scan_worker():
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                time.sleep(1) # Pici pihenő
                subprocess.run(['pnputil', '/scan-devices'], startupinfo=startupinfo, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                time.sleep(3) # Várjunk, amíg a Windows a háttérben telepíti az eszközöket
            except Exception as ex:
                logging.error(f"Hiba a PnP hardver scan során: {ex}")

            def finish_scan():
                if scan_win.winfo_exists():
                    scan_win.destroy()
                messagebox.showinfo("Kész", "Az alapértelmezett Windows illesztők (pl. Generic Touchpad) beállítása befejeződött!\nMost már működnie kell az eszközöknek.")
                self.refresh_drivers()

            self.after(0, finish_scan)

        threading.Thread(target=scan_worker, daemon=True).start()

    # =====================================================================
    # 1 KATTINTÁSOS AUTOMATIKUS DRIVER FIX
    # =====================================================================
    def one_click_driver_fix(self):
        """Teljes automatikus driver újratelepítés: törlés → scan → WU install → reboot."""
        confirm = messagebox.askyesno(
            "⚡ 1 Kattintásos Driver Fix",
            "Ez a művelet:\n\n"
            "1. LETILTJA a WU automatikus driver keresést\n"
            "2. TÖRLI az összes third-party drivert\n"
            "3. Újraszkennel minden hardvert\n"
            "4. Windows Update-ről TELEPÍTI az összes elérhető drivert\n"
            "5. Automatikusan ÚJRAINDÍTJA a gépet\n\n"
            "⚠️ A folyamat közben NE használd a gépet!\n\n"
            "Biztosan elindítod?",
            icon='warning'
        )
        if not confirm:
            return

        self.autofix_btn.config(state=tk.DISABLED, text="⏳ Folyamatban...")

        prog_win = tk.Toplevel(self)
        prog_win.title("⚡ 1 Kattintásos Driver Fix — Folyamatban")
        prog_win.geometry("700x500")
        prog_win.transient(self)
        prog_win.grab_set()
        prog_win.protocol("WM_DELETE_WINDOW", lambda: None)

        header_lbl = ttk.Label(prog_win, text="⚡ Automatikus Driver Újratelepítés", font=("Segoe UI", 12, "bold"))
        header_lbl.pack(pady=(10, 2))

        phase_lbl = ttk.Label(prog_win, text="Inicializálás...", font=("Segoe UI", 10, "bold"), foreground="#0066CC")
        phase_lbl.pack(pady=(2, 5))

        counter_lbl = ttk.Label(prog_win, text="", font=("Segoe UI", 10, "bold"))
        counter_lbl.pack(pady=(0, 2))

        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=620, mode='determinate',
                                   style="Green.Horizontal.TProgressbar", maximum=100)
        progress.pack(pady=5)

        status_lbl = ttk.Label(prog_win, text="Előkészítés...", font=("Segoe UI", 9))
        status_lbl.pack(pady=(2, 5))

        time_lbl = ttk.Label(prog_win, text="", font=("Segoe UI", 9), foreground="#666666")
        time_lbl.pack(pady=(0, 5))

        text_frame = tk.Frame(prog_win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        log_text = tk.Text(text_frame, height=14, state=tk.DISABLED, bg="#1E1E1E", fg="#00FF00",
                           font=("Consolas", 9))
        log_scroll = ttk.Scrollbar(text_frame, command=log_text.yview)
        log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def append_log(msg):
            logging.info(f"[AUTOFIX] {msg}")
            log_text.config(state=tk.NORMAL)
            log_text.insert(tk.END, msg + "\n")
            log_text.see(tk.END)
            log_text.config(state=tk.DISABLED)

        def set_phase(text):
            phase_lbl.config(text=text)

        def set_status(text):
            status_lbl.config(text=text)

        def set_counter(text):
            counter_lbl.config(text=text)

        def set_time(text):
            time_lbl.config(text=text)

        def set_progress(value, maximum=None):
            if maximum is not None:
                progress.config(maximum=maximum)
            progress.config(value=value)

        def worker():
            import time as _time
            overall_start = _time.time()
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            def elapsed():
                secs = int(_time.time() - overall_start)
                m, s = divmod(secs, 60)
                return f"Eltelt idő: {m:02d}:{s:02d}"

            # ========================================
            # PHASE 1: WU driver keresés letiltása
            # ========================================
            self.after(0, lambda: set_phase("⛔ 1. FÁZIS: WU driver keresés letiltása"))
            self.after(0, lambda: append_log("=" * 50))
            self.after(0, lambda: append_log("FÁZIS 1: Windows Update driver keresés letiltása..."))
            self.after(0, lambda: set_status("Registry és Group Policy beállítása..."))
            self.after(0, lambda: set_counter(""))
            self.after(0, lambda: set_progress(0, 4))

            import winreg
            wu_disable_ok = True

            # 1/4: ExcludeWUDriversInQualityUpdate = 1
            self.after(0, lambda: append_log("  1. ExcludeWUDriversInQualityUpdate = 1"))
            try:
                key_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 1)
                self.after(0, lambda: append_log("    ✅ Registry beállítva"))
            except Exception as e:
                self.after(0, lambda err=e: append_log(f"    ⚠ winreg hiba: {err}"))
            # Fallback reg.exe-vel is
            subprocess.run(['reg', 'add', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate',
                           '/v', 'ExcludeWUDriversInQualityUpdate', '/t', 'REG_DWORD', '/d', '1', '/f'],
                          startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW,
                          capture_output=True, text=True, errors='replace')
            self.after(0, lambda: set_progress(1, 4))

            # 2/4: SearchOrderConfig = 0
            self.after(0, lambda: append_log("  2. SearchOrderConfig = 0"))
            try:
                key_path2 = r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching"
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path2, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 0)
                self.after(0, lambda: append_log("    ✅ Registry beállítva"))
            except Exception as e:
                self.after(0, lambda err=e: append_log(f"    ⚠ winreg hiba: {err}"))
            subprocess.run(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching',
                           '/v', 'SearchOrderConfig', '/t', 'REG_DWORD', '/d', '0', '/f'],
                          startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW,
                          capture_output=True, text=True, errors='replace')
            self.after(0, lambda: set_progress(2, 4))

            # 3/4: WU szolgáltatás újraindítása
            self.after(0, lambda: append_log("  3. Windows Update szolgáltatás újraindítása..."))
            self.after(0, lambda: set_status("WU szolgáltatás újraindítása..."))
            subprocess.run('net stop wuauserv & net start wuauserv', shell=True,
                          startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW,
                          capture_output=True, text=True, errors='replace')
            self.after(0, lambda: append_log("    ✅ WU szolgáltatás újraindítva"))
            self.after(0, lambda: set_progress(3, 4))

            # 4/4: Ellenőrzés
            self.after(0, lambda: append_log("  4. Beállítások ellenőrzése..."))
            try:
                res_chk = subprocess.run(['reg', 'query', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate',
                                         '/v', 'ExcludeWUDriversInQualityUpdate'],
                                        startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW,
                                        capture_output=True, text=True, errors='replace')
                if '0x1' in res_chk.stdout:
                    self.after(0, lambda: append_log("    ✅ ExcludeWUDriversInQualityUpdate = 1 (OK)"))
                else:
                    self.after(0, lambda: append_log("    ⚠ ExcludeWUDriversInQualityUpdate — nem ellenőrizhető"))
            except Exception:
                pass
            try:
                res_chk2 = subprocess.run(['reg', 'query', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching',
                                          '/v', 'SearchOrderConfig'],
                                         startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW,
                                         capture_output=True, text=True, errors='replace')
                if '0x0' in res_chk2.stdout:
                    self.after(0, lambda: append_log("    ✅ SearchOrderConfig = 0 (OK)"))
                else:
                    self.after(0, lambda: append_log("    ⚠ SearchOrderConfig — nem ellenőrizhető"))
            except Exception:
                pass
            self.after(0, lambda: set_progress(4, 4))
            self.after(0, lambda: append_log("\n✅ WU driver keresés sikeresen letiltva!\n"))
            self.after(0, lambda: set_time(elapsed()))

            # ========================================
            # PHASE 2: Third-party driverek törlése
            # ========================================
            self.after(0, lambda: set_phase("🔴 2. FÁZIS: Third-party driverek törlése"))
            self.after(0, lambda: append_log("=" * 50))
            self.after(0, lambda: append_log("FÁZIS 2: Third-party driverek listázása..."))

            drivers = self.get_third_party_drivers()
            if not drivers:
                self.after(0, lambda: append_log("Nincs third-party driver a gépen."))
                self.after(0, lambda: set_counter("0 driver"))
            else:
                del_total = len(drivers)
                self.after(0, lambda t=del_total: append_log(f"Talált third-party driverek: {t} db"))
                self.after(0, lambda t=del_total: set_counter(f"0 / {t} driver törölve"))
                self.after(0, lambda t=del_total: set_progress(0, t))

                del_success = 0
                del_fail = 0
                for i, drv in enumerate(drivers):
                    pub = drv.get("published", "ismeretlen")
                    prov = drv.get("provider", "")
                    cls = drv.get("class", "")
                    self.after(0, lambda p=pub, pr=prov, c=cls: set_status(f"Törlés: {p} ({pr} — {c})"))
                    self.after(0, lambda p=pub, pr=prov: append_log(f"  🗑 Törlés: {p} [{pr}]"))

                    try:
                        res = subprocess.run(
                            ['pnputil', '/delete-driver', pub, '/uninstall', '/force'],
                            capture_output=True, text=True, startupinfo=startupinfo,
                            errors='replace', creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        if res.returncode == 0 or "Deleted" in res.stdout or "törölve" in res.stdout or "successfully" in res.stdout.lower():
                            del_success += 1
                            self.after(0, lambda p=pub: append_log(f"    ✅ {p} törölve"))
                        else:
                            del_fail += 1
                            self.after(0, lambda p=pub: append_log(f"    ❌ {p} — sikertelen"))
                    except Exception as e:
                        del_fail += 1
                        self.after(0, lambda p=pub, err=e: append_log(f"    ❌ {p} — hiba: {err}"))

                    done = i + 1
                    self.after(0, lambda d=done, t=del_total, s=del_success, f=del_fail:
                        (set_progress(d, t),
                         set_counter(f"{d} / {t} driver (✅ {s}  ❌ {f})"),
                         set_time(elapsed())))

                self.after(0, lambda s=del_success, f=del_fail:
                    append_log(f"\n--- Törlés kész. Sikeres: {s}, Sikertelen: {f} ---\n"))

            # ========================================
            # PHASE 3: Hardver újraszkennelés
            # ========================================
            self.after(0, lambda: set_phase("🟡 3. FÁZIS: Hardver újraszkennelés"))
            self.after(0, lambda: set_status("Windows alapértelmezett driverek visszaállítása..."))
            self.after(0, lambda: set_counter(""))
            self.after(0, lambda: set_progress(0, 100))
            self.after(0, lambda: append_log("=" * 50))
            self.after(0, lambda: append_log("FÁZIS 3: pnputil /scan-devices futtatása..."))

            try:
                subprocess.run(['pnputil', '/scan-devices'], startupinfo=startupinfo,
                              capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=120)
                _time.sleep(5)  # Várakozás, hogy a Windows befejezze az eszközök újra-inicializálását
                self.after(0, lambda: append_log("✅ Hardver újraszkennelés kész!"))
            except subprocess.TimeoutExpired:
                self.after(0, lambda: append_log("⚠ Scan timeout (120s) — folytatás..."))
            except Exception as e:
                self.after(0, lambda err=e: append_log(f"⚠ Scan hiba: {err} — folytatás..."))

            self.after(0, lambda: set_progress(100, 100))
            self.after(0, lambda: set_time(elapsed()))

            # ========================================
            # PHASE 4: WU COM API keresés
            # ========================================
            self.after(0, lambda: set_phase("🟠 4. FÁZIS: Windows Update driver keresés"))
            self.after(0, lambda: set_status("WU COM API-n keresztüli keresés... (ez eltarthat 1-3 percig)"))
            self.after(0, lambda: set_counter("Keresés folyamatban..."))
            self.after(0, lambda: set_progress(0, 100))
            self.after(0, lambda: append_log("=" * 50))
            self.after(0, lambda: append_log("FÁZIS 4: Windows Update COM API driver keresés..."))

            wu_results = self._search_wu_api()

            if wu_results is None:
                self.after(0, lambda: append_log("❌ WU API keresés hiba! Nem sikerült lekérdezni."))
                self.after(0, lambda: set_status("WU API hiba — telepítés kihagyva"))
                wu_results = []
            elif len(wu_results) == 0:
                self.after(0, lambda: append_log("ℹ Nem talált elérhető driver frissítést a Windows Update."))
                self.after(0, lambda: set_status("Nincs elérhető driver frissítés"))
            else:
                self.after(0, lambda c=len(wu_results): append_log(f"✅ Talált {c} db elérhető driver frissítést!"))
                for drv in wu_results:
                    title = drv.get('Title', 'ismeretlen')
                    self.after(0, lambda t=title: append_log(f"  📦 {t}"))

            self.after(0, lambda: set_progress(100, 100))
            self.after(0, lambda: set_time(elapsed()))

            # ========================================
            # PHASE 4: WU COM API telepítés
            # ========================================
            if wu_results:
                wu_count = len(wu_results)
                self.after(0, lambda c=wu_count: set_phase(f"🟢 5. FÁZIS: {c} driver letöltése és telepítése"))
                self.after(0, lambda: set_status("Windows Update COM API telepítés indítása..."))
                self.after(0, lambda c=wu_count: set_counter(f"0 / {c}"))
                self.after(0, lambda c=wu_count: set_progress(0, c))
                self.after(0, lambda: append_log("=" * 50))
                self.after(0, lambda c=wu_count: append_log(f"FÁZIS 5: {c} driver letöltése és telepítése WU API-n keresztül...\n"))

                # WU COM API: összes driver telepítése egyszerre (egy PS processz)
                ps_script = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    $Session = New-Object -ComObject Microsoft.Update.Session
    $Searcher = $Session.CreateUpdateSearcher()
    try {
        $SM = New-Object -ComObject Microsoft.Update.ServiceManager
        $SM.AddService2("7971f918-a847-4430-9279-4a52d1efe18d", 7, "") | Out-Null
    } catch {}
    $Searcher.ServerSelection = 3
    $Searcher.ServiceID = "7971f918-a847-4430-9279-4a52d1efe18d"
    
    Write-Output "SEARCH: Driver frissítések keresése..."
    $Result = $Searcher.Search("IsInstalled=0 and Type='Driver'")
    
    if ($Result.Updates.Count -eq 0) {
        Write-Output "EMPTY: Nincs elérhető driver frissítés."
        return
    }
    
    $ToInstall = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($U in $Result.Updates) {
        if (-not $U.EulaAccepted) { $U.AcceptEula() }
        $ToInstall.Add($U) | Out-Null
    }
    
    $total = $ToInstall.Count
    Write-Output "TOTAL: $total"
    
    $successCount = 0
    $failCount = 0
    
    for ($i = 0; $i -lt $total; $i++) {
        $U = $ToInstall.Item($i)
        $title = $U.Title
        $idx = $i + 1
        
        Write-Output "DLONE: $idx/$total $title"
        $SingleColl = New-Object -ComObject Microsoft.Update.UpdateColl
        $SingleColl.Add($U) | Out-Null
        
        $Downloader = $Session.CreateUpdateDownloader()
        $Downloader.Updates = $SingleColl
        try {
            $DlResult = $Downloader.Download()
        } catch {
            Write-Output "FAIL: [LETÖLTÉS HIBA] $title"
            $failCount++
            continue
        }
        
        if ($DlResult.ResultCode -ne 2 -and $DlResult.ResultCode -ne 3) {
            Write-Output "FAIL: [LETÖLTÉS HIBA kód=$($DlResult.ResultCode)] $title"
            $failCount++
            continue
        }
        
        Write-Output "INSTONE: $idx/$total $title"
        $Installer = $Session.CreateUpdateInstaller()
        $Installer.Updates = $SingleColl
        try {
            $InstResult = $Installer.Install()
        } catch {
            Write-Output "FAIL: [TELEPÍTÉS HIBA] $title"
            $failCount++
            continue
        }
        
        $rc = $InstResult.GetUpdateResult(0).ResultCode
        switch ($rc) {
            2 { Write-Output "OK: [SIKER] $title"; $successCount++ }
            3 { Write-Output "OK: [SIKER/FIGYELEM] $title"; $successCount++ }
            4 { Write-Output "FAIL: [HIBA] $title"; $failCount++ }
            5 { Write-Output "FAIL: [MEGSZAKÍTVA] $title"; $failCount++ }
            default { Write-Output "FAIL: [ISMERETLEN=$rc] $title"; $failCount++ }
        }
    }
    
    Write-Output "DONE: Sikeres=$successCount, Sikertelen=$failCount"
    
} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
}
"""
                install_success = 0
                install_fail = 0
                install_total = 0

                process = subprocess.Popen(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                    startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
                )

                for line in process.stdout:
                    line = line.strip()
                    if not line:
                        continue

                    if line.startswith("SEARCH:"):
                        self.after(0, lambda m=line.split(":", 1)[1].strip(): set_status(m))
                        self.after(0, lambda m=line: append_log(m))
                    elif line.startswith("TOTAL:"):
                        _m = re.search(r'(\d+)', line)
                        if _m:
                            install_total = int(_m.group(1))
                        self.after(0, lambda t=install_total: set_progress(0, max(t, 1)))
                        self.after(0, lambda t=install_total: set_counter(f"0 / {t}"))
                        self.after(0, lambda t=install_total: append_log(f"Összesen {t} driver telepítése..."))
                    elif line.startswith("DLONE:"):
                        msg = line[6:].strip()
                        self.after(0, lambda m=msg: set_status(f"⬇ Letöltés: {m}"))
                        self.after(0, lambda m=msg: append_log(f"  ⬇ Letöltés: {m}"))
                    elif line.startswith("INSTONE:"):
                        msg = line[8:].strip()
                        self.after(0, lambda m=msg: set_status(f"⚙ Telepítés: {m}"))
                        self.after(0, lambda m=msg: append_log(f"  ⚙ Telepítés: {m}"))
                    elif line.startswith("OK:"):
                        install_success += 1
                        done = install_success + install_fail
                        self.after(0, lambda m=line[3:].strip(): append_log(f"  ✅ {m}"))
                        self.after(0, lambda d=done, t=install_total, s=install_success, f=install_fail:
                            (set_progress(d, max(t, 1)),
                             set_counter(f"{d} / {t}  (✅ {s}  ❌ {f})")))
                    elif line.startswith("FAIL:"):
                        install_fail += 1
                        done = install_success + install_fail
                        self.after(0, lambda m=line[5:].strip(): append_log(f"  ❌ {m}"))
                        self.after(0, lambda d=done, t=install_total, s=install_success, f=install_fail:
                            (set_progress(d, max(t, 1)),
                             set_counter(f"{d} / {t}  (✅ {s}  ❌ {f})")))
                    elif line.startswith("DONE:"):
                        self.after(0, lambda m=line[5:].strip(): append_log(f"\n--- {m} ---"))
                    elif line.startswith("EMPTY:"):
                        self.after(0, lambda m=line[6:].strip(): append_log(m))
                    elif line.startswith("ERROR:"):
                        self.after(0, lambda m=line[6:].strip(): append_log(f"❌ HIBA: {m}"))
                    else:
                        self.after(0, lambda m=line: append_log(m))

                    self.after(0, lambda: set_time(elapsed()))

                process.wait()

                # Post-install scan
                if install_success > 0:
                    self.after(0, lambda: append_log("\nEszközök újraszkennelése a telepítés után..."))
                    self.after(0, lambda: set_status("Telepített driverek aktiválása..."))
                    subprocess.run(['pnputil', '/scan-devices'], startupinfo=startupinfo,
                                  capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.after(0, lambda: append_log("✅ Eszközök frissítve!"))

                self.after(0, lambda s=install_success, f=install_fail:
                    append_log(f"\nTelepítés kész. Sikeres: {s}, Sikertelen: {f}"))
            else:
                self.after(0, lambda: append_log("\nNincs telepítendő driver — telepítés fázis kihagyva."))

            self.after(0, lambda: set_time(elapsed()))

            # ========================================
            # PHASE 6: Újraindítás
            # ========================================
            self.after(0, lambda: set_phase("🔵 6. FÁZIS: Automatikus újraindítás"))
            self.after(0, lambda: append_log("\n" + "=" * 50))
            self.after(0, lambda: append_log("FÁZIS 6: A gép 30 másodperc múlva újraindul!"))
            self.after(0, lambda: set_status("A gép 30 másodperc múlva újraindul..."))

            overall_secs = int(_time.time() - overall_start)
            m_total, s_total = divmod(overall_secs, 60)
            self.after(0, lambda mt=m_total, st=s_total:
                append_log(f"\n⚡ Teljes folyamat idő: {mt:02d}:{st:02d}"))
            self.after(0, lambda mt=m_total, st=s_total:
                set_time(f"Teljes idő: {mt:02d}:{st:02d}"))

            # 30 másodperc visszaszámlálás
            for countdown in range(30, 0, -1):
                self.after(0, lambda c=countdown: set_counter(f"Újraindítás {c} másodperc múlva..."))
                self.after(0, lambda c=countdown: set_progress(30 - c, 30))
                _time.sleep(1)

            # Reboot
            self.after(0, lambda: append_log("🔄 Újraindítás MOST!"))
            subprocess.run(['shutdown', '/r', '/t', '0', '/f'],
                          startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)

        def safe_worker():
            try:
                worker()
            except Exception as e:
                logging.error(f"AutoFix worker hiba: {e}")
                def on_error(err=e):
                    prog_win.protocol("WM_DELETE_WINDOW", prog_win.destroy)
                    set_phase("❌ HIBA TÖRTÉNT")
                    set_status(f"Hiba: {str(err)[:100]}")
                    append_log(f"\n❌ KRITIKUS HIBA: {err}")
                    self.autofix_btn.config(state=tk.NORMAL, text="⚡ INDÍTÁS: Teljes Driver Újratelepítés ⚡")
                self.after(0, on_error)

        threading.Thread(target=safe_worker, daemon=True).start()

    def check_wu_status(self):
        try:
            policy_disabled = False
            search_disabled = False
            
            logging.info("[WU_STATUS] === WU állapot ellenőrzés ===")
            
            # 1. Policy key (Windows 10/11)
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate", 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, "ExcludeWUDriversInQualityUpdate")
                    logging.info(f"[WU_STATUS] ExcludeWUDriversInQualityUpdate = {val}")
                    if val == 1: policy_disabled = True
            except FileNotFoundError:
                logging.info("[WU_STATUS] ExcludeWUDriversInQualityUpdate: NEM LÉTEZIK (jó)")
                
            # 2. DriverSearching key (Eszköztelepítési beállítások)
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching", 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, "SearchOrderConfig")
                    logging.info(f"[WU_STATUS] SearchOrderConfig = {val}")
                    if val == 0: search_disabled = True
            except FileNotFoundError:
                logging.info("[WU_STATUS] SearchOrderConfig: NEM LÉTEZIK")
                
            if policy_disabled and search_disabled:
                status = "Teljesen LETILTVA (Házirend és Eszközbeállítás is)"
                self.wu_status_lbl.config(text=f"Állapot: {status}", foreground="red")
            elif policy_disabled:
                status = "Házirend által LETILTVA (Képen: bekapcsolva)"
                self.wu_status_lbl.config(text=f"Állapot: {status}", foreground="red")
            elif search_disabled:
                status = "Eszközbeállításokban LETILTVA"
                self.wu_status_lbl.config(text=f"Állapot: {status}", foreground="red")
            else:
                status = "Driver frissítés ENGEDÉLYEZVE"
                self.wu_status_lbl.config(text=f"Állapot: {status}", foreground="green")
            logging.info(f"[WU_STATUS] Végeredmény: {status}")
        except Exception as e:
            logging.info(f"[WU_STATUS] HIBA: {e}")
            self.wu_status_lbl.config(text="Állapot: Ismeretlen", foreground="black")

    def restart_wu_services(self):
        """Gyors javítás: WU szolgáltatások force-stop + restart, cache nélkül"""
        prog_win = tk.Toplevel(self)
        prog_win.title("WU Szolgáltatások Újraindítása")
        prog_win.geometry("500x140")
        prog_win.transient(self)
        prog_win.grab_set()
        lbl = ttk.Label(prog_win, text="Windows Update szolgáltatások újraindítása folyamatban...\nKérlek várj!", justify=tk.CENTER, font=("Segoe UI", 10))
        lbl.pack(pady=(10, 5))
        wu_progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=420, mode='indeterminate', style="Green.Horizontal.TProgressbar")
        wu_progress.pack(pady=5)
        wu_progress.start(15)

        def _wu_restart_worker():
            log_lines = []
            def L(msg):
                logging.info(f"[WU_RESTART] {msg}")
                log_lines.append(msg)
            
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                def run_cmd(cmd, shell=False):
                    return subprocess.run(cmd, shell=shell, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, errors='replace')
                
                L("=== WU SZOLGÁLTATÁSOK GYORS ÚJRAINDÍTÁSA ===")
                
                # 1. Leállítás
                services = ['wuauserv', 'bits', 'cryptsvc', 'msiserver']
                L("1. Szolgáltatások leállítása...")
                for svc in services:
                    res = run_cmd(f'net stop {svc} /y', shell=True)
                    L(f"   net stop {svc}: rc={res.returncode}")
                
                # 2. Várakozás + force kill ha kell
                import time as _time
                _time.sleep(2)
                for svc in ['wuauserv', 'bits']:
                    chk = run_cmd(['sc', 'queryex', svc])
                    if 'STOP_PENDING' in chk.stdout or 'RUNNING' in chk.stdout:
                        for line in chk.stdout.splitlines():
                            if 'PID' in line:
                                parts = line.split(':')
                                if len(parts) >= 2:
                                    pid = parts[1].strip()
                                    if pid and pid != '0':
                                        L(f"   FORCE KILL {svc} (PID {pid})")
                                        run_cmd(f'taskkill /f /pid {pid}', shell=True)
                                        _time.sleep(1)
                
                # 3. Függőségek biztosítása
                L("2. Függő szolgáltatások indítása...")
                for svc in ['rpcss', 'cryptsvc', 'bits', 'msiserver', 'wuauserv']:
                    for attempt in range(3):
                        res = run_cmd(f'net start {svc}', shell=True)
                        started = res.returncode == 0
                        already = 'already' in res.stderr.lower() or 'already' in res.stdout.lower() or 'elindult' in res.stdout.lower() or 'm\xe1r' in res.stdout.lower()
                        L(f"   net start {svc} ({attempt+1}.): rc={res.returncode} | {res.stdout.strip()[:80]}")
                        if started or already:
                            break
                        _time.sleep(3)
                
                # 4. Állapot ellenőrzés
                L("3. Végső állapot...")
                for svc in ['wuauserv', 'bits', 'cryptsvc']:
                    chk = run_cmd(['sc', 'query', svc])
                    state = 'RUNNING' if 'RUNNING' in chk.stdout else 'STOPPED' if 'STOPPED' in chk.stdout else 'UNKNOWN'
                    L(f"   {svc}: {state}")
                
                # 5. Frissítés-keresés indítása
                L("4. Frissítés-keresés indítása...")
                run_cmd('wuauclt.exe /resetauthorization /detectnow', shell=True)
                run_cmd('UsoClient.exe StartScan', shell=True)
                
                L("=== ÚJRAINDÍTÁS KÉSZ ===")
                
                # Összesített állapot
                chk_wu = run_cmd(['sc', 'query', 'wuauserv'])
                chk_bits = run_cmd(['sc', 'query', 'bits'])
                wu_ok = 'RUNNING' in chk_wu.stdout
                bits_ok = 'RUNNING' in chk_bits.stdout
                
                def show_result():
                    if prog_win.winfo_exists(): prog_win.destroy()
                    if wu_ok and bits_ok:
                        messagebox.showinfo("Siker", "WU szolgáltatások sikeresen újraindítva!\n\n✓ Windows Update (wuauserv): FUT\n✓ BITS: FUT\n\nFrissítés-keresés elindítva.\nMenj a Beállítások > Frissítések oldalra!")
                    else:
                        status_msg = f"Windows Update: {'FUT ✓' if wu_ok else 'NEM FUT ✗'}\nBITS: {'FUT ✓' if bits_ok else 'NEM FUT ✗'}"
                        messagebox.showwarning("Részben sikeres", f"Nem minden szolgáltatás indult el:\n\n{status_msg}\n\nAjánlott: Indítsd ÚJRA a gépet!\n\nLog: driver_tool_debug.log")
                    self.check_wu_status()
                self.after(0, show_result)
            except Exception as e:
                L(f"HIBA: {e}")
                def show_err(err=e):
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba", f"Hiba történt:\n{str(err)}")
                self.after(0, show_err)

        threading.Thread(target=_wu_restart_worker, daemon=True).start()

    def disable_wu_drivers(self):
        prog_win = tk.Toplevel(self)
        prog_win.title("WU Driver Letiltás")
        prog_win.geometry("500x140")
        prog_win.transient(self)
        prog_win.grab_set()
        lbl = ttk.Label(prog_win, text="Windows Update driver letiltás folyamatban...\nKérlek várj!", justify=tk.CENTER, font=("Segoe UI", 10))
        lbl.pack(pady=(10, 5))
        wu_progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=420, mode='indeterminate', style="Green.Horizontal.TProgressbar")
        wu_progress.pack(pady=5)
        wu_progress.start(15)

        def _wu_disable_worker():
            log_lines = []
            def L(msg):
                logging.info(f"[WU_DISABLE] {msg}")
                log_lines.append(msg)

            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                L("=== WU DRIVER LETILTÁS INDÍTÁSA ===")

                # Policy - ExcludeWUDriversInQualityUpdate
                L("1. ExcludeWUDriversInQualityUpdate = 1 beállítása...")
                try:
                    key_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
                    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE) as key:
                        winreg.SetValueEx(key, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 1)
                    L("   OK: winreg beállítva")
                except Exception as e:
                    L(f"   HIBA winreg: {e}")

                res = subprocess.run(['reg', 'add', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate', '/v', 'ExcludeWUDriversInQualityUpdate', '/t', 'REG_DWORD', '/d', '1', '/f'],
                                     startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, errors='replace')
                L(f"   reg.exe eredmény: rc={res.returncode} | {res.stdout.strip()} {res.stderr.strip()}")

                # SearchOrderConfig = 0
                L("2. SearchOrderConfig = 0 beállítása...")
                try:
                    key_path2 = r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching"
                    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path2, 0, winreg.KEY_WRITE) as key:
                        winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 0)
                    L("   OK: winreg beállítva")
                except Exception as e:
                    L(f"   HIBA winreg: {e}")

                res = subprocess.run(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching', '/v', 'SearchOrderConfig', '/t', 'REG_DWORD', '/d', '0', '/f'],
                                     startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, errors='replace')
                L(f"   reg.exe eredmény: rc={res.returncode} | {res.stdout.strip()} {res.stderr.strip()}")

                # WU újraindítás
                L("3. WU szolgáltatás újraindítása...")
                res = subprocess.run("net stop wuauserv & net start wuauserv", shell=True, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, errors='replace')
                L(f"   net stop/start: rc={res.returncode} | {res.stdout.strip()}")

                # Ellenőrzés
                L("4. Ellenőrzés (visszaolvasás)...")
                try:
                    res_chk = subprocess.run(['reg', 'query', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate', '/v', 'ExcludeWUDriversInQualityUpdate'],
                                             startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, errors='replace')
                    L(f"   ExcludeWUDrivers: {res_chk.stdout.strip()}")
                except Exception: pass
                try:
                    res_chk2 = subprocess.run(['reg', 'query', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching', '/v', 'SearchOrderConfig'],
                                              startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, errors='replace')
                    L(f"   SearchOrderConfig: {res_chk2.stdout.strip()}")
                except Exception: pass

                L("=== LETILTÁS BEFEJEZVE ===")

                def show_result():
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showinfo("Siker", "Windows Update driver telepítés sikeresen LETILTVA.\n\n(A Windows Update szolgáltatás újraindult a háttérben.)\n\nRészletes log: driver_tool_debug.log")
                    self.check_wu_status()
                self.after(0, show_result)
            except PermissionError:
                L("PERMISSION ERROR - Nincs admin jog!")
                def show_perm_err():
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba", "Nincs jogosultság a Registry írásához. Futtasd Rendszergazdaként!")
                self.after(0, show_perm_err)
            except Exception as e:
                L(f"VÁRATLAN HIBA: {e}")
                def show_err(err=e):
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba", f"Hiba történt:\n{str(err)}\n\nLog:\n" + "\n".join(log_lines[-10:]))
                self.after(0, show_err)

        threading.Thread(target=_wu_disable_worker, daemon=True).start()

    def enable_wu_drivers(self):
        prog_win = tk.Toplevel(self)
        prog_win.title("WU Driver Engedélyezés + Reset")
        prog_win.geometry("500x140")
        prog_win.transient(self)
        prog_win.grab_set()
        lbl = ttk.Label(prog_win, text="Windows Update driver engedélyezés és teljes reset folyamatban...\nEz akár 1-2 percig is eltarthat, kérlek várj!", justify=tk.CENTER, font=("Segoe UI", 10))
        lbl.pack(pady=(10, 5))
        wu_progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=420, mode='indeterminate', style="Green.Horizontal.TProgressbar")
        wu_progress.pack(pady=5)
        wu_progress.start(15)

        def _wu_enable_worker():
            log_lines = []
            def L(msg):
                logging.info(f"[WU_ENABLE] {msg}")
                log_lines.append(msg)

            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                import time as _time

                def run_cmd(cmd, shell=False):
                    return subprocess.run(cmd, shell=shell, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, errors='replace')

                def stop_service(svc):
                    L(f"   Leállítás: {svc}...")
                    res = run_cmd(f'net stop {svc} /y', shell=True)
                    L(f"   net stop {svc}: rc={res.returncode} | {res.stdout.strip()}")
                    for i in range(15):
                        chk = run_cmd(['sc', 'query', svc])
                        if 'STOPPED' in chk.stdout or 'not been started' in chk.stderr.lower() or chk.returncode != 0:
                            L(f"   {svc}: STOPPED ({i}s)")
                            return True
                        if 'STOP_PENDING' in chk.stdout:
                            L(f"   {svc}: STOP_PENDING... várakozás ({i+1}/15)")
                            _time.sleep(1)
                        else:
                            break
                    chk = run_cmd(['sc', 'queryex', svc])
                    L(f"   {svc} queryex: {chk.stdout.strip()}")
                    if 'STOP_PENDING' in chk.stdout or 'RUNNING' in chk.stdout:
                        for line in chk.stdout.splitlines():
                            if 'PID' in line:
                                parts = line.split(':')
                                if len(parts) >= 2:
                                    pid = parts[1].strip()
                                    if pid and pid != '0':
                                        L(f"   FORCE KILL: taskkill /f /pid {pid}")
                                        kres = run_cmd(f'taskkill /f /pid {pid}', shell=True)
                                        L(f"   taskkill: rc={kres.returncode} | {kres.stdout.strip()} {kres.stderr.strip()}")
                                        _time.sleep(2)
                                        return True
                    L(f"   {svc}: Nem sikerült leállítani, de folytatjuk...")
                    return False

                L("=== WU DRIVER ENGEDÉLYEZÉS + TELJES RESET INDÍTÁSA ===")

                # 1. Policy törlés winreg-gel
                key_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
                L("1. ExcludeWUDriversInQualityUpdate policy TÖRLÉSE (winreg)...")
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE) as key:
                        winreg.DeleteValue(key, "ExcludeWUDriversInQualityUpdate")
                    L("   OK: winreg DeleteValue sikeres")
                except FileNotFoundError:
                    L("   INFO: Nem létezett (FileNotFoundError) - nincs teendő")
                except Exception as e:
                    L(f"   HIBA winreg törlés: {e} - fallback 0-ra állítás...")
                    try:
                        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE) as key:
                            winreg.SetValueEx(key, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 0)
                        L("   OK: fallback 0-ra állítás sikeres")
                    except Exception as e2:
                        L(f"   HIBA fallback is: {e2}")

                # 2. SearchOrderConfig = 1 winreg-gel
                key_path2 = r"SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching"
                L("2. SearchOrderConfig = 1 beállítása (winreg)...")
                try:
                    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path2, 0, winreg.KEY_WRITE) as key:
                        winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 1)
                    L("   OK: winreg beállítva")
                except Exception as e:
                    L(f"   HIBA winreg: {e}")

                # 3. reg.exe fallback - SearchOrderConfig
                L("3. reg.exe fallback: SearchOrderConfig = 1...")
                res = run_cmd(['reg', 'add', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching', '/v', 'SearchOrderConfig', '/t', 'REG_DWORD', '/d', '1', '/f'])
                L(f"   rc={res.returncode} | {res.stdout.strip()} {res.stderr.strip()}")

                # 4. reg.exe fallback - Policy törlés
                L("4. reg.exe fallback: ExcludeWUDrivers policy törlése...")
                res = run_cmd(['reg', 'delete', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate', '/v', 'ExcludeWUDriversInQualityUpdate', '/f'])
                L(f"   rc={res.returncode} | {res.stdout.strip()} {res.stderr.strip()}")

                # 5. NoAutoUpdate törlés
                L("5. NoAutoUpdate policy törlése...")
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU", 0, winreg.KEY_WRITE) as key:
                        winreg.DeleteValue(key, "NoAutoUpdate")
                    L("   OK: NoAutoUpdate törölve")
                except FileNotFoundError:
                    L("   INFO: NoAutoUpdate nem létezett")
                except Exception as e:
                    L(f"   HIBA: {e}")

                # 6. Szolgáltatások leállítása (FORCE KILL ha kell!)
                L("6. WU szolgáltatások leállítása (force kill ha kell)...")
                for svc in ['wuauserv', 'bits', 'cryptsvc']:
                    stop_service(svc)

                # Extra várakozás hogy a fájlok felszabaduljanak
                L("   Extra 3s várakozás fájl-zárolás feloldásra...")
                _time.sleep(3)

                # 7. SoftwareDistribution törlése (retry-val!)
                sysroot = os.environ.get('SYSTEMROOT', r'C:\Windows')
                sw_dist = os.path.join(sysroot, 'SoftwareDistribution')
                L(f"7. SoftwareDistribution mappa törlése: {sw_dist}")
                for attempt in range(3):
                    try:
                        if os.path.exists(sw_dist):
                            shutil.rmtree(sw_dist, ignore_errors=False)
                            L(f"   OK: törölve ({attempt+1}. próbálkozás)")
                            break
                        else:
                            L("   INFO: Mappa nem létezett")
                            break
                    except Exception as e:
                        L(f"   {attempt+1}. próba HIBA: {e}")
                        if attempt < 2:
                            L(f"   Újrapróbálás 3s múlva...")
                            _time.sleep(3)
                # Ha még mindig ott van, próbáljuk ignore_errors-szal + rd /s /q
                if os.path.exists(sw_dist):
                    shutil.rmtree(sw_dist, ignore_errors=True)
                    res = run_cmd(f'rd /s /q "{sw_dist}"', shell=True)
                    L(f"   rd /s /q fallback: rc={res.returncode} | létezik még: {os.path.exists(sw_dist)}")

                # 8. catroot2 átnevezése
                catroot2 = os.path.join(sysroot, 'System32', 'catroot2')
                bak = catroot2 + '.bak'
                L(f"8. catroot2 átnevezése: {catroot2} -> {bak}")
                try:
                    if os.path.exists(bak):
                        shutil.rmtree(bak, ignore_errors=True)
                        L("   Régi .bak törölve")
                    if os.path.exists(catroot2):
                        os.rename(catroot2, bak)
                        L("   OK: átnevezve")
                    else:
                        L("   INFO: catroot2 mappa nem létezett")
                except Exception as e:
                    L(f"   HIBA: {e}")

                # 9. WU DLL-ek újraregisztrálása (TELJES ÚTVONALLAL!)
                sys32 = os.path.join(sysroot, 'System32')
                L(f"9. WU DLL-ek újraregisztrálása ({sys32})...")
                for dll in ['wuaueng.dll', 'wuapi.dll', 'wups.dll', 'wups2.dll', 'wuwebv.dll', 'wucltux.dll']:
                    full_path = os.path.join(sys32, dll)
                    exists = os.path.exists(full_path)
                    L(f"   {dll}: létezik={exists}")
                    if exists:
                        res = run_cmd(f'regsvr32.exe /s "{full_path}"', shell=True)
                        L(f"   regsvr32 {dll}: rc={res.returncode} | {res.stderr.strip()}")
                    else:
                        L(f"   KIHAGYVA (nem létezik): {full_path}")

                # 10. Winsock reset
                L("10. Winsock reset...")
                res = run_cmd('netsh winsock reset', shell=True)
                L(f"    rc={res.returncode} | {res.stdout.strip()} {res.stderr.strip()}")

                # 11. Szolgáltatások indítása (retry-val!)
                L("11. Szolgáltatások indítása (cryptsvc, bits, wuauserv)...")
                for svc in ['cryptsvc', 'bits', 'wuauserv']:
                    for attempt in range(3):
                        res = run_cmd(f'net start {svc}', shell=True)
                        L(f"    net start {svc} ({attempt+1}.): rc={res.returncode} | {res.stdout.strip()} {res.stderr.strip()}")
                        if res.returncode == 0 or 'already been started' in res.stderr.lower() or 'already been started' in res.stdout.lower() or 'm\xe1r elindult' in res.stdout.lower():
                            break
                        if 'elindul vagy' in res.stdout or 'being started' in res.stderr.lower():
                            L(f"    {svc}: Még indul... várunk 5s")
                            _time.sleep(5)
                        else:
                            _time.sleep(2)

                # 12. Kényszerített frissítés-keresés
                L("12. wuauclt /resetauthorization /detectnow...")
                res = run_cmd('wuauclt.exe /resetauthorization /detectnow', shell=True)
                L(f"    rc={res.returncode} | {res.stdout.strip()} {res.stderr.strip()}")

                # Próbáljuk a modernebb UsoClient-et is
                L("12b. UsoClient StartScan (Win10+)...")
                res = run_cmd('UsoClient.exe StartScan', shell=True)
                L(f"    rc={res.returncode} | {res.stdout.strip()} {res.stderr.strip()}")

                # 13. Végső ellenőrzés
                L("13. Végső ellenőrzés (registry + service visszaolvasás)...")
                try:
                    res_chk = run_cmd(['reg', 'query', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate', '/v', 'ExcludeWUDriversInQualityUpdate'])
                    L(f"    ExcludeWUDrivers: rc={res_chk.returncode} | {res_chk.stdout.strip()} {res_chk.stderr.strip()}")
                except Exception: pass
                try:
                    res_chk2 = run_cmd(['reg', 'query', r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching', '/v', 'SearchOrderConfig'])
                    L(f"    SearchOrderConfig: {res_chk2.stdout.strip()}")
                except Exception: pass
                try:
                    res_chk3 = run_cmd(['sc', 'query', 'wuauserv'])
                    L(f"    wuauserv állapot: {res_chk3.stdout.strip()}")
                except Exception: pass
                L(f"    SoftwareDistribution létezik: {os.path.exists(sw_dist)}")
                L(f"    catroot2 létezik: {os.path.exists(catroot2)}")
                L(f"    catroot2.bak létezik: {os.path.exists(bak)}")

                L("=== WU ENGEDÉLYEZÉS + RESET BEFEJEZVE ===")

                def show_result():
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showinfo("Siker", "Windows Update driver telepítés sikeresen VISSZAÁLLÍTVA.\n\n• Házirend policy TÖRÖLVE\n• WU cache törölve (SoftwareDistribution)\n• Catroot2 alaphelyzetbe állítva\n• WU DLL-ek újraregisztrálva\n• Winsock reset\n• WU szolgáltatás újraindítva\n• Frissítés-keresés elindítva\n\nRészletes log: driver_tool_debug.log\n\nAjánlott: Indítsd ÚJRA a gépet, majd menj a\nBeállítások > Frissítések oldalra!")
                    self.check_wu_status()
                self.after(0, show_result)
            except PermissionError:
                L("PERMISSION ERROR - Nincs admin jog!")
                def show_perm_err():
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba", "Nincs jogosultság a Registry írásához. Futtasd Rendszergazdaként!")
                self.after(0, show_perm_err)
            except Exception as e:
                L(f"VÁRATLAN HIBA: {e}")
                def show_err(err=e):
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba", f"Hiba történt:\n{str(err)}\n\nLog:\n" + "\n".join(log_lines[-10:]))
                self.after(0, show_err)

        threading.Thread(target=_wu_enable_worker, daemon=True).start()

    def create_restore_point(self):
        desc = f"Driver_Cleaner_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        prog_win = tk.Toplevel(self)
        prog_win.title("Visszaállítási Pont")
        prog_win.geometry("500x160")
        prog_win.transient(self)
        prog_win.grab_set()
        lbl = ttk.Label(prog_win, text="Rendszer-visszaállítási pont létrehozása folyamatban...\nEz eltarthat egy percig, kérlek várj!", justify=tk.CENTER, font=("Segoe UI", 10))
        lbl.pack(pady=(10, 5))
        status_lbl = ttk.Label(prog_win, text="Rendszervédelem ellenőrzése...", font=("Segoe UI", 9))
        status_lbl.pack(pady=(0, 5))
        rp_progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=420, mode='indeterminate', style="Green.Horizontal.TProgressbar")
        rp_progress.pack(pady=5)
        rp_progress.start(15)

        def _rp_worker():
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si_flags = dict(startupinfo=startupinfo, capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)

                # 1) Rendszervédelem engedélyezése C: meghajtón (ha nincs bekapcsolva)
                self.after(0, lambda: status_lbl.config(text="Rendszervédelem engedélyezése a C: meghajtón..."))
                enable_cmd = 'powershell.exe -ExecutionPolicy Bypass -NoProfile -Command "Enable-ComputerRestore -Drive \"C:\\\" -ErrorAction Stop"'
                enable_res = subprocess.run(enable_cmd, shell=True, **si_flags)
                if enable_res.returncode != 0:
                    err_msg = (enable_res.stderr or enable_res.stdout or "Ismeretlen hiba").strip()
                    def show_enable_err(msg=err_msg):
                        if prog_win.winfo_exists(): prog_win.destroy()
                        messagebox.showerror("Rendszervédelem Hiba",
                            f"Nem sikerült engedélyezni a Rendszervédelmet a C: meghajtón!\n\n"
                            f"Lehetséges okok:\n"
                            f"• A program nem fut rendszergazdaként\n"
                            f"• Csoportházirend (GPO) tiltja\n"
                            f"• A meghajtó nem támogatja\n\n"
                            f"Hibaüzenet:\n{msg}")
                    self.after(0, show_enable_err)
                    return

                # 2) Visszaállítási pont létrehozása
                self.after(0, lambda: status_lbl.config(text=f"Visszaállítási pont mentése: {desc}"))
                create_cmd = f'powershell.exe -ExecutionPolicy Bypass -NoProfile -Command "Checkpoint-Computer -Description \'{desc}\' -RestorePointType \'MODIFY_SETTINGS\' -ErrorAction Stop"'
                res = subprocess.run(create_cmd, shell=True, **si_flags)

                # 3) Ellenőrzés — tényleg létrejött-e?
                self.after(0, lambda: status_lbl.config(text="Visszaállítási pont ellenőrzése..."))
                verify_cmd = f'powershell.exe -ExecutionPolicy Bypass -NoProfile -Command "(Get-ComputerRestorePoint | Where-Object {{ $_.Description -eq \'{desc}\' }}).Description"'
                verify_res = subprocess.run(verify_cmd, shell=True, **si_flags)
                verified = desc in (verify_res.stdout or '')

                def show_result():
                    if prog_win.winfo_exists(): prog_win.destroy()
                    if res.returncode == 0 and verified:
                        messagebox.showinfo("Siker", f"A '{desc}' nevű visszaállítási pont sikeresen létrejött és ellenőrizve!")
                    elif res.returncode == 0:
                        messagebox.showwarning("Figyelem",
                            f"A Checkpoint-Computer lefutott (kód: 0), de a visszaállítási pont NEM található a listában.\n\n"
                            f"Lehetséges ok: a Windows 24 órán belül már készített egy pontot, és nem engedélyez újat.\n\n"
                            f"Ellenőrizd kézzel: Start → 'rstrui' → Enter")
                    else:
                        err_msg = (res.stderr or res.stdout or "Ismeretlen hiba").strip()
                        messagebox.showerror("Hiba",
                            f"Nem sikerült létrehozni a visszaállítási pontot!\n\n"
                            f"Hibaüzenet:\n{err_msg}")
                self.after(0, show_result)
            except Exception as e:
                def show_err(err=e):
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba", f"Kivétel történt:\n{str(err)}")
                self.after(0, show_err)

        threading.Thread(target=_rp_worker, daemon=True).start()

    def backup_drivers(self):
        dest_dir = filedialog.askdirectory(title="Válassz egy mappát a driverek kimentéséhez")
        if not dest_dir:
            return
            
        backup_folder = os.path.join(dest_dir, f"Driver_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(backup_folder, exist_ok=True)
        
        total_guess = len(self.tree.get_children())
        prog_win, progress, status_lbl, counter_lbl, log_text, append_log = self._create_progress_window(
            "Exportálás folyamatban...",
            f"Driverek kimentése folyamatban ide:\n{backup_folder}\nKérlek várj...",
            width=550, height=250, mode='determinate', maximum=max(total_guess, 1), has_log=False
        )

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
                            counter_lbl.config(text=f"{v} / {mg}")
                        self.after(0, update_prog)
                    elif ".inf" in line.lower():
                        current_val += 1
                        def step_prog(v=current_val, txt=line):
                            if progress['maximum'] < v: progress.config(maximum=v+5)
                            progress['value'] = v
                            short_txt = txt if len(txt) < 65 else txt[:62] + "..."
                            status_lbl.config(text=short_txt)
                            counter_lbl.config(text=f"{v}")
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

    def backup_all_drivers(self):
        """ÖSSZES driver (third-party + Windows inbox) lementése pnputil-lal."""
        dest_dir = filedialog.askdirectory(title="Válassz egy mappát az ÖSSZES driver kimentéséhez")
        if not dest_dir:
            return

        backup_folder = os.path.join(dest_dir, f"ALL_Driver_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(backup_folder, exist_ok=True)

        prog_win, progress, status_lbl, counter_lbl, log_text, append_log = self._create_progress_window(
            "ÖSSZES Driver Exportálása...",
            f"Összes driver (Third Party + Windows) kimentése ide:\n{backup_folder}\nEz több percig is eltarthat!",
            width=650, height=400, mode='indeterminate'
        )

        def worker():
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                self.after(0, lambda: append_log("1. lépés: Driver lista lekérdezése (pnputil /enum-drivers)..."))
                self.after(0, lambda: status_lbl.config(text="Driver lista lekérdezése..."))

                # Összes driver felsorolása
                enum_res = subprocess.run(
                    ['pnputil', '/enum-drivers'],
                    capture_output=True, text=True, errors='replace',
                    startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
                )

                # .inf nevek kinyerése
                import re as _re
                all_infs = _re.findall(r'(oem\d+\.inf)', enum_res.stdout, _re.IGNORECASE)
                # Windows inbox driverek is kellenek — azokat a DriverStore-ból szedjük
                driverstore_path = os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), 'System32', 'DriverStore', 'FileRepository')

                self.after(0, lambda c=len(all_infs): append_log(f"  Talált OEM driverek: {c} db"))

                # 2. lépés: OEM driverek exportálása pnputil-lal egyenként
                self.after(0, lambda: append_log("\n2. lépés: OEM driverek exportálása egyenként..."))

                total_oem = len(all_infs)
                success_count = 0
                fail_count = 0

                if total_oem > 0:
                    def switch_det(t=total_oem):
                        try: progress.stop()
                        except Exception: pass
                        progress.config(mode='determinate', maximum=t, value=0)
                    self.after(0, switch_det)

                for i, inf_name in enumerate(all_infs):
                    self.after(0, lambda idx=i+1, t=total_oem, nm=inf_name: (
                        progress.config(value=idx),
                        status_lbl.config(text=f"Export: {nm} ({idx}/{t})"),
                        counter_lbl.config(text=f"{idx} / {t}")
                    ))

                    inf_folder = os.path.join(backup_folder, inf_name.replace('.inf', ''))
                    os.makedirs(inf_folder, exist_ok=True)

                    res = subprocess.run(
                        ['pnputil', '/export-driver', inf_name, inf_folder],
                        capture_output=True, text=True, errors='replace',
                        startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if res.returncode == 0:
                        success_count += 1
                    else:
                        fail_count += 1
                        self.after(0, lambda nm=inf_name, e=res.stdout.strip()[:100]: append_log(f"  ❌ {nm}: {e}"))

                self.after(0, lambda s=success_count, f=fail_count: append_log(f"\n  OEM export kész: ✅ {s} sikeres, ❌ {f} sikertelen"))

                # 3. lépés: DriverStore FileRepository teljes másolása (inbox driverek)
                self.after(0, lambda: append_log("\n3. lépés: Windows inbox driverek másolása (DriverStore)..."))
                self.after(0, lambda: status_lbl.config(text="Windows inbox driverek másolása..."))
                self.after(0, lambda: progress.config(mode='indeterminate'))
                self.after(0, lambda: progress.start(15))

                inbox_folder = os.path.join(backup_folder, '_Windows_Inbox_Drivers')
                os.makedirs(inbox_folder, exist_ok=True)

                # robocopy a teljes FileRepository-t másolja
                robo_res = subprocess.run(
                    ['robocopy', driverstore_path, inbox_folder, '/E', '/R:0', '/W:0', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP'],
                    capture_output=True, text=True, errors='replace',
                    startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
                )
                # robocopy 0-7 mind "sikeres" (8+ a hiba)
                if robo_res.returncode < 8:
                    self.after(0, lambda: append_log("  ✅ Windows inbox driverek sikeresen másolva!"))
                else:
                    self.after(0, lambda rc=robo_res.returncode: append_log(f"  ⚠ Robocopy figyelmeztetés, kód: {rc} (nem minden fájl másolódott)"))

                # Összegzés
                total_size = 0
                for dirpath, dirnames, filenames in os.walk(backup_folder):
                    for f in filenames:
                        try:
                            total_size += os.path.getsize(os.path.join(dirpath, f))
                        except OSError:
                            pass
                size_mb = total_size / (1024 * 1024)

                def finish():
                    try: progress.stop()
                    except Exception: pass
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showinfo("ÖSSZES Driver Export Kész",
                        f"Az összes driver sikeresen lementve ide:\n{backup_folder}\n\n"
                        f"📦 OEM (third-party): {success_count} db\n"
                        f"📦 Windows inbox: DriverStore másolva\n"
                        f"📁 Összes méret: {size_mb:.0f} MB\n\n"
                        f"Visszaállításhoz használd a 'Lementett Driverek Visszaállítása' gombot!")
                self.after(0, finish)

            except Exception as e:
                def on_err(err=e):
                    try: progress.stop()
                    except Exception: pass
                    if prog_win.winfo_exists(): prog_win.destroy()
                    messagebox.showerror("Hiba", f"Váratlan hiba az exportálás során:\n{str(err)}")
                self.after(0, on_err)

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
        prog_win.geometry("600x200")
        prog_win.transient(self)
        prog_win.grab_set()

        lbl = ttk.Label(prog_win, text=f"Windows Image csatolása és gyári driverek kinyerése...\nEz több percig is eltarthat, a háttérben folyik a művelet!", justify=tk.CENTER, font=("Segoe UI", 10))
        lbl.pack(pady=(10, 5))

        counter_lbl = ttk.Label(prog_win, text="", font=("Segoe UI", 10, "bold"))
        counter_lbl.pack(pady=(0, 2))

        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=520, mode='indeterminate', style="Green.Horizontal.TProgressbar")
        progress.pack(pady=5)
        progress.start(15)

        status_lbl = ttk.Label(prog_win, text="WIM fájl csatolása (Mount)...", font=("Segoe UI", 9))
        status_lbl.pack(pady=5)
        
        def worker():
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                # 1. Mount image
                self.after(0, lambda: (status_lbl.config(text="Képfájl csatolása a Temp mappába (Türelem, 4-5 perc is lehet!)..."), counter_lbl.config(text="1 / 3")))
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
                self.after(0, lambda: (status_lbl.config(text="Gyári DriverStore másolása (1-2 GB adat)..."), counter_lbl.config(text="2 / 3")))
                driverstore_path = os.path.join(mount_dir, "Windows", "System32", "DriverStore", "FileRepository")
                logging.info(f"DriverStore masolasa innen: {driverstore_path}")
                if os.path.exists(driverstore_path):
                    shutil.copytree(driverstore_path, target_folder, dirs_exist_ok=True)
                else:
                    raise Exception("A FileRepository (gyári driver mappa) nem található a csatolt WIM fájlban!")
                
                # 3. Biztonságos Unmount
                self.after(0, lambda: (status_lbl.config(text="WIM leválasztása (Takarítás)..."), counter_lbl.config(text="3 / 3")))
                logging.info("WIM unmountolasa...")
                unmount_cmd = ["dism", "/Unmount-Image", f"/MountDir:{mount_dir}", "/Discard"]
                subprocess.run(unmount_cmd, capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                
                try:
                    shutil.rmtree(mount_dir, ignore_errors=True)
                except Exception: pass

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
                except Exception: pass
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

        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, mode='indeterminate', style="Green.Horizontal.TProgressbar")
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
                    except Exception:
                        pass
                logging.info(f"[RESTORE] {msg}")
                def gui_up():
                    try:
                        log_text.insert(tk.END, msg + '\n')
                        if auto_scroll.get():
                            log_text.see(tk.END)
                        short_txt = msg.strip() if len(msg.strip()) < 100 else msg.strip()[:97] + "..."
                        status_lbl.config(text=short_txt)
                    except Exception:
                        pass
                self.after(0, gui_up)

            try:
                write_log(f"=== {'ONLINE' if online else 'OFFLINE'} DRIVER RESTORE INDÍTÁSA ===")
                write_log(f"Forrás könyvtár: {source_dir}")
                write_log(f"Célpont / OS Meghajtó: {target_dir}")
                write_log("Felkészülés a parancsok futtatására...")

                process_returncode = 0  # Default value for paths that don't generate a process

                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                import os
                
                # Szigorú backslash konverzió a natív parancssori eszközöknek
                norm_source = os.path.normpath(source_dir).replace('/', '\\') if source_dir else None
                norm_target = os.path.normpath(target_dir).replace('/', '\\') if target_dir else None

                is_inbox_restore = (not online) and ("Windows_Gyari_Alap_Driverek" in norm_source)

                if is_inbox_restore:
                    write_log("Gyári Windows (inbox) driverek felismerve!")
                    write_log("A DISM offline nem képes inbox drivereket telepíteni => Közvetlen FileRepository másolás + Boot Service aktiválva.")
                    
                    # 1. LÉPÉS: Közvetlen másolás a DriverStore\FileRepository alá (azonnali hatás bootoláskor)
                    target_filerepo = os.path.join(norm_target, "Windows", "System32", "DriverStore", "FileRepository")
                    write_log(f"Fájlok másolása közvetlenül a FileRepository-ba: {norm_source} -> {target_filerepo}")
                    import shutil
                    copied_count = 0
                    error_count = 0
                    try:
                        os.makedirs(target_filerepo, exist_ok=True)
                        for item in os.listdir(norm_source):
                            src_item = os.path.join(norm_source, item)
                            dst_item = os.path.join(target_filerepo, item)
                            try:
                                if os.path.isdir(src_item):
                                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                                else:
                                    shutil.copy2(src_item, dst_item)
                                copied_count += 1
                            except Exception as ce:
                                error_count += 1
                                write_log(f"  Figyelem: {item} másolási hiba: {ce}")
                        write_log(f"FileRepository másolás KÉSZ! Sikeres: {copied_count}, Hibás: {error_count}")
                    except Exception as fe:
                        write_log(f"HIBA a FileRepository másolás során: {fe}")
                    
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
                    process_returncode = process.returncode
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
                    process_returncode = process.returncode

                if online:
                    is_pe = os.environ.get('SystemDrive', 'C:') == 'X:' or getattr(self, 'sys_drive', '').upper() == 'X:\\'
                    if not is_pe:
                        write_log("Hardverváltozások keresése és eszközök frissítése az Eszközkezelőben...")
                        import time
                        time.sleep(1.5)
                        scan_proc = subprocess.run(['pnputil', '/scan-devices'], startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, errors='replace')
                        write_log("SCAN_DEVICES Kész! Kimenet:\n" + scan_proc.stdout)
                        time.sleep(3.5)
                    else:
                        write_log("WinPE környezet érzékelve, hardverváltozások scannelése kihagyva az élő (X:) rendszeren.")
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
                    bat_content = "@echo off\n" \
                                  "set LOGFILE=\"%SystemDrive%\\Users\\Public\\driver_startup_log.txt\"\n" \
                                  "echo ---------------------------------------- >> %LOGFILE%\n" \
                                  "echo [%DATE% %TIME%] Boot elotti SYSTEM telepites service (No UAC! Azonnali!) >> %LOGFILE%\n" \
                                  "echo [%DATE% %TIME%] Ideiglenes szerviz torlese a registrybol is... >> %LOGFILE%\n" \
                                  "sc delete DriverRestoreSvc >> %LOGFILE% 2>&1\n" \
                                  "echo [%DATE% %TIME%] Varakozas a Windows PlugAndPlay szolgaltatasara (15 sec max)... >> %LOGFILE%\n" \
                                  "ping 127.0.0.1 -n 15 > nul\n" \
                                  "echo [%DATE% %TIME%] Driverek betoltese (Csendes mod)... kerlek varj! >> %LOGFILE%\n" \
                                  "pnputil /add-driver \"%SystemDrive%\\TempRunDrivers\\*.inf\" /subdirs /install >> %LOGFILE% 2>&1\n" \
                                  "echo [%DATE% %TIME%] pnputil scan-devices inditasa... >> %LOGFILE%\n" \
                                  "pnputil /scan-devices >> %LOGFILE% 2>&1\n" \
                                  "echo [%DATE% %TIME%] Ideiglenes mappak torlese... >> %LOGFILE%\n" \
                                  "rd /s /q \"%SystemDrive%\\TempRunDrivers\" >> %LOGFILE% 2>&1\n" \
                                  "echo [%DATE% %TIME%] Befejezve. Torlom a scriptet. >> %LOGFILE%\n" \
                                  "ping 127.0.0.1 -n 3 > nul\n" \
                                  "(goto) 2>nul & del \"%~f0\"\n"
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
                                bat_target_path = r'cmd.exe /c "%SystemDrive%\ProgramData\auto_pnputil_scan.bat"'
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
                        if process_returncode == 0:
                            log_text.config(fg="#00FF00")   # green
                        else:
                            log_text.config(fg="#FFFF00")   # yellow/warning

                    except Exception: pass
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
                    except Exception: pass
                self.after(0, crash_gui)
            finally:
                if log_handle:
                    try:
                        log_handle.close()
                    except Exception: pass

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

    # 1. Globális exception (kivétel) logoló - minden, ami elszállna (akár csendben is), beleíródik a fájlba
    def global_exception_handler(exc_type, exc_value, exc_traceback):
        logging.exception("VÁRATLAN FATÁLIS HIBA (Főszál):", exc_info=(exc_type, exc_value, exc_traceback))
    sys.excepthook = global_exception_handler

    # 2. Háttérszálak (thread) exception logolója (hogy a néma crasheket is megfogjuk)
    import threading
    def thread_exception_handler(args):
        logging.exception("VÁRATLAN HIBA EGY HÁTTÉRSZÁLBAN (Thread):", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = thread_exception_handler

    logging.info("==================================================")
    logging.info("ULTIMATE DRIVER GYILKOLO (es telepito) SZERVIZ TOOL ELINDITVA")
    logging.info(f"Futtatasi konyvtar: {os.getcwd()}")
    logging.info("==================================================")

    app = DriverCleanerApp()
    
    # 3. Tkinter (GUI) gombnyomás/grafikus hibák logolója
    def tkinter_exception_handler(exc_type, exc_value, exc_traceback):
        logging.exception("GUI HIBA (Tkinter callback):", exc_info=(exc_type, exc_value, exc_traceback))
    app.report_callback_exception = tkinter_exception_handler

    app.mainloop()
