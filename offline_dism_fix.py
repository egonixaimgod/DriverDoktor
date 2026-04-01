import re
import subprocess
import logging

with open('driver_tool.py', 'r', encoding='utf-8') as f:
    text = f.read()

def replace_offline():
    old = '''    def get_offline_drivers(self, all_drivers=False):
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # Using PowerShell Get-WindowsDriver for robust parsing
            all_flag = "-All" if all_drivers else ""
            cmd = ['powershell', '-NoProfile', '-Command', 
                   f'Get-WindowsDriver -Path "{self.target_os_path}" {all_flag} | Select-Object ProviderName, ClassName, Version, Driver, OriginalFileName | ConvertTo-Json -Depth 2 -WarningAction SilentlyContinue']
            res = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
            
            import json
            out = res.stdout.strip()
            if not out: return []
            
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
            logging.error(f"Hiba az Offline driver lekérdezésben (PowerShell Get-WindowsDriver -Path): {e}")
            return []'''

    new = '''    def get_offline_drivers(self, all_drivers=False):
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
            return []'''

    res_str = text.replace(old, new)
    with open('driver_tool.py', 'w', encoding='utf-8') as fw:
        fw.write(res_str)

replace_offline()
print("Success")