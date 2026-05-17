# VoiceWidget — Windows Setup Script
# ====================================
# PowerShell ALS ADMIN ausführen:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\setup.ps1
#
# Oder per Download:
#   iex ((New-Object System.Net.WebClient).DownloadString('https://raw.githubusercontent.com/legifx/VoiceWidget/main/setup.ps1'))

$ErrorActionPreference = "Stop"
$WidgetDir = "$env:USERPROFILE\VoiceWidget"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗"
Write-Host "║     🎤  VoiceWidget — Windows Setup          ║"
Write-Host "╚══════════════════════════════════════════════╝"
Write-Host ""

# ── 1. Python check ──
Write-Host "📦 1. Python prüfen..."
try {
    $py = (Get-Command python -ErrorAction Stop).Source
    $ver = & python --version 2>&1
    Write-Host "   ✅ $ver — $py"
} catch {
    Write-Host "   ❌ Python nicht gefunden!"
    Write-Host "   Lade es runter von: https://www.python.org/downloads/"
    Write-Host "   WICHTIG: 'Add Python to PATH' HAKEN SETZEN!"
    pause
    exit 1
}

# ── 2. Git check ──
Write-Host "📦 2. Repository klonen..."
if (Test-Path "$WidgetDir") {
    Write-Host "   📁 Verzeichnis existiert bereits — update..."
    Push-Location "$WidgetDir"
    & git pull 2>$null
    Pop-Location
} else {
    try {
        & git clone https://github.com/legifx/VoiceWidget.git "$WidgetDir" 2>$null
        if (-not $?) { throw "git clone failed" }
    } catch {
        Write-Host "   ⚠️  Git nicht gefunden — lade als ZIP..."
        # Fallback: Download ZIP
        $zipUrl = "https://github.com/legifx/VoiceWidget/archive/refs/heads/main.zip"
        $zipPath = "$env:TEMP\VoiceWidget.zip"
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
        Expand-Archive -Path $zipPath -DestinationPath "$env:TEMP\VoiceWidget-temp" -Force
        Move-Item "$env:TEMP\VoiceWidget-temp\VoiceWidget-main\*" "$WidgetDir" -Force
        Remove-Item "$env:TEMP\VoiceWidget-temp" -Recurse -Force
        Remove-Item $zipPath -Force
    }
}
Write-Host "   ✅ $WidgetDir"

# ── 3. Venv ──
Write-Host "📦 3. Python Venv einrichten..."
Push-Location "$WidgetDir"
if (-not (Test-Path "venv")) {
    & python -m venv venv
    Write-Host "   ✅ Venv erstellt"
} else {
    Write-Host "   ✅ Venv existiert bereits"
}

# ── 4. Dependencies ──
Write-Host "📦 4. Abhängigkeiten installieren..."
& "$WidgetDir\venv\Scripts\pip" install -r "$WidgetDir\requirements.txt" 2>&1 | Out-Null
Write-Host "   ✅ Dependencies installiert (customtkinter, sounddevice, ...)"

# ── 5. SSH-Key prüfen ──
Write-Host "🔑 5. SSH-Key prüfen..."
$sshKey = "$env:USERPROFILE\.ssh\id_ed25519"
if (-not (Test-Path "$sshKey")) {
    Write-Host "   🔑 Erstelle neuen SSH-Key..."
    mkdir "$env:USERPROFILE\.ssh" -Force | Out-Null
    & ssh-keygen -t ed25519 -f "$sshKey" -N "" -q
    Write-Host ""
    Write-Host "   ⚠️  DIESEN KEY MUSST DU JULIAN GEBEN:"
    Write-Host ""
    $pubKey = Get-Content "${sshKey}.pub"
    Write-Host "   $pubKey"
    Write-Host ""
    Write-Host "   Kopier den obigen Text und schick ihn Julian."
    Write-Host "   Erst wenn er ihn eingetragen hat, funktioniert das Widget!"
    Write-Host ""
} else {
    Write-Host "   ✅ SSH-Key existiert"
}

# ── 6. Desktop Verknüpfung ──
Write-Host "📌 6. Desktop-Verknüpfung erstellen..."
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = "$desktop\VoiceWidget.lnk"

try {
    $WScriptShell = New-Object -ComObject WScript.Shell
    $shortcut = $WScriptShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "$WidgetDir\venv\Scripts\pythonw.exe"
    $shortcut.Arguments = "`"$WidgetDir\widget.py`""
    $shortcut.WorkingDirectory = "$WidgetDir"
    $shortcut.Description = "VoiceWidget — Sprachaufnahme → Text"
    $shortcut.Save()
    Write-Host "   ✅ Desktop-Verknüpfung: $shortcutPath"
} catch {
    Write-Host "   ⚠️  Konnte keine Verknüpfung erstellen (nicht Admin?)"
}

Pop-Location

# ── Fertig ──
Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗"
Write-Host "║     ✅  SETUP ABGESCHLOSSEN!                 ║"
Write-Host "║                                              ║"
Write-Host "║  🖱️  Starte das Widget per Doppelklick auf:  ║"
Write-Host "║     $desktop\VoiceWidget.lnk                 ║"
Write-Host "║                                              ║"
Write-Host "║  Oder im Terminal:                           ║"
Write-Host "║     cd $WidgetDir                            ║"
Write-Host "║     .\venv\Scripts\python widget.py          ║"
Write-Host "║                                              ║"
Write-Host "║  ⚠️  SSH-Key NICHT VERGESSEN!                 ║"
Write-Host "║     Wenn ein Key erstellt wurde,             ║"
Write-Host "║     schick den öffentlichen Key an Julian!   ║"
Write-Host "╚══════════════════════════════════════════════╝"
Write-Host ""

pause
