$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$checks=Invoke-WebRequest 'https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt' -TimeoutSec 25
$line=($checks.Content -split "`n"|Where-Object{$_ -match 'node-v22.*linux-x64.tar.xz$'}|Select-Object -First 1).Trim()
if(-not $line){throw 'Official Node checksum missing'}
$parts=$line -split '\s+'
New-Item -ItemType Directory -Path "$root/docker/runtime" -Force|Out-Null
$target=Join-Path $root 'docker/runtime/node-linux.tar.xz'
Invoke-WebRequest ('https://nodejs.org/dist/latest-v22.x/'+$parts[1]) -OutFile $target -TimeoutSec 90
if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower() -ne $parts[0]){throw 'Node runtime checksum mismatch'}
Write-Output "Official runtime verified: $($parts[1])"
