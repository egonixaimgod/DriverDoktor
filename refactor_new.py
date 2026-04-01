import re

with open('driver_tool.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_ui = '''    def __init__(self):
        super().__init__()
        self.title("Windows Driver Szerviz & Tisztító Eszköz")
        self.geometry("1300x800")
        
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except:
            pass
        
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TLabelframe.Label", font=("Segoe UI", 11, "bold"), foreground="#003366")
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=6)
        style.configure("Danger.TButton", font=("Segoe UI", 10, "bold"), foreground="red")
        style.configure("Active.TButton", background="#4CAF50", foreground="white")
        
        try:
            self.iconbitmap(resource_path("icon.ico"))
        except:
            pass
        
        self.target_os_path = None
        self.sys_drive = os.path.splitdrive(os.environ.get('WINDIR', 'C:\\\\'))[0] + "\\\\"
        self.selected_drive = self.sys_drive
        self.current_menu = "driver"
        
        self.available_drives = self.get_available_drives()
        
        self.create_main_layout()
        self.refresh_drivers()
        self.check_wu_status()

    def get_available_drives(self):
        drives = []
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:\\\\\\"
            if os.path.exists(drive):
                drives.append(drive)
        return sorted(drives)

    def create_main_layout(self):
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=5, pady=5)
        
        top_label = ttk.Label(top_frame, text="Válassz cél-meghajtót:", font=("Segoe UI", 10, "bold"))
        top_label.pack(side=tk.LEFT, padx=(0, 10))
        
        drives_frame = ttk.Frame(top_frame)
        drives_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.drive_buttons = {}
        for drive in self.available_drives:
            btn = tk.Button(
                drives_frame, text=drive, command=lambda d=drive: self.select_drive(d),
                font=("Segoe UI", 9, "bold"), width=5, relief=tk.RAISED,
                bg="#4CAF50" if drive == self.sys_drive else "#e0e0e0",
                fg="white" if drive == self.sys_drive else "black"
            )
            btn.pack(side=tk.LEFT, padx=2)
            self.drive_buttons[drive] = btn
        
        self.drive_status_lbl = ttk.Label(
            top_frame, text=f"Jelenleg a {self.sys_drive} meghajtót módosítod! (ÉLŐRENDSZER)",
            font=("Segoe UI", 10, "bold"), foreground="#2e7d32"
        )
        self.drive_status_lbl.pack(side=tk.RIGHT, padx=10)
        
        sep1 = ttk.Separator(self, orient=tk.HORIZONTAL)
        sep1.pack(fill=tk.X)
        
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        left_menu = ttk.Frame(main_frame, width=180)
        left_menu.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        left_menu.pack_propagate(False)
        
        self.menu_buttons = {}
        
        btn_driver = tk.Button(left_menu, text="Driver Kezelő", command=lambda: self.switch_menu("driver"), font=("Segoe UI", 11, "bold"), relief=tk.SUNKEN, bg="#4CAF50", fg="white", height=2)
        btn_driver.pack(fill=tk.X, pady=5)
        self.menu_buttons["driver"] = btn_driver
        
        btn_wu = tk.Button(left_menu, text="Windows Update", command=lambda: self.switch_menu("update"), font=("Segoe UI", 11, "bold"), relief=tk.RAISED, bg="#f0f0f0", fg="black", height=2)
        btn_wu.pack(fill=tk.X, pady=5)
        self.menu_buttons["update"] = btn_wu
        
        btn_restore = tk.Button(left_menu, text="Rendszervisszaállítás", command=lambda: self.switch_menu("restore"), font=("Segoe UI", 11, "bold"), relief=tk.RAISED, bg="#f0f0f0", fg="black", height=2)
        btn_restore.pack(fill=tk.X, pady=5)
        self.menu_buttons["restore"] = btn_restore
        
        self.content_frame = ttk.Frame(main_frame)
        self.content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.switch_menu("driver")

    def select_drive(self, drive):
        self.selected_drive = drive
        
        if drive == self.sys_drive:
            self.target_os_path = None
            self.drive_status_lbl.config(text=f"Jelenleg a {drive} meghajtót módosítod! (ÉLŐRENDSZER)", foreground="#2e7d32")
        else:
            if not os.path.exists(os.path.join(drive, "Windows")):
                messagebox.showwarning("Figyelmeztetés", f"A(z) {drive} meghajtón nem található 'Windows' mappa!")
                return
            self.target_os_path = drive
            self.drive_status_lbl.config(text=f"Jelenleg a {drive} meghajtót módosítod! (OFFLINE MÓD)", foreground="#c62828")
        
        for d, btn in self.drive_buttons.items():
            if d == drive:
                btn.config(bg="#4CAF50", fg="white")
            else:
                btn.config(bg="#e0e0e0", fg="black")
        
        if self.current_menu == "driver":
            self.refresh_drivers()
        elif self.current_menu == "update":
            self.check_wu_status()

    def switch_menu(self, menu_name):
        self.current_menu = menu_name
        
        for name, btn in self.menu_buttons.items():
            if name == menu_name:
                btn.config(bg="#4CAF50", fg="white", relief=tk.SUNKEN)
            else:
                btn.config(bg="#f0f0f0", fg="black", relief=tk.RAISED)
        
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        if menu_name == "driver":
            self.create_driver_content()
        elif menu_name == "update":
            self.create_update_content()
        elif menu_name == "restore":
            self.create_restore_content()

    def create_driver_content(self):
        title = ttk.Label(self.content_frame, text="Telepített Harmadik Fél (Third-party) Driverek", font=("Segoe UI", 12, "bold"), foreground="#003366")
        title.pack(fill=tk.X, padx=5, pady=(5, 10))
        
        columns = ("published", "original", "provider", "class", "version")
        self.tree = ttk.Treeview(self.content_frame, columns=columns, show="headings", selectmode="extended", height=20)
        
        self.tree.heading("published", text="Közzétett Név (oem*.inf)")
        self.tree.heading("original", text="Eredeti Név")
        self.tree.heading("provider", text="Gyártó")
        self.tree.heading("class", text="Eszközosztály")
        self.tree.heading("version", text="Verzió/Dátum")
        
        self.tree.column("published", width=120)
        self.tree.column("original", width=150)
        self.tree.column("provider", width=200)
        self.tree.column("class", width=150)
        self.tree.column("version", width=200)
        
        scrollbar = ttk.Scrollbar(self.content_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        btn_frame = ttk.Frame(self.content_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=10)
        
        refresh_btn = ttk.Button(btn_frame, text="↻ Frissítés", command=self.refresh_drivers)
        refresh_btn.pack(side=tk.LEFT, padx=3)
        
        select_all_btn = ttk.Button(btn_frame, text="Összes Kijelölése", command=self.select_all_drivers)
        select_all_btn.pack(side=tk.LEFT, padx=3)
        
        self.list_all_var = tk.BooleanVar(value=False)
        self.list_all_chk = ttk.Checkbutton(btn_frame, text="Minden Driver Listázása (Inbox is!) (Veszélyes!)", variable=self.list_all_var, command=self.on_list_all_toggle)
        self.list_all_chk.pack(side=tk.LEFT, padx=15)
        
        delete_btn = ttk.Button(btn_frame, text="❌ Kijelölt Driver(ek) TÖRLÉSE", command=self.delete_selected_drivers, style="Danger.TButton")
        delete_btn.pack(side=tk.RIGHT, padx=3)
        
        self.refresh_drivers()
        self.tree.bind("<Return>", lambda e: self.delete_selected_drivers())
        self.tree.bind("<Delete>", lambda e: self.delete_selected_drivers())
        self.tree.bind("<Control-a>", lambda e: [self.tree.selection_add(item) for item in self.tree.get_children()])
        self.tree.bind("<F5>", lambda e: self.refresh_drivers())
        self.after(500, lambda: self.tree.focus_set())

    def create_update_content(self):
        title = ttk.Label(self.content_frame, text="Windows Update Driver Frissítések Beállításai", font=("Segoe UI", 12, "bold"), foreground="#003366")
        title.pack(fill=tk.X, pady=(0, 20))
        
        self.wu_status_lbl = ttk.Label(self.content_frame, text="Állapot: Ismeretlen", font=("Arial", 11, "bold"))
        self.wu_status_lbl.pack(fill=tk.X, pady=10)
        
        btn_frame = ttk.Frame(self.content_frame)
        btn_frame.pack(fill=tk.X, pady=20)
        
        disable_btn = ttk.Button(btn_frame, text="WU Driver Letöltés LETILTÁSA", command=self.disable_wu_drivers)
        disable_btn.pack(side=tk.LEFT, padx=5)
        
        enable_btn = ttk.Button(btn_frame, text="WU Driver Letöltés ENGEDÉLYEZÉSE", command=self.enable_wu_drivers)
        enable_btn.pack(side=tk.LEFT, padx=5)
        
        self.check_wu_status()

    def create_restore_content(self):
        title = ttk.Label(self.content_frame, text="Biztonsági Mentés és Helyreállítás", font=("Segoe UI", 12, "bold"), foreground="#003366")
        title.pack(fill=tk.X, pady=(0, 20))
        
        s1 = ttk.LabelFrame(self.content_frame, text="Biztonsági Mentés (Driver Export és Visszaállítási Pont)", padding=10)
        s1.pack(fill=tk.X, pady=10)
        ttk.Button(s1, text="Új Rendszer-visszaállítási Pont Készítése", command=self.create_restore_point).pack(side=tk.LEFT, padx=5)
        ttk.Button(s1, text="Összes Third-Party Driver Lementése (Exportálás)", command=self.backup_drivers).pack(side=tk.LEFT, padx=5)
        ttk.Button(s1, text="Lementett Driverek Visszaállítása", command=self.restore_drivers).pack(side=tk.LEFT, padx=5)
        
        s3 = ttk.LabelFrame(self.content_frame, text="Extrém Helyreállítás: Gyári Windows (Alap) Driverek Kinyerése", padding=10)
        s3.pack(fill=tk.X, pady=10)
        lbl = ttk.Label(s3, text="Ha minden gyári driver törlődött (Billentyűzet, Mouse, USB), a Windows ISO-ból (install.wim) visszahozhatod!")
        lbl.pack(side=tk.LEFT, padx=5)
        ttk.Button(s3, text="Alap Driverek Kinyerése (install.wim)", command=self.extract_wim_drivers).pack(side=tk.RIGHT, padx=5)

    def check_wu_status(self):
        if self.target_os_path and self.target_os_path != self.sys_drive:
            self.wu_status_lbl.config(text=f"Figyelem: A ({self.target_os_path}) célrendszer állapota offline nem kérdezhető le.", foreground="#B58900")
            return
        try:
            key_path = r"SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                val, _ = winreg.QueryValueEx(key, "ExcludeWUDriversInQualityUpdate")
                if val == 1:
                    self.wu_status_lbl.config(text="Állapot: KIKAPCSOLVA (Letiltva)", foreground="red")
                else:
                    self.wu_status_lbl.config(text="Állapot: BEKAPCSOLVA", foreground="green")
        except FileNotFoundError:
            self.wu_status_lbl.config(text="Állapot: BEKAPCSOLVA (Alap)", foreground="green")
        except Exception:
            self.wu_status_lbl.config(text="Állapot: Ismeretlen", foreground="gray")

    def disable_wu_drivers(self):
        try:
            if self.target_os_path and self.target_os_path != self.sys_drive:
                hive_path = os.path.join(self.target_os_path, "Windows", "System32", "config", "SOFTWARE")
                if not os.path.exists(hive_path):
                    messagebox.showerror("Hiba", f"SOFTWARE hive nem található: {hive_path}")
                    return
                res = subprocess.run(['reg', 'load', 'HKLM\\\\OfflineWU', hive_path], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if res.returncode != 0:
                    messagebox.showerror("Hiba", f"Reg load hiba: {res.stderr}")
                    return
                try:
                    p1 = r"HKLM\\\\OfflineWU\\\\Policies\\\\Microsoft\\\\Windows\\\\WindowsUpdate"
                    subprocess.run(['reg', 'add', p1, '/v', 'ExcludeWUDriversInQualityUpdate', '/t', 'REG_DWORD', '/d', '1', '/f'], creationflags=subprocess.CREATE_NO_WINDOW)
                    p2 = r"HKLM\\\\OfflineWU\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\DriverSearching"
                    subprocess.run(['reg', 'add', p2, '/v', 'SearchOrderConfig', '/t', 'REG_DWORD', '/d', '0', '/f'], creationflags=subprocess.CREATE_NO_WINDOW)
                    messagebox.showinfo("Siker", f"Windows Update driverek OFFLINE LETILTVA a {self.target_os_path} meghajtón!")
                finally:
                    subprocess.run(['reg', 'unload', 'HKLM\\\\OfflineWU'], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                p1 = r"SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate"
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, p1, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 1)
                p2 = r"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\DriverSearching"
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, p2, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "SearchOrderConfig", 0, winreg.REG_DWORD, 0)
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.run("net stop wuauserv & net start wuauserv", shell=True, startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW)
                messagebox.showinfo("Siker", "Élő Windows Update driver telepítés sikeresen LETILTVA!")
        except Exception as e:
            messagebox.showerror("Hiba", str(e))
        self.check_wu_status()

    def enable_wu_drivers(self):
        try:
            if self.target_os_path and self.target_os_path != self.sys_drive:
                hive_path = os.path.join(self.target_os_path, "Windows", "System32", "config", "SOFTWARE")
                if not os.path.exists(hive_path):
                    messagebox.showerror("Hiba", f"SOFTWARE hive nem található: {hive_path}")
                    return
                res = subprocess.run(['reg', 'load', 'HKLM\\\\OfflineWU', hive_path], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if res.returncode != 0:
                    messagebox.showerror("Hiba", f"Reg load hiba: {res.stderr}")
                    return
                try:
                    p1 = r"HKLM\\\\OfflineWU\\\\Policies\\\\Microsoft\\\\Windows\\\\WindowsUpdate"
                    subprocess.run(['reg', 'add', p1, '/v', 'ExcludeWUDriversInQualityUpdate', '/t', 'REG_DWORD', '/d', '0', '/f'], creationflags=subprocess.CREATE_NO_WINDOW)
                    p2 = r"HKLM\\\\OfflineWU\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\DriverSearching"
                    subprocess.run(['reg', 'add', p2, '/v', 'SearchOrderConfig', '/t', 'REG_DWORD', '/d', '1', '/f'], creationflags=subprocess.CREATE_NO_WINDOW)
                    messagebox.showinfo("Siker", f"Windows Update driverek OFFLINE ENGEDÉLYEZVE a {self.target_os_path} meghajtón!")
                finally:
                    subprocess.run(['reg', 'unload', 'HKLM\\\\OfflineWU'], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                p1 = r"SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate"
                try:
                    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, p1, 0, winreg.KEY_WRITE) as k:
                        winreg.SetValueEx(k, "ExcludeWUDriversInQualityUpdate", 0, winreg.REG_DWORD, 0)
                except: pass
                p2 = r"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\DriverSearching"
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, p2, 0, winreg.KEY_WRITE) as k:
                    winreg.SetValueEx(k, "SearchOrderConfig", 0, winreg.REG_DWORD, 1)
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.run("net stop wuauserv && net start wuauserv", shell=True, startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW)
                messagebox.showinfo("Siker", "Élő Windows Update driver telepítés sikeresen VISSZAÁLLÍTVA!")
        except Exception as e:
            messagebox.showerror("Hiba", str(e))
        self.check_wu_status()
'''

import re

# Match the old __init__, create_widgets, check_wu_status, disable_wu_drivers, enable_wu_drivers, change_target_os, reset_target_os
# and replace them entirely. 
# Look for a large block to replace cleanly.
# We will use string manipulation to find start/end indices.

idx_init = content.find('    def __init__(self):')
idx_create_restore = content.find('    def create_restore_point(self):')

if idx_init != -1 and idx_create_restore != -1:
    new_content = content[:idx_init] + new_ui + '\n' + content[idx_create_restore:]
    
    with open('driver_tool.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Módosítás kész.")
else:
    print("Nem találtam meg a szakaszokat.")
