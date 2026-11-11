<#
.SYNOPSIS
  Ejecuta en orden los scripts de database/scripts contra SQL Server.
  Todos los scripts son idempotentes (se pueden re-ejecutar).

.EXAMPLE
  .\database\deploy.ps1                                   # localhost, autenticacion Windows
  .\database\deploy.ps1 -Server "srv\INST" -Database MetamorphERP -User sa -Password '***'
#>
param(
    [string]$Server   = "localhost",
    [string]$Database = "MetamorphERP",
    [string]$User,
    [string]$Password
)

$ErrorActionPreference = "Stop"
$scriptsDir = Join-Path $PSScriptRoot "scripts"

[string[]]$auth = if ($User) { @("-U", $User, "-P", $Password) } else { @("-E") }

# Crea la base si no existe (se conecta a master)
& sqlcmd -S $Server @auth -C -b -d master -Q "IF DB_ID(N'$Database') IS NULL CREATE DATABASE [$Database];"
if ($LASTEXITCODE -ne 0) { throw "No se pudo verificar/crear la base $Database" }

Get-ChildItem $scriptsDir -Filter "*.sql" | Sort-Object Name | ForEach-Object {
    Write-Host ">> $($_.Name)" -ForegroundColor Cyan
    # -b: aborta al primer error | -f 65001: lee el archivo como UTF-8 | -C: confia en el certificado (dev)
    & sqlcmd -S $Server @auth -C -b -I -f 65001 -d $Database -i $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Fallo $($_.Name)" }
}

Write-Host "Despliegue completado en [$Server].[$Database]" -ForegroundColor Green
