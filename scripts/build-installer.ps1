#Requires -Version 5.1
param(
  [string]$PythonVersion = "3.12.8",
  [string]$AppVersion = "0.1.0",
  [switch]$SkipDownload,
  [switch]$SkipInno
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Packaging = Join-Path $Root "packaging"
$Payload = Join-Path $Packaging "payload"
$Runtime = Join-Path $Payload "runtime"
$Dist = Join-Path $Root "dist"
$Cache = Join-Path $Packaging "cache"

$EmbedName = "python-$PythonVersion-embed-amd64.zip"
$EmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/$EmbedName"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"

function Write-Step([string]$msg) {
  Write-Host ""
  Write-Host "==> $msg" -ForegroundColor Cyan
}

function Find-ISCC {
  $candidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:LocalAppData}\Programs\Inno Setup 6\ISCC.exe"
  )
  foreach ($p in $candidates) {
    if (Test-Path $p) { return $p }
  }
  $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

Write-Step "prepare dirs"
New-Item -ItemType Directory -Force -Path $Cache, $Dist | Out-Null
if (Test-Path $Payload) {
  Remove-Item -Recurse -Force $Payload
}
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

$zipPath = Join-Path $Cache $EmbedName
if ((-not $SkipDownload) -or (-not (Test-Path $zipPath))) {
  Write-Step "download embeddable Python $PythonVersion"
  Invoke-WebRequest -Uri $EmbedUrl -OutFile $zipPath -UseBasicParsing
}

Write-Step "extract runtime"
Expand-Archive -Path $zipPath -DestinationPath $Runtime -Force

$pth = Get-ChildItem $Runtime -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "python*._pth not found" }
$pthText = Get-Content $pth.FullName -Raw
if ($pthText -notmatch "(?m)^import site\s*$") {
  $pthText = $pthText -replace "(?m)^#\s*import site\s*$", "import site"
  if ($pthText -notmatch "(?m)^import site\s*$") {
    $pthText = $pthText.TrimEnd() + "`r`nimport site`r`n"
  }
  Set-Content -Path $pth.FullName -Value $pthText -Encoding ASCII
}

$python = Join-Path $Runtime "python.exe"
$getPip = Join-Path $Cache "get-pip.py"
if (-not (Test-Path $getPip)) {
  Write-Step "download get-pip.py"
  Invoke-WebRequest -Uri $GetPipUrl -OutFile $getPip -UseBasicParsing
}

Write-Step "install pip"
& $python $getPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip failed" }

Write-Step "install runtime deps"
$req = Join-Path $Root "requirements-runtime.txt"
if (-not (Test-Path $req)) { $req = Join-Path $Root "requirements.txt" }
& $python -m pip install --upgrade pip setuptools wheel --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip/setuptools bootstrap failed" }
& $python -m pip install -r $req --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Step "copy app files"
$appSrc = Join-Path $Root "app"
$appDst = Join-Path $Payload "app"
Copy-Item -Recurse -Force $appSrc $appDst
Get-ChildItem $appDst -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$scriptsDst = Join-Path $Payload "scripts"
New-Item -ItemType Directory -Force -Path $scriptsDst | Out-Null
Copy-Item -Force (Join-Path $Root "scripts\launcher.py") (Join-Path $scriptsDst "launcher.py")
Copy-Item -Force (Join-Path $Packaging "Start.bat") (Join-Path $Payload "Start.bat")
Copy-Item -Force $req (Join-Path $Payload "requirements.txt")

$docsDst = Join-Path $Payload "docs"
New-Item -ItemType Directory -Force -Path $docsDst | Out-Null
$installDoc = Join-Path $Root "docs\安装与使用.md"
if (Test-Path $installDoc) {
  Copy-Item -Force $installDoc (Join-Path $docsDst "安装与使用.md")
}

$issPath = Join-Path $Packaging "setup.iss"
$iss = Get-Content $issPath -Raw -Encoding UTF8
$verLine = '#define MyAppVersion "' + $AppVersion + '"'
$iss = [regex]::Replace($iss, '#define MyAppVersion ".*?"', $verLine)
[System.IO.File]::WriteAllText($issPath, $iss, [System.Text.UTF8Encoding]::new($false))

Write-Step "portable zip"
$portableZip = Join-Path $Dist ("买入时机-portable-" + $AppVersion + ".zip")
if (Test-Path $portableZip) { Remove-Item -Force $portableZip }
Compress-Archive -Path (Join-Path $Payload "*") -DestinationPath $portableZip -Force
Write-Host ("created: " + $portableZip)

$iscc = Find-ISCC
if ($SkipInno) {
  Write-Host ("SkipInno. payload: " + $Payload)
  exit 0
}
if (-not $iscc) {
  Write-Warning "Inno Setup 6 (ISCC.exe) not found. Portable zip is ready."
  Write-Host "https://jrsoftware.org/isinfo.php"
  Write-Host ("payload: " + $Payload)
  exit 0
}

Write-Step ("compile Setup.exe via " + $iscc)
& $iscc $issPath
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }

$setup = Join-Path $Dist ("买入时机-Setup-" + $AppVersion + ".exe")
if (Test-Path $setup) {
  Write-Host ("done: " + $setup) -ForegroundColor Green
} else {
  Write-Host "ISCC finished; check dist\" -ForegroundColor Green
}
Get-ChildItem $Dist | Format-Table Name, Length, LastWriteTime
