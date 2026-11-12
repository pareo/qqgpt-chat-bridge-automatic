param(
    [Parameter(Mandatory, Position=0)][ValidateSet('bind', 'import')][string]$Action,
    [Parameter(Mandatory)][ValidatePattern('^[1-9][0-9]{4,11}$')][string]$QQ,
    [string]$File,
    [switch]$AllowImport
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $commandArgs = @('compose', '--env-file', 'config/generated/deployment.env', 'exec', '-T',
                     'core', 'python', '/project/scripts/maimai_local.py', $Action, $QQ)
    if ($Action -eq 'bind') {
        if ($AllowImport) { $commandArgs += '--allow-import' }
        docker @commandArgs
    } else {
        if (-not $File) { throw 'Specify -File with your latest NET score page.' }
        $scoreFile = Get-Item -LiteralPath $File
        if ($scoreFile.PSIsContainer -or $scoreFile.Extension -notin '.html', '.htm', '.txt' -or $scoreFile.Length -gt 10MB) {
            throw 'Choose a complete UTF-8 NET score page (.html, .htm or .txt, up to 10 MiB).'
        }
        Get-Content -LiteralPath $scoreFile.FullName -Raw -Encoding UTF8 | docker @commandArgs
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
