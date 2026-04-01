import re

with open('driver_tool.py', 'r', encoding='utf-8') as f:
    text = f.read()

new_widgets = '''    def create_widgets(self):
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

        refresh_btn = ttk.Button(btn_frame, text="Lista Frissítése (F5)", command=self.refresh_drivers)
        refresh_btn.pack(side=tk.LEFT, padx=5)

        select_all_btn = ttk.Button(btn_frame, text="Összes Kijelölése", command=self.select_all_drivers)
        select_all_btn.pack(side=tk.LEFT, padx=5)

        
        self.list_all_chk = ttk.Checkbutton(btn_frame, text="Minden Driver Listázása (Veszélyes!)", variable=self.list_all_var, command=self.on_list_all_toggle)
        self.list_all_chk.pack(side=tk.LEFT, padx=10)

        delete_btn = ttk.Button(btn_frame, text="Kiválasztott Driver(ek) TÖRLÉSE (Del)", command=self.delete_selected_drivers, style="Danger.TButton")
        delete_btn.pack(side=tk.RIGHT, padx=5)


        # -----------------------------
        # BACKUP & WIM VIEW CONTENT
        # -----------------------------
        backup_frame = ttk.LabelFrame(self.backup_view, text="Biztonsági Mentés (Driver Export és Visszaállítás)", padding=10)
        backup_frame.pack(fill=tk.X, padx=10, pady=10)

        rp_btn = ttk.Button(backup_frame, text="Új Rendszer-visszaállítási Pont Készítése", command=self.create_restore_point)
        rp_btn.pack(side=tk.LEFT, padx=5, pady=5)

        export_btn = ttk.Button(backup_frame, text="Összes Third-Party Driver Lementése (Exportálás)", command=self.backup_drivers)
        export_btn.pack(side=tk.LEFT, padx=5, pady=5)

        restore_btn = ttk.Button(backup_frame, text="Lementett Driverek Visszaállítása (Automatikus)", command=self.restore_drivers)
        restore_btn.pack(side=tk.LEFT, padx=5, pady=5)

        wim_frame = ttk.LabelFrame(self.backup_view, text="Extrém Helyreállítás: Gyári Windows (Alap) Driverek Kinyerése", padding=10)
        wim_frame.pack(fill=tk.X, padx=10, pady=10)

        wim_lbl = ttk.Label(wim_frame, text="Ha minden gyári driver törlődött (Billentyűzet, Touchpad, Standard USB), a Windows ISO-ból (install.wim) visszahozhatod!", font=("Segoe UI", 9))
        wim_lbl.pack(pady=(0, 10))

        wim_btn = ttk.Button(wim_frame, text="Alap Driverek Kinyerése (install.wim kiválasztása)", command=self.extract_wim_drivers)
        wim_btn.pack(pady=5)


        # -----------------------------
        # WINDOWS UPDATE VIEW CONTENT
        # -----------------------------
        wu_frame = ttk.LabelFrame(self.wu_view, text="Windows Update Driver Frissítések Beállításai", padding=10)
        wu_frame.pack(fill=tk.X, padx=10, pady=5)

        self.wu_status_lbl = ttk.Label(wu_frame, text="Állapot: Ismeretlen", font=("Segoe UI", 10, "bold"))
        self.wu_status_lbl.pack(side=tk.LEFT, padx=10, pady=5)

        disable_wu_btn = ttk.Button(wu_frame, text="WU Driver Letöltés LETILTÁSA", command=self.disable_wu_drivers)
        disable_wu_btn.pack(side=tk.LEFT, padx=5, pady=5)

        enable_wu_btn = ttk.Button(wu_frame, text="WU Driver Letöltés ENGEDÉLYEZÉSE", command=self.enable_wu_drivers)
        enable_wu_btn.pack(side=tk.LEFT, padx=5, pady=5)


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
'''

target = re.sub(r'    def create_widgets\(self\):.*?    def change_target_os\(self\):', new_widgets + '\n    def change_target_os(self):', text, flags=re.DOTALL)

with open('driver_tool.py', 'w', encoding='utf-8') as f:
    f.write(target)
