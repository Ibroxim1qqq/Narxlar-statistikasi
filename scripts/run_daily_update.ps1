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

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $false)][string[]]$ArgumentList = @()
    )

    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $Output = & $FilePath @ArgumentList 2>&1
        $ExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    $Lines = @($Output | ForEach-Object { $_.ToString() })
    return [PSCustomObject]@{
        ExitCode = [int]$ExitCode
        Lines = $Lines
    }
}

function Write-LogLines {
    param(
        [Parameter(Mandatory = $false)][string[]]$Lines = @()
    )

    foreach ($Line in $Lines) {
        Add-Content -Path $LogFile -Value $Line
        Write-Host $Line
    }
}

function Invoke-NativeLogged {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $false)][string[]]$ArgumentList = @()
    )

    $Result = Invoke-NativeCapture -FilePath $FilePath -ArgumentList $ArgumentList
    if ($Result.Lines.Count -gt 0) {
        Write-LogLines -Lines $Result.Lines
    }
    return $Result.ExitCode
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectRoot

Write-Output ("Started daily update at {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")) | Tee-Object -FilePath $LogFile
Write-Output "Checking Python dependencies..." | Tee-Object -FilePath $LogFile -Append
$DependencyCheck = "import importlib.util, sys; missing=[m for m in ('pandas','requests','bs4','lxml','plotly','streamlit','sqlalchemy','psycopg') if importlib.util.find_spec(m) is None]; print('Missing dependencies:', ', '.join(missing) if missing else 'none'); sys.exit(1 if missing else 0)"
$DependencyResult = Invoke-NativeCapture -FilePath $Python -ArgumentList @("-c", $DependencyCheck)
Write-LogLines -Lines $DependencyResult.Lines
if ($DependencyResult.ExitCode -ne 0) {
    Write-Output "Installing Python dependencies from requirements.txt..." | Tee-Object -FilePath $LogFile -Append
    $PipCode = Invoke-NativeLogged -FilePath $Python -ArgumentList @("-m", "pip", "install", "-r", "requirements.txt", "--no-input")
    if ($PipCode -ne 0) {
        $ExitCode = $PipCode
        Write-Output ("Finished daily update with exit code {0} at {1}" -f $ExitCode, (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")) | Tee-Object -FilePath $LogFile -Append
        exit $ExitCode
    }
}
$ExitCode = Invoke-NativeLogged -FilePath $Python -ArgumentList @("daily_update.py")
if ($ExitCode -eq 0) {
    $Git = Resolve-Git
    $TrackedDataFiles = @("data/housing_prices.sqlite", "data/processed/projects.csv", "data/processed/room_prices.csv", "data/processed/summary.json")
    $StatusResult = Invoke-NativeCapture -FilePath $Git -ArgumentList (@("status", "--porcelain", "--") + $TrackedDataFiles)
    $Changes = @($StatusResult.Lines | Where-Object { $_ })
    if ($StatusResult.ExitCode -eq 0 -and $Changes.Count -gt 0) {
        Write-Output "Committing updated database snapshot to GitHub..." | Tee-Object -FilePath $LogFile -Append
        $AddCode = Invoke-NativeLogged -FilePath $Git -ArgumentList (@("add", "--") + $TrackedDataFiles)
        if ($AddCode -ne 0) {
            $ExitCode = $AddCode
        } else {
            $CommitCode = Invoke-NativeLogged -FilePath $Git -ArgumentList @("commit", "-m", ("Daily housing price snapshot {0}" -f (Get-Date -Format "yyyy-MM-dd")))
            if ($CommitCode -eq 0) {
                $PushCode = Invoke-NativeLogged -FilePath $Git -ArgumentList @("push")
                $ExitCode = $PushCode
            } else {
                $ExitCode = $CommitCode
            }
        }
    } elseif ($StatusResult.ExitCode -ne 0) {
        $StatusResult.Lines | Tee-Object -FilePath $LogFile -Append
        $ExitCode = $StatusResult.ExitCode
    } else {
        Write-Output "No tracked data changes to commit." | Tee-Object -FilePath $LogFile -Append
        $PushResult = Invoke-NativeCapture -FilePath $Git -ArgumentList @("push")
        if ($PushResult.Lines.Count -gt 0) {
            $PushResult.Lines | Tee-Object -FilePath $LogFile -Append
        }
        $PushText = $PushResult.Lines -join "`n"
        if ($PushResult.ExitCode -ne 0 -and $PushText -notmatch "Everything up-to-date") {
            $ExitCode = $PushResult.ExitCode
        } else {
            $ExitCode = 0
        }
    }
}
Write-Output ("Finished daily update with exit code {0} at {1}" -f $ExitCode, (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")) | Tee-Object -FilePath $LogFile -Append

exit $ExitCode
