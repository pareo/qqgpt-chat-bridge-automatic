param([ValidateSet('prepare','build','login','start','stop','status','smoke')][string]$Action='status')
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$docker=Get-Command docker -ErrorAction SilentlyContinue
$dockerExe=if($docker){$docker.Source}else{Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'}
$env:PATH=(Split-Path -Parent $dockerExe)+';'+$env:PATH
$compose=@('compose','--env-file','config/generated/deployment.env','-f','compose.yaml','-f','compose.codex.yaml')
function Invoke-Compose([string[]]$values){& $dockerExe @compose @values;if($LASTEXITCODE -ne 0){throw 'Codex worker command failed. No backend switch was applied.'}}
switch($Action){
 'prepare'{& $dockerExe run --rm --network none --mount "type=bind,source=$Root,target=/project" --entrypoint python daifeilong-maibot-core:1.4.3 /project/scripts/codex_config.py;if($LASTEXITCODE -ne 0){throw 'Preparation failed'}}
 'build'{Invoke-Compose @('build','codex-worker')}
 'start'{Invoke-Compose @('up','-d','--no-deps','codex-worker')}
 'stop'{Invoke-Compose @('stop','codex-worker')}
 'status'{Invoke-Compose @('ps','codex-worker')}
 'login'{
  New-Item -ItemType Directory -Path 'logs/codex-worker' -Force | Out-Null
  $arguments=$compose+@('run','--rm','--no-deps','codex-worker','node','node_modules/@agentclientprotocol/codex-acp/dist/index.js','cli','login','--device-auth')
  Start-Process -FilePath $dockerExe -ArgumentList $arguments -WindowStyle Hidden -WorkingDirectory $Root -RedirectStandardOutput "$Root/logs/codex-worker/login.log" -RedirectStandardError "$Root/logs/codex-worker/login-error.log" | Out-Null
  Write-Output 'Login started. Open logs/codex-worker/login.log for the device URL and code. Complete authorization yourself.'
 }
 'smoke'{Invoke-Compose @('exec','-T','codex-worker','node','src/smoke.js')}
}
