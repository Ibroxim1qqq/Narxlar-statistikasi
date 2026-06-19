$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $ProjectRoot ".env"
$PostgresPackage = "PostgreSQL.PostgreSQL.17"
$PgAdminPackage = "PostgreSQL.pgAdmin"
$AdminPassword = "NarxlarAdmin2026"

if (Test-Path $EnvPath) {
    Get-Content $EnvPath | ForEach-Object {
        if ($_.Trim().StartsWith("POSTGRES_ADMIN_PASSWORD=")) {
            $AdminPassword = $_.Split("=", 2)[1].Trim().Trim('"').Trim("'")
        }
    }
}

winget install `
    --id $PostgresPackage `
    --source winget `
    --accept-source-agreements `
    --accept-package-agreements `
    --silent `
    --override "--mode unattended --unattendedmodeui none --superpassword $AdminPassword --servicename postgresql-x64-17 --serverport 5432 --locale C --disable-components stackbuilder"

winget install `
    --id $PgAdminPackage `
    --source winget `
    --accept-source-agreements `
    --accept-package-agreements `
    --silent

Write-Output "PostgreSQL va pgAdmin o'rnatildi yoki allaqachon mavjud."
Write-Output "Keyingi qadam: .\scripts\setup_postgres_database.ps1"
