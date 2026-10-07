<#
.SYNOPSIS
  Builds the portable Interis folder: Interis.exe + its own Python runtime + all packages.

.DESCRIPTION
  Result (default build\Interis):
      Interis.exe             starter (compiled here from packaging\launcher\Interis.cs)
      runtime\                Python 3.11 (python-build-standalone, relocatable) with all
                              packages installed from uv.lock – exact versions, hash-checked
      Internet-sperren.ps1    optional firewall rule for runtime\python(w).exe
      LIESMICH.txt
  The models are NOT included: on first start Interis asks for an existing models folder
  (linked in place) or downloads them into a folder of your choice.

  The folder is self-contained and can be moved or copied (other drive, USB stick).

.EXAMPLE
  .\packaging\build_portable.ps1
  .\packaging\build_portable.ps1 -Zip
#>
param(
    [string]$Out = 'build\Interis',
    [switch]$Zip
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed ($LASTEXITCODE)" } }

$Out = [IO.Path]::GetFullPath((Join-Path $repo $Out))
$work = Join-Path $repo 'build\work'
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force -Path $Out, $work | Out-Null

Step 'Checking the built user interface'
if (-not (Test-Path 'src\interis\web\dist\index.html')) {
    throw 'src\interis\web\dist is missing – run `npm ci; npm run build` in frontend\ first.'
}

Step 'Building the Interis wheel'
uv build --wheel --out-dir (Join-Path $work 'wheel'); Check 'uv build'
$wheel = Get-ChildItem (Join-Path $work 'wheel') -Filter 'interis-*.whl' | Select-Object -First 1

Step 'Python runtime (uv-managed, relocatable python-build-standalone)'
$version = & .venv\Scripts\python.exe -c "import platform; print(platform.python_version())"; Check 'python version'
uv python install $version; Check 'uv python install'
$basePython = (uv python find --managed-python $version).Trim(); Check 'uv python find'
$runtimeSrc = Split-Path -Parent $basePython
Write-Host "Python $version from $runtimeSrc"
robocopy $runtimeSrc (Join-Path $Out 'runtime') /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0
$py = Join-Path $Out 'runtime\python.exe'
# uv marks its Pythons as externally managed; this copy belongs to Interis alone.
Get-ChildItem (Join-Path $Out 'runtime') -Recurse -Filter 'EXTERNALLY-MANAGED' | Remove-Item -Force

Step 'Installing the locked packages (exact versions, every file hash-checked)'
$req = Join-Path $work 'requirements.txt'
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file $req | Out-Null; Check 'uv export'
uv pip install --python $py --system --require-hashes --no-deps --compile-bytecode `
    --index-strategy unsafe-best-match --extra-index-url https://download.pytorch.org/whl/cpu `
    -r $req; Check 'uv pip install (dependencies)'
uv pip install --python $py --system --no-deps --compile-bytecode $wheel.FullName; Check 'uv pip install (interis)'

Step 'Self-check of the runtime'
& $py -I -c "import interis.desktop, webview, torch, faster_whisper, pyannote.audio; print('imports ok, torch', torch.__version__)"
Check 'runtime import check'

Step 'Compiling Interis.exe (C# compiler built into Windows)'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $csc /nologo /target:winexe /optimize+ /out:(Join-Path $Out 'Interis.exe') `
    /r:System.Windows.Forms.dll packaging\launcher\Interis.cs; Check 'csc'

Step 'Extras'
Copy-Item packaging\portable\* $Out
$size = (Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Host ("Portable folder: {0} ({1:N1} GB)" -f $Out, $size)

if ($Zip) {
    Step 'Zipping'
    $zipFile = "$Out.zip"
    if (Test-Path $zipFile) { Remove-Item $zipFile }
    tar.exe -a -c -f $zipFile -C (Split-Path $Out) (Split-Path $Out -Leaf); Check 'tar'
    Write-Host ("Zip: {0} ({1:N1} GB)" -f $zipFile, ((Get-Item $zipFile).Length / 1GB))
}
Write-Host "`nDone. Start: $Out\Interis.exe" -ForegroundColor Green
