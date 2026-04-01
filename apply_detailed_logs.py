with open('driver_tool.py', 'r', encoding='utf-8') as f:
    content = f.read()

delete_start_idx = content.find("    def delete_selected_drivers(self):")
delete_end_idx = content.find("def _run_hardware_scan_window(self):", delete_start_idx)

if delete_start_idx != -1 and delete_end_idx != -1:
    delete_old = content[delete_start_idx:delete_end_idx]
    
    delete_new = """    def delete_selected_drivers(self):
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

        lbl = ttk.Label(prog_win, text=f"{len(selected)} driver vegleges eltavolitasa folyamatban...\\nKerlek varj!", justify=tk.CENTER)
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
            log_text.insert(tk.END, msg + "\\n")
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

                    if res.returncode == 0 or "Deleted" in res.stdout or "törölve" in res.stdout or "t\\xf6r\\xf6lve" in res.stdout or "successfully" in res.stdout.lower():
                        success_count += 1
                        self.after(0, lambda m=f"   [SIKER] {published_name} letorolve.": append_log(m))
                    else:
                        if hasattr(self, 'list_all_var') and self.list_all_var.get() and not is_oem:
                            self.after(0, lambda m=f"   [KISERLET] Inbox {published_name} eroszakos torlese FileRepository-bol...": append_log(m))
                            import glob
                            if is_offline:
                                rep_path = os.path.join(self.target_os_path, "Windows", "System32", "DriverStore", "FileRepository")
                            else:
                                rep_path = r"C:\\Windows\\System32\\DriverStore\\FileRepository"
                            
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
                messagebox.showinfo("Eredmeny", f"Sikeresen torolve: {success_count}\\nNem sikerult: {fail_count}\\n\\nMost a program ujraellenorzi a hardvereket.")
                self._run_hardware_scan_window()

            self.after(0, finish_delete)

        threading.Thread(target=worker, daemon=True).start()

    """
    
    content = content[:delete_start_idx] + delete_new + content[delete_end_idx:]


restore_start_idx = content.find("    def _start_restore_thread(self, online, source_dir, target_dir):")
restore_end_idx = content.find("    def auto_wipe_selected(self, target_dir):", restore_start_idx)

if restore_start_idx != -1 and restore_end_idx != -1:
    restore_new = """    def _start_restore_thread(self, online, source_dir, target_dir):
        prog_win = tk.Toplevel(self)
        title_txt = "Elo rendszer frissitese..." if online else f"Offline WinPE Integralasa: {target_dir}"
        prog_win.title(title_txt)
        prog_win.geometry("700x400")
        prog_win.transient(self)
        prog_win.grab_set()

        lbl_txt = "Illesztoprogramok ratelepitese a jelenlegi gepre...\\nKerlek varj!" if online else f"Illesztoprogramok befuzese a(z) {target_dir} meghajtora...\\nEz eltarthat egy darabig!"
        lbl = ttk.Label(prog_win, text=lbl_txt, justify=tk.CENTER)
        lbl.pack(pady=5)

        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=600, mode='determinate')
        progress.pack(pady=5)
        
        status_lbl = ttk.Label(prog_win, text="Inicializalas es .inf fajlok keressese...", font=("Arial", 8))
        status_lbl.pack(pady=5)

        text_frame = tk.Frame(prog_win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10))
        log_text = tk.Text(text_frame, height=12, state=tk.DISABLED, bg="#F3F3F3", font=("Consolas", 8))
        log_scroll = ttk.Scrollbar(text_frame, command=log_text.yview)
        log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def append_log(msg):
            logging.info(msg)
            log_text.config(state=tk.NORMAL)
            log_text.insert(tk.END, msg + "\\n")
            log_text.see(tk.END)
            log_text.config(state=tk.DISABLED)

        def worker():
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                norm_source = os.path.normpath(source_dir).replace('/', '\\\\')
                norm_target = os.path.normpath(target_dir).replace('/', '\\\\')

                self.after(0, lambda: append_log(f"--- Kereses elinditva: {norm_source} ---"))
                inf_files = []
                for root, _, files in os.walk(norm_source):
                    for f in files:
                        if f.lower().endswith(".inf"):
                            inf_files.append(os.path.join(root, f))
                
                total = len(inf_files)
                if total == 0:
                    self.after(0, lambda: messagebox.showwarning("Nincs driver", f"Nem talaltam .inf kiterjesztesu driver fajlokat a mappaban:\\n{norm_source}"))
                    self.after(0, prog_win.destroy)
                    return

                self.after(0, lambda: progress.config(maximum=total))
                self.after(0, lambda: append_log(f"Osszesen {total} db .inf fajt talaltam. FELDOLGOZAS EGYESEVEL INDUL!"))
                
                success_count = 0
                fail_count = 0

                for i, inf_path in enumerate(inf_files):
                    self.after(0, lambda i=i, s=inf_path: status_lbl.config(text=f"Telepites ({i+1}/{total}): {os.path.basename(s)[:50]}..."))
                    self.after(0, lambda i=i: progress.configure(value=i))

                    if online:
                        cmd = ['pnputil', '/add-driver', inf_path, '/install']
                    else:
                        cmd = ['dism', f'/Image:{norm_target}', '/Add-Driver', f'/Driver:{inf_path}', '/ForceUnsigned']
                    
                    try:
                        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, 
                                           startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW, errors='replace')
                        
                        out = res.stdout.strip()
                        if res.returncode == 0 or "successfully" in out.lower() or "sikeres" in out.lower() or "successful" in out.lower() or "completed" in out.lower():
                            success_count += 1
                            self.after(0, lambda m=f"   [SIKER] ({i+1}/{total}) {os.path.basename(inf_path)} beillesztve.": append_log(m))
                        else:
                            fail_count += 1
                            self.after(0, lambda m=f"   [HIBA] ({i+1}/{total}) {os.path.basename(inf_path)}. Kod: {res.returncode}": append_log(m))
                            out_clean = out.replace(chr(10), ' ')[:250]
                            self.after(0, lambda m=f"   [LOG] {out_clean}": append_log(m))
                    except Exception as e:
                        fail_count += 1
                        self.after(0, lambda m=f"   [KIVETEL] ({i+1}/{total}) {os.path.basename(inf_path)} telepitese kozben: {e}": append_log(m))
                        
                self.after(0, lambda: progress.configure(value=total))
                self.after(0, lambda: append_log(f"--- FOLYAMAT VEGE. Sikeres: {success_count}, Hibas: {fail_count} ---"))

                if online:
                    self.after(0, lambda: status_lbl.config(text="Hardvervaltozasok keresese az Eszkozkezeloben..."))
                    import time
                    time.sleep(1.5)
                    subprocess.run(['pnputil', '/scan-devices'], startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
                    time.sleep(3.5)

                self.after(0, lambda: messagebox.showinfo("Befejezve", f"Sikeres: {success_count}\\nHibas: {fail_count}\\n\\nA reszletes logot a gep lementette a driver_tool_debug.log fajlba."))
                self.after(0, prog_win.destroy)

            except Exception as e:
                self.after(0, lambda e=e: messagebox.showerror("Varatlan hiba", str(e)))

        threading.Thread(target=worker, daemon=True).start()

"""
    content = content[:restore_start_idx] + restore_new + content[restore_end_idx:]

with open('driver_tool.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("String replace SUCCESS")
