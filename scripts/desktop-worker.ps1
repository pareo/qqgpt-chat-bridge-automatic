param([ValidateSet('build','start','stop','status','reset','test')][string]$Action='status')
$ErrorActionPreference='Stop'
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$WorkerRoot=Join-Path $ProjectRoot 'services/desktop-worker'
$StateRoot=Join-Path $ProjectRoot 'data/desktop-worker'
$LogRoot=Join-Path $ProjectRoot 'logs/desktop-worker'
$PidPath=Join-Path $StateRoot 'worker.pid'
$NodePath=if($env:DAIFEILONG_NODE){$env:DAIFEILONG_NODE}elseif(Test-Path -LiteralPath "$WorkerRoot/bin/node.exe"){"$WorkerRoot/bin/node.exe"}else{'node'}
$NodeCommand=Get-Command $NodePath -ErrorAction SilentlyContinue
if(-not $NodeCommand){throw 'Install Node.js 22.13+ x64 or put node.exe in services/desktop-worker/bin/.'}
$NodeExe=$NodeCommand.Source
$NodeVersion=& $NodeExe --version
if($LASTEXITCODE -ne 0 -or $NodeVersion -notmatch '^v(\d+)\.(\d+)\.(\d+)' -or [version]$NodeVersion.TrimStart('v') -lt [version]'22.13.0'){throw 'Desktop worker requires Node.js 22.13+ x64.'}
function Build-Worker {
    $framework=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319'
    $compiler=Join-Path $framework 'csc.exe'
    if(-not(Test-Path -LiteralPath $compiler)){throw 'Install .NET Framework 4.x x64 before building the Windows worker.'}
    New-Item -ItemType Directory -Path "$WorkerRoot/bin" -Force | Out-Null
    $sources=@('Bridge.cs','ImageBridge.cs','QuoteBridge.cs','MentionBridge.cs','FileBridge.cs','RecoveryBridge.cs','GroupBridge.cs','TableBridge.cs')|ForEach-Object{Join-Path $WorkerRoot "native/$_"}
    $refs=@('/reference:Accessibility.dll','/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',"/reference:$framework/WPF/UIAutomationClient.dll","/reference:$framework/WPF/UIAutomationTypes.dll")
    & $compiler /nologo /platform:x64 "/out:$WorkerRoot/bin/ChatGPTWorker.exe" @refs @sources
    if($LASTEXITCODE -ne 0){throw 'Worker compilation failed; stop worker before rebuilding.'}
}
function Worker-Process {
    if(-not(Test-Path -LiteralPath $PidPath)){return $null}
    $workerPid=0
    if(-not [int]::TryParse((Get-Content -LiteralPath $PidPath -Raw).Trim(),[ref]$workerPid)){throw 'Invalid worker PID file.'}
    $entry=Join-Path $WorkerRoot 'src/server.js'
    $proc=Get-CimInstance Win32_Process -Filter "ProcessId = $workerPid" -ErrorAction SilentlyContinue
    if($proc -and $proc.Name -eq 'node.exe' -and $proc.CommandLine.Contains($entry)){return $proc}
    return $null
}
function Worker-Request([string]$Endpoint,[string]$Method='GET') {
    $config=Get-Content -LiteralPath "$ProjectRoot/config/local/project.json" -Raw | ConvertFrom-Json
    $secrets=Get-Content -LiteralPath "$ProjectRoot/config/local/secrets.json" -Raw | ConvertFrom-Json
    $port=if($config.desktop_worker.port){$config.desktop_worker.port}else{18120}
    Invoke-RestMethod -Uri "http://127.0.0.1:$port$Endpoint" -Headers @{Authorization="Bearer $($secrets.desktop_worker_token)"} -Method $Method -TimeoutSec 4
}
switch($Action){
    'build'{Build-Worker}
    'test'{& $NodeExe --test "$WorkerRoot/test/worker.test.js";if($LASTEXITCODE -ne 0){throw 'Worker offline tests failed.'}}
    'status'{Worker-Request '/health' | ConvertTo-Json}
    'reset'{Worker-Request '/v1/reset' 'POST' | ConvertTo-Json}
    'stop'{
        $proc=Worker-Process
        if($proc){Stop-Process -Id $proc.ProcessId;Write-Output 'Desktop worker stopped. Incomplete submissions will not be replayed.'}else{Write-Output 'Desktop worker is not running.'}
    }
    'start'{
        if(Worker-Process){Worker-Request '/health' | ConvertTo-Json;break}
        if(-not(Test-Path -LiteralPath "$WorkerRoot/bin/ChatGPTWorker.exe")){Build-Worker}
        # Validate settings without opening or modifying any ChatGPT/QQ window.
        & $NodeExe -e 'require(process.argv[1]).settings();' "$WorkerRoot/src/settings.js"
        if($LASTEXITCODE -ne 0){throw 'Worker configuration check failed.'}
        New-Item -ItemType Directory -Path $StateRoot,$LogRoot -Force | Out-Null
        $entry=Join-Path $WorkerRoot 'src/server.js'
        $proc=Start-Process -FilePath $NodeExe -ArgumentList @('"'+$entry+'"') -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput "$LogRoot/stdout.log" -RedirectStandardError "$LogRoot/stderr.log" -PassThru
        $proc.Id | Set-Content -LiteralPath $PidPath -Encoding ASCII
        Start-Sleep -Milliseconds 700
        try{Worker-Request '/health' | ConvertTo-Json}catch{throw 'Worker did not start; see logs/desktop-worker/stderr.log.'}
    }
}
