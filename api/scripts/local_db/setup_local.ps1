<#
  setup_local.ps1 - one-time local setup for the BRERC API + ETL on Windows.

  Run from anywhere (PowerShell):
      powershell -ExecutionPolicy Bypass -File api\scripts\local_db\setup_local.ps1
  Add -RunEtl to run the ETL once at the end.

  What it does (each step is skipped if already done):
    1. Checks Python is 3.10 or newer
    2. Creates api\.venv and installs requirements-dev.txt
    3. Creates api\.env (asks for your Postgres passwords; nothing is echoed)
    4. Puts the brerc_ui schema at db\b6_schema.sql (backs up the old one)
    5. Checks data\sensitive_species.csv exists (offers a placeholder if not)
    6. Tests the database: PostGIS, brerc_source views, brerc_ui tables
#>
param([switch]$RunEtl)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$ApiDir    = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$RepoDir   = (Resolve-Path (Join-Path $ApiDir "..")).Path
Set-Location $ApiDir

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "   OK  $text" -ForegroundColor Green }
function Warn($text) { Write-Host "   !!  $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "   XX  $text" -ForegroundColor Red; exit 1 }

# --- 1. Python ---------------------------------------------------------------
Step "1. Python"
$pyExe = $null; $pyPre = @(); $v = $null
foreach ($candidate in @(@("py", "-3"), @("python"))) {
    if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
    $pre = @($candidate | Select-Object -Skip 1)
    try { $out = & $candidate[0] @pre -c "import sys; print(sys.version.split()[0])" 2>$null } catch { $out = $null }
    if ($LASTEXITCODE -eq 0 -and $out) { $pyExe = $candidate[0]; $pyPre = $pre; $v = "$out".Trim(); break }
}
if (-not $pyExe) { Fail "Python not found. Install Python 3.11+ from python.org (tick 'Add python.exe to PATH')." }
$parts = $v.Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) { Fail "Python $v found; 3.10 or newer is required." }
Ok "Python $v ($pyExe $pyPre)"

# --- 2. Virtual environment + packages ---------------------------------------
Step "2. Virtual environment"
$venvPython = Join-Path $ApiDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $pyExe @pyPre -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create .venv" }
    Ok "Created api\.venv"
} else { Ok "api\.venv already exists" }

& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r requirements-dev.txt xlrd openpyxl
if ($LASTEXITCODE -ne 0) { Fail "pip install failed - see the messages above." }
Ok "Installed requirements-dev.txt (+ xlrd, openpyxl for the loader)"

# --- 3. .env -----------------------------------------------------------------
Step "3. api\.env"
$envFile = Join-Path $ApiDir ".env"
if (Test-Path $envFile) {
    Ok ".env already exists - left unchanged"
} else {
    function Read-Secret($prompt) {
        $s = Read-Host $prompt -AsSecureString
        $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
        try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
    }
    $dbName = Read-Host "   Database that holds brerc_source and brerc_ui [postgres]"
    if (-not $dbName) { $dbName = "postgres" }
    $pgPass  = [uri]::EscapeDataString((Read-Secret "   Password for the postgres user"))
    $apiPass = [uri]::EscapeDataString((Read-Secret "   Password for brerc_api_ro (set with ALTER ROLE brerc_api_ro PASSWORD '...')"))

    $base = "localhost:5432/$dbName"
    @(
        "# Local development settings - git-ignored, never commit.",
        "DATABASE_URL=postgresql://brerc_api_ro:$apiPass@$base",
        "SOURCE_DATABASE_URL=postgresql://postgres:$pgPass@$base",
        "DESTINATION_DATABASE_URL=postgresql://postgres:$pgPass@$base",
        "DATABASE_URL_ADMIN=postgresql://postgres:$pgPass@$base",
        "APP_ENV=dev",
        "DB_STATEMENT_TIMEOUT_MS=5000",
        "SPECIES_INFO_ENABLED=false"
    ) | Set-Content -Path $envFile -Encoding ASCII
    Ok "Wrote api\.env"
}

# --- 4. db\b6_schema.sql -----------------------------------------------------
Step "4. db\b6_schema.sql (the ETL re-runs this on every initial load)"
$dbDir   = Join-Path $RepoDir "db"
$schema  = Join-Path $dbDir "b6_schema.sql"
$ours    = Join-Path $ScriptDir "02_brerc_ui_schema.sql"
New-Item -ItemType Directory -Force -Path $dbDir | Out-Null
if ((Test-Path $schema) -and ((Get-FileHash $schema).Hash -eq (Get-FileHash $ours).Hash)) {
    Ok "Already the brerc_ui schema"
} else {
    if (Test-Path $schema) {
        $backup = "$schema.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        Copy-Item $schema $backup
        Warn "Backed up the original to $(Split-Path $backup -Leaf)"
    }
    Copy-Item $ours $schema -Force
    Ok "Copied 02_brerc_ui_schema.sql -> db\b6_schema.sql"
}

# --- 5. data\sensitive_species.csv -------------------------------------------
Step "5. data\sensitive_species.csv"
$dataDir   = Join-Path $RepoDir "data"
$sensitive = Join-Path $dataDir "sensitive_species.csv"
if (Test-Path $sensitive) {
    Ok "Found"
} else {
    Warn "Missing - the ETL refuses to run without it."
    $placeholder = Join-Path $ScriptDir "sensitive_species_from_dictionary.csv"
    $answer = Read-Host "   Use the 65 species flagged SENSITIVE=yes in the species dictionary as a TEMPORARY list? (y/n)"
    if ($answer -eq "y") {
        New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
        Copy-Item $placeholder $sensitive
        Warn "Copied a PLACEHOLDER list. Replace it with BRERC's real sensitive-species list before trusting any output."
    } else {
        Warn "Put BRERC's list at data\sensitive_species.csv (columns species_no, nbn_number) before running the ETL."
    }
}

# --- 6. Database checks ------------------------------------------------------
Step "6. Database"
$check = @'
import os, sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg
load_dotenv(Path(".env"))
checks = [
    ("PostGIS in public",  "SELECT extnamespace::regnamespace::text = 'public' FROM pg_extension WHERE extname = 'postgis'"),
    ("brerc_source rows",  "SELECT count(*) FROM brerc_source.vw_occurrences"),
    ("dictionary species", "SELECT count(*) FROM brerc_source.vw_species_dictionary"),
    ("brerc_ui tables",    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'brerc_ui'"),
]
bad = False
with psycopg.connect(os.environ["DESTINATION_DATABASE_URL"]) as conn, conn.cursor() as cur:
    for label, sql in checks:
        try:
            cur.execute(sql); row = cur.fetchone(); value = row[0] if row else None
        except Exception as e:
            conn.rollback(); value = f"ERROR {type(e).__name__}"
        ok = value not in (None, False, 0) and not str(value).startswith("ERROR")
        bad |= not ok
        print(f"   {'OK' if ok else 'XX'}  {label}: {value}")
try:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM public_species"); print("   OK  API role can read public_species")
except Exception as e:
    print(f"   !!  API role (DATABASE_URL) failed: {type(e).__name__} - check brerc_api_ro's password")
sys.exit(1 if bad else 0)
'@
$check | & $venvPython -
if ($LASTEXITCODE -ne 0) { Warn "Fix the XX items above (see 01_brerc_source.sql / 02_brerc_ui_schema.sql), then re-run this script." }

# --- Optional: run the ETL ---------------------------------------------------
if ($RunEtl) {
    Step "Running the ETL"
    & $venvPython -c "from etl.job import nightly_job; nightly_job()"
}

Step "Done. Day-to-day, from the api folder:"
Write-Host "   .venv\Scripts\Activate.ps1"
Write-Host "   python -c `"from etl.job import nightly_job; nightly_job()`"   # ETL"
Write-Host "   uvicorn app.main:app --reload                                   # API -> http://127.0.0.1:8000/docs"
Write-Host "   python -m pytest -v                                             # tests"
