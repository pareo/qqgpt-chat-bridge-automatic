param(
    [ValidateSet('help','init','configure','doctor','setup','start','stop','restart','status','logs','api-check','test','webui','napcat-webui','worker-build','worker-start','worker-stop','worker-status','worker-reset','worker-test')]
    [string]$Action = 'help',
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ExtraArgs
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
if ($Action.StartsWith('worker-')) {
    & (Join-Path $PSScriptRoot 'desktop-worker.ps1') -Action $Action.Substring(7)
    exit $LASTEXITCODE
}
$Docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $Docker) {
    $DockerPath = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
    if (Test-Path -LiteralPath $DockerPath) { $Docker = Get-Item -LiteralPath $DockerPath }
}
if (-not $Docker) { throw 'Docker Desktop is required. Install it, enable the Linux engine, and retry.' }
$DockerExe = if ($Docker.Source) { $Docker.Source } else { $Docker.FullName }
$env:PATH = (Split-Path -Parent $DockerExe) + ';' + $env:PATH
$BaseImage = 'sengokucola/maibot@sha256:ada1d38593fe4756cc1b8af100ec62136d0e011416cd2cfd7908cdb1422443eb'
function Invoke-Docker([string[]]$DockerArgs) {
    & $DockerExe @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker failed (exit $LASTEXITCODE). See the error above." }
}
function Invoke-Tool([string]$ToolAction) {
    Invoke-Docker @('run','--rm','--add-host','host.docker.internal:host-gateway','--mount',"type=bind,source=$ProjectRoot,target=/project",'--entrypoint','python',$BaseImage,'/project/scripts/project.py',$ToolAction)
}
function Invoke-Compose([string[]]$ComposeArgs) {
    if (-not (Test-Path -LiteralPath 'config/generated/deployment.env')) { throw 'Run run.cmd init first.' }
    Invoke-Docker (@('compose','--env-file','config/generated/deployment.env') + $ComposeArgs)
}
if ($Action -eq 'help') {
    Write-Host 'Daifeilong / MaiBot + NapCat'
    Write-Host 'run.cmd init       Initialize local config (never overwrites existing values)'
    Write-Host 'run.cmd configure  Apply local config to MaiBot and NapCat'
    Write-Host 'run.cmd doctor     Check Docker, configuration, and API credentials'
    Write-Host 'run.cmd setup      Start the management UI without enabling QQ chat'
    Write-Host 'run.cmd start      Validate config and start services'
    Write-Host 'run.cmd stop       Stop services and preserve all data'
    Write-Host 'run.cmd restart    Restart services'
    Write-Host 'run.cmd status     Show service status'
    Write-Host 'run.cmd logs       Follow service logs (Ctrl+C exits logs only)'
    Write-Host 'run.cmd api-check  List accessible models (does not send a chat request)'
    Write-Host 'run.cmd test       Run offline tests; no QQ messages are sent'
    Write-Host 'run.cmd webui      Print a one-time MaiBot login URL'
    Write-Host 'run.cmd napcat-webui  Print the NapCat login URL'
    Write-Host 'run.cmd worker-build/start/stop/status/reset/test  Manage optional Windows ChatGPT task worker'
    exit 0
}
Invoke-Docker @('compose','version')
Invoke-Docker @('info','--format','{{.ServerVersion}}')
$EngineType = & $DockerExe info --format '{{.OSType}}'
if ($EngineType -ne 'linux') { throw 'Switch Docker Desktop to Linux containers before starting this project.' }
switch ($Action) {
    'init' { Invoke-Tool 'init' }
    'configure' { Invoke-Tool 'configure' }
    'doctor' { Invoke-Tool 'check' }
    'setup' { Invoke-Compose @('up','-d','--build','core') }
    'start' { Invoke-Tool 'check'; Invoke-Compose @('up','-d','--build') }
    'stop' { Invoke-Compose @('stop') }
    'restart' { Invoke-Tool 'check'; Invoke-Compose @('restart') }
    'status' { Invoke-Compose @('ps','-a'); Invoke-Compose @('exec','-T','core','python','-m','src.cli.tool','host','status','-d','/MaiMBot'); Invoke-Compose @('exec','-T','core','python','/project/scripts/api_smoke.py','qq-status') }
    'logs' { Invoke-Compose (@('logs','--tail','120','-f') + $ExtraArgs) }
    'api-check' { Invoke-Tool 'api-check' }
    'test' { Invoke-Compose @('run','--rm','--no-deps','--entrypoint','python','core','-m','unittest','discover','-s','/project/tests','-v') }
    'webui' {
        $LinkOutput = & $DockerExe compose --env-file config/generated/deployment.env exec -T core python -m src.cli.tool host open-webui -d /MaiMBot
        if ($LASTEXITCODE -ne 0) { throw 'MaiBot is not running; use setup or start first.' }
        $Port = (Get-Content -LiteralPath 'config/local/project.json' -Raw | ConvertFrom-Json).ports.maibot
        Write-Host (($LinkOutput | ConvertFrom-Json).url.Replace(':8001/', ":$Port/"))
    }
    'napcat-webui' { Invoke-Tool 'napcat-url' }
}
