$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $ProjectRoot ".env"

function Read-EnvFile {
    param([string]$Path)
    $Values = @{}
    if (-not (Test-Path $Path)) {
        return $Values
    }
    Get-Content $Path | ForEach-Object {
        $Line = $_.Trim()
        if (-not $Line -or $Line.StartsWith("#") -or -not $Line.Contains("=")) {
            return
        }
        $Key, $Value = $Line.Split("=", 2)
        $Values[$Key.Trim()] = $Value.Trim().Trim('"').Trim("'")
    }
    return $Values
}

function Resolve-Psql {
    $Command = Get-Command psql -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }
    $Candidates = @(
        "C:\Program Files\PostgreSQL\18\bin\psql.exe",
        "C:\Program Files\PostgreSQL\17\bin\psql.exe",
        "C:\Program Files\PostgreSQL\16\bin\psql.exe",
        "C:\Program Files\PostgreSQL\15\bin\psql.exe"
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path $Candidate) {
            return $Candidate
        }
    }
    throw "psql.exe topilmadi. Avval PostgreSQL o'rnating."
}

function Sql-Quote {
    param([string]$Value)
    return $Value.Replace("'", "''")
}

$EnvValues = Read-EnvFile $EnvPath
$AdminUser = $EnvValues["POSTGRES_ADMIN_USER"]
$AdminPassword = $EnvValues["POSTGRES_ADMIN_PASSWORD"]
$AppUser = $EnvValues["POSTGRES_APP_USER"]
$AppPassword = $EnvValues["POSTGRES_APP_PASSWORD"]
$Database = $EnvValues["POSTGRES_DB"]

if (-not $AdminUser) { $AdminUser = "postgres" }
if (-not $AdminPassword) { throw "POSTGRES_ADMIN_PASSWORD .env ichida topilmadi." }
if (-not $AppUser) { $AppUser = "narxlar_app" }
if (-not $AppPassword) { throw "POSTGRES_APP_PASSWORD .env ichida topilmadi." }
if (-not $Database) { $Database = "narxlar_statistikasi" }

$Psql = Resolve-Psql
$env:PGPASSWORD = $AdminPassword
$AppPasswordSql = Sql-Quote $AppPassword

$BootstrapSql = @"
DO `$`$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$AppUser') THEN
        CREATE ROLE $AppUser LOGIN PASSWORD '$AppPasswordSql';
    ELSE
        ALTER ROLE $AppUser WITH LOGIN PASSWORD '$AppPasswordSql';
    END IF;
END
`$`$;

SELECT 'CREATE DATABASE $Database OWNER $AppUser'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$Database')\gexec

ALTER DATABASE $Database OWNER TO $AppUser;
GRANT ALL PRIVILEGES ON DATABASE $Database TO $AppUser;
"@

$SchemaSql = @"
ALTER SCHEMA public OWNER TO $AppUser;
GRANT USAGE, CREATE ON SCHEMA public TO $AppUser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $AppUser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO $AppUser;
"@

$BootstrapFile = Join-Path $env:TEMP "narxlar_pg_bootstrap.sql"
$SchemaFile = Join-Path $env:TEMP "narxlar_pg_schema.sql"
Set-Content -Path $BootstrapFile -Value $BootstrapSql -Encoding UTF8
Set-Content -Path $SchemaFile -Value $SchemaSql -Encoding UTF8

& $Psql -h localhost -p 5432 -U $AdminUser -d postgres -v ON_ERROR_STOP=1 -f $BootstrapFile
& $Psql -h localhost -p 5432 -U $AdminUser -d $Database -v ON_ERROR_STOP=1 -f $SchemaFile

Write-Output "PostgreSQL database tayyor: $Database"
Write-Output "App user: $AppUser"
Write-Output "DSN .env ichida: POSTGRES_DSN"
