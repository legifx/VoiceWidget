# VoiceWidget

Ein superschönes **Liquid Glass** Widget für Windows – drück aufnehmen, sprich, und der Text landet direkt in deiner Hermes SSH Session.

![Liquid Glass Design](https://img.shields.io/badge/style-Liquid%20Glass-ff7eb3)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

---

## 🎬 So siehts aus

```
┌─────────────────────────────────────────┐
│  🎤 VoiceWidget                         │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │                                 │    │
│  │         ⏺ AUFNEHMEN             │    │
│  │                                 │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─ Ziel: ───────────────────────────┐  │
│  │  ▼ NAME: Hermes (192.168.1.182)  │  │
│  │                                   │  │
│  │  ○ nimbus (Nimbus Mode)           │  │
│  │  ● hermes (aktive Session)       │  │
│  │  ○ debug                          │  │
│  └───────────────────────────────────┘  │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │  Hallo Welt, dies ist ein Test  │    │
│  │  der Spracherkennung...         │    │
│  │                             📋  │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

## ✨ Features

- **🎤 Ein-Klick Aufnahme** – Drück den Button, sprich, fertig
- **🧊 Liquid Glass Design** – Apple-style, semi-transparent, blur, rounded corners
- **🤖 Tmux Integration** – Wählt eine laufende Hermes SSH Session aus und fügt Text direkt ein
- **📋 Zwischenablage** – Text mit einem Klick kopieren
- **🚀 Auto-Start** – Widget startet mit Windows
- **🌐 SSH via Tailscale** – Verbindet sich zu deinem Server

## 📦 Installation

### Voraussetzungen

- **Windows 10/11**
- **Python 3.10+** installiert ([python.org](https://python.org))
- **Tailscale** verbunden (dein PC muss im selben Tailnet wie der Server sein)
- **SSH-Zugriff** auf deinen Server (`server@192.168.1.182`)

### 1. Setup-Script ausführen

**PowerShell ALS ADMIN öffnen** und folgendes ausführen:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
iex ((New-Object System.Net.WebClient).DownloadString('https://raw.githubusercontent.com/legifx/VoiceWidget/main/setup.ps1'))
```

Oder **manuell**:

```powershell
# 1. Repository klonen
git clone https://github.com/legifx/VoiceWidget.git
cd VoiceWidget

# 2. Python Venv erstellen
python -m venv venv
.\venv\Scripts\activate

# 3. Dependencies installieren
pip install -r requirements.txt

# 4. SSH-Key erstellen (wenn nicht vorhanden)
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\id_ed25519" -N ""

# 5. ÖFFENTLICHEN KEY an Julian geben
cat "$env:USERPROFILE\.ssh\id_ed25519.pub"

# 6. Widget starten
python widget.py
```

### 2. SSH-Key auf dem Server eintragen

Nach Schritt 5 bekommst du einen Key angezeigt. Den gibst du mir (Julian),
damit ich ihn auf dem Server eintrage. Danach verbindet sich das Widget
automatisch.

### 3. Auto-Start einrichten

Einmalig im Widget auf **Settings → Auto-Start** klicken.
Oder manuell: `WIN+R` → `shell:startup` → Verknüpfung zu `widget.py` reinlegen.

## 🔧 Konfiguration

Öffne die `config.ini` (wird beim ersten Start automatisch erstellt):

```ini
[Server]
host = 192.168.1.182
user = server
port = 22
whisper_port = 8766

[Widget]
theme = liquid_glass
opacity = 0.92
autostart = true
```

## 🏗️ Projektstruktur

```
VoiceWidget/
├── widget.py              # Haupt-Widget (Python + CustomTkinter)
├── server.py              # Server-Helper (SSH, Tmux, Transkription)
├── requirements.txt       # Abhängigkeiten
├── setup.ps1              # Windows Setup-Script
├── config.ini             # Konfiguration (automatisch erstellt)
└── README.md              # Diese Datei
```

## ⚙️ How it works

1. Du drückst **Aufnehmen**
2. Widget nimmt Audio vom Mikrofon auf
3. Bei **Stop** wirds per SSH an den Server geschickt
4. Server transkribiert mit **faster-whisper-large-v3-turbo**
5. Text erscheint im Widget
6. Du wählst eine **tmux Session** aus
7. Text wird per SSH in die Session eingefügt
8. Fertig! 🎉

## 🛠️ Entwicklung

```bash
# Dev-Mode mit Live-Reload
python widget.py --debug

# Requirements aktualisieren
pip freeze > requirements.txt
```

## 📄 Lizenz

MIT – mach damit was du willst.
