param([string]$Python = "python")

$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "..")
try {
    & $Python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Installing runtime dependencies failed." }

    & $Python -m pip install "pyinstaller==6.16.0"
    if ($LASTEXITCODE -ne 0) { throw "Installing PyInstaller failed." }

    & $Python -m PyInstaller --noconfirm --clean --onedir --windowed `
        --name WritingAssistant --collect-data spellchecker app.py
    if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }
} finally {
    Pop-Location
}
