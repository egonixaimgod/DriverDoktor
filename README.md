# ♻️ DriverDoktor

**Windows Driver Management Utility** — Professzionális szerviz eszköz driver törléshez, telepítéshez, mentéshez és visszaállításhoz.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue.svg)](https://www.microsoft.com/windows)
[![Language: Python](https://img.shields.io/badge/Python-3.8+-green.svg)](https://www.python.org/)

---

## 📋 Tartalomjegyzék

- [Funkciók](#-funkciók)
- [Telepítés](#-telepítés)
- [Használat](#-használat)
- [Rendszerkövetelmények](#-rendszerkövetelmények)
- [Gyakori problémák](#-gyakori-problémák)
- [Fejlesztőknek](#-fejlesztőknek)
- [Licenc](#-licenc)

---

## ✨ Funkciók

### 🎯 1 Kattintásos Driver Fix (Autofix)
A legerőteljesebb funkció — egyetlen gombnyomással:
1. Letiltja a Windows Update automatikus driver telepítését
2. Törli az összes third-party drivert
3. Újraszkenneli a hardvereket
4. Letölti és telepíti a hivatalos drivereket a Windows Update szerverekről
5. Automatikusan újraindítja a számítógépet

**Ideális használati esetek:**
- Hibás driver telepítés után
- Kék halál (BSOD) driver problémák esetén
- Rendszer tisztítás előtt/után
- OEM bloatware driverek eltávolítására

### 📋 Driver Lista és Törlés
- **Third-party driverek** megjelenítése (OEM driverek)
- **Összes driver** megjelenítése (Windows inbox + OEM)
- Több driver egyidejű törlése
- Erőltetett törlés "ghost" driverekhez
- Offline rendszer támogatás (WinPE, másik Windows partíció)

### 💾 Driver Mentés és Visszaállítás
- **Third-party export** — DISM alapú gyors mentés
- **Teljes mentés** — OEM + Windows inbox driverek
- **WIM kinyerés** — Gyári driverek kimentése install.wim fájlból
- **Élő visszaállítás** — Futó Windowsra
- **Offline visszaállítás** — Halott/bootolhatatlan Windowsra

### ⚙️ Windows Update Kezelés
- WU driver frissítések **letiltása/engedélyezése**
- WU szolgáltatások **újraindítása**
- WU cache **teljes reset**

### 🖥️ Hardver Szkennelés
- PnP eszközök felderítése
- Elérhető driver frissítések keresése (WU API vagy MS Katalógus)
- Kategorizált eszközlista (GPU, Audio, Hálózat, stb.)

---

## 📥 Telepítés

### Futtatható verzió (ajánlott)
1. Töltsd le a legújabb `.exe` fájlt a [Releases](https://github.com/egonixaimgod/DriverDoktor/releases) oldalról
2. Futtasd rendszergazdaként
3. Nincs szükség telepítésre!

### Forráskódból futtatás
```bash
# Klónozás
git clone https://github.com/egonixaimgod/DriverDoktor.git
cd DriverDoktor

# Függőségek telepítése
pip install pywebview

# Futtatás
python driver_tool.py
```

---

## 🚀 Használat

### Alapvető műveletek

| Művelet | Leírás |
|---------|--------|
| **Driver Lista** | Kattints a "Third-party" vagy "Összes" gombra a driverek listázásához |
| **Törlés** | Jelöld ki a drivereket, majd kattints a "Törlés" gombra |
| **1 Kattintásos Fix** | Használd az "Autofix" gombot a teljes driver újratelepítéshez |
| **Mentés** | "Driver Mentés" menüből válaszd a megfelelő opciót |
| **Visszaállítás** | "Driver Visszaállítás" menüből válaszd az élő vagy offline módot |

### Offline mód
A program képes **másik Windows partíción** dolgozni:
1. Kattints a "Cél OS váltás" gombra
2. Válaszd ki a halott Windows partíciót (ahol van `Windows` mappa)
3. Mostantól minden művelet arra a rendszerre vonatkozik

### WIM kinyerés
Gyári driverek kimentése telepítő médiáról:
1. Csatold fel a Windows ISO-t vagy USB-t
2. "WIM Kinyerés" → válaszd az `install.wim` fájlt
3. Válassz célmappát
4. A program kimásolja a gyári drivereket

---

## 💻 Rendszerkövetelmények

| Követelmény | Minimum |
|-------------|---------|
| **OS** | Windows 10 / 11 (x64) |
| **RAM** | 2 GB |
| **Lemezterület** | 50 MB + mentések helye |
| **Jogosultság** | Rendszergazda |
| **Futtatókörnyezet** | WebView2 Runtime (Win10/11-ben alapból benne van) |

---

## ❓ Gyakori problémák

### Windows Defender blokkolja
A program PyInstaller-rel készült, ami néha false positive-ot okoz:
1. Győződj meg róla, hogy a hivatalos Releases oldalról töltötted le
2. Adj kivételt a Windows Defenderben
3. Vagy futtasd forráskódból

### Fehér képernyő Autofix közben
Ha a videókártya driver törlődik, a képernyő elfeketedhet majd fehér ablak marad:
- Ez normális jelenség — a program a háttérben folytatódik
- Várj amíg a gép újraindul
- Build 53+ automatikusan megpróbálja helyreállítani az ablakot

### "Nem sikerült törölni" hiba
Néhány driver használatban van:
- Használd az "Erőltetett törlés" (Összes driver) módot
- Vagy használd az Autofix-et

---

## 👨‍💻 Fejlesztőknek

### Build készítése
```bash
# PyInstaller build verzió infóval
pyinstaller --noconfirm --onefile --windowed --uac-admin ^
  --add-data "ui.html;." ^
  --icon "icon_driverdoktor.ico" ^
  --version-file "version_info.txt" ^
  --name "DriverDoktor" ^
  driver_tool.py
```

### Projekt struktúra
```
├── driver_tool.py          # Fő Python backend
├── ui.html                 # WebView2 UI frontend
├── icon_driverdoktor.ico   # Alkalmazás ikon
├── version_info.txt        # Windows verzió metaadatok
└── dist/                   # Build kimenet
```

### Technológiák
- **Backend:** Python 3.8+
- **Frontend:** HTML/CSS/JS (WebView2)
- **GUI Framework:** pywebview
- **Build:** PyInstaller

---

## 📄 Licenc

MIT License — szabadon használható, módosítható és terjeszthető.

---

## 🙏 Készítette

**EgonixAI** — 2024-2026

Ha hasznos volt, dobj egy ⭐-ot a GitHub-on!
