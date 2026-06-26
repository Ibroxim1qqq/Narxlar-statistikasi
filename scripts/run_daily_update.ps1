$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = if (Test-Path $BundledPython) { $BundledPython } else { "python" }
$LogDir = Join-Path $ProjectRoot "data\logs"
$LogFile = Join-Path $LogDir ("daily_update_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

function Resolve-Git {
    $githubDesktopGit = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "GitHubDesktop\app-*\resources\app\git\cmd\git.exe") -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($githubDesktopGit) {
        return $githubDesktopGit.FullName
    }
    return "git"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectRoot

Write-Output ("Started daily update at {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")) | Tee-Object -FilePath $LogFile
Write-Output "Checking Python dependencies..." | Tee-Object -FilePath $LogFile -Append
$DependencyCheck = "import importlib.util, sys; missing=[m for m in ('pandas','requests','bs4','lxml','plotly','streamlit','sqlalchemy','psycopg') if importlib.util.find_spec(m) is None]; print('Missing dependencies:', ', '.join(missing) if missing else 'none'); sys.exit(1 if missing else 0)"
& $Python -c $DependencyCheck 2>&1 | Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) {
    Write-Output "Installing Python dependencies from requirements.txt..." | Tee-Object -FilePath $LogFile -Append
    & $Python -m pip install -r "requirements.txt" --no-input 2>&1 | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        $ExitCode = $LASTEXITCODE
        Write-Output ("Finished daily update with exit code {0} at {1}" -f $ExitCode, (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")) | Tee-Object -FilePath $LogFile -Append
        exit $ExitCode
    }
}
& $Python "daily_update.py" 2>&1 | Tee-Object -FilePath $LogFile -Append
$ExitCode = $LASTEXITCODE
if ($ExitCode -eq 0) {
    $Git = Resolve-Git
    $Changes = & $Git status --porcelain data/housing_prices.sqlite data/processed/projects.csv data/processed/room_prices.csv data/processed/summary.json 2>&1
    $GitStatusCode = $LASTEXITCODE
    if ($GitStatusCode -eq 0 -and $Changes) {
        Write-Output "Committing updated database snapshot to GitHub..." | Tee-Object -FilePath $LogFile -Append
        $AddOutput = & $Git add data/housing_prices.sqlite data/processed/projects.csv data/processed/room_prices.csv data/processed/summary.json 2>&1
        $AddCode = $LASTEXITCODE
        $AddOutput | Tee-Object -FilePath $LogFile -Append
        if ($AddCode -ne 0) {
            $ExitCode = $AddCode
        } else {
            $CommitOutput = & $Git commit -m ("Daily housing price snapshot {0}" -f (Get-Date -Format "yyyy-MM-dd")) 2>&1
            $CommitCode = $LASTEXITCODE
            $CommitOutput | Tee-Object -FilePath $LogFile -Append
            if ($CommitCode -eq 0) {
                $PushOutput = & $Git push 2>&1
                $PushCode = $LASTEXITCODE
                $PushOutput | Tee-Object -FilePath $LogFile -Append
                $ExitCode = $PushCode
            } else {
                $ExitCode = $CommitCode
            }
        }
    } elseif ($GitStatusCode -ne 0) {
        $Changes | Tee-Object -FilePath $LogFile -Append
        $ExitCode = $GitStatusCode
    } else {
        Write-Output "No tracked data changes to commit." | Tee-Object -FilePath $LogFile -Append
        $PushOutput = & $Git push 2>&1
        $PushCode = $LASTEXITCODE
        $PushOutput | Tee-Object -FilePath $LogFile -Append
        if ($PushCode -ne 0 -and $PushOutput -notmatch "Everything up-to-date") {
            $ExitCode = $PushCode
        } else {
            $ExitCode = 0
        }
    }
}
Write-Output ("Finished daily update with exit code {0} at {1}" -f $ExitCode, (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")) | Tee-Object -FilePath $LogFile -Append

exit $ExitCode
