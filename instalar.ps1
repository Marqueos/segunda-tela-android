# Segunda Tela: instalador (Windows 10/11).
# Rode pelo Instalar.bat (clique duas vezes). Não precisa de administrador.
#
# 1. Confere o Python 3.10+ (se faltar, oferece instalar pelo winget).
# 2. Instala as bibliotecas do pc\requirements.txt para o seu usuário.
# 3. Confere o adb; se faltar, baixa o Android Platform Tools oficial do Google.
# 4. Instala o app no tablet pelo cabo USB (release\SegundaTela.apk).
# 5. Cria o atalho "Segunda Tela" na Área de Trabalho.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = $PSScriptRoot

function Passo($texto) { Write-Host "`n== $texto" -ForegroundColor Cyan }
function Pergunta($texto) { (Read-Host "$texto [S/n]") -notmatch '^[nN]' }

# 1. Python
Passo 'Python'
function Find-Python {
    foreach ($cmd in @('python', 'py')) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $args_ = if ($cmd -eq 'py') { @('-3') } else { @() }
        try {
            $path = & $exe.Source @args_ -c "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2>$null
            if ($path -and (Test-Path $path)) { return $path.Trim() }
        } catch { }
    }
    return $null
}
$python = Find-Python
if (-not $python) {
    Write-Host 'Python 3.10 ou mais novo não encontrado.'
    if (Pergunta 'Instalar o Python 3.12 pelo winget agora?') {
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $python = Find-Python
    }
    if (-not $python) { throw 'Instale o Python 3.10+ (python.org) e rode o instalador de novo.' }
}
Write-Host "Usando $python"

# 2. Bibliotecas
Passo 'Bibliotecas do Python'
& $python -m pip install --user --disable-pip-version-check -r (Join-Path $root 'pc\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'pip falhou ao instalar as bibliotecas.' }

# 3. adb
Passo 'adb (ligação com o tablet pelo cabo)'
$adb = (Get-Command adb -ErrorAction SilentlyContinue).Source
foreach ($p in @("$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe", "$env:LOCALAPPDATA\SegundaTela\platform-tools\adb.exe")) {
    if (-not $adb -and (Test-Path $p)) { $adb = $p }
}
if (-not $adb) {
    Write-Host 'adb não encontrado: baixando o Android Platform Tools do Google...'
    $dest = Join-Path $env:LOCALAPPDATA 'SegundaTela'
    New-Item -ItemType Directory -Force $dest | Out-Null
    $zip = Join-Path $dest 'platform-tools.zip'
    Invoke-WebRequest 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $dest -Force
    Remove-Item $zip
    $adb = Join-Path $dest 'platform-tools\adb.exe'
}
Write-Host "Usando $adb"

# 4. App no tablet
Passo 'App no tablet'
$apk = Join-Path $root 'release\SegundaTela.apk'
if (Pergunta 'Instalar o app no tablet agora (pelo cabo USB)?') {
    Write-Host 'No tablet: Configurações > Sobre > toque 7 vezes em "Número da versão" (ou "Versão do MIUI"),'
    Write-Host 'depois Opções do desenvolvedor > ative "Depuração USB" (no Xiaomi, também "Instalar via USB").'
    Write-Host 'Ligue o cabo e aceite o aviso "Permitir depuração USB" no tablet.'
    Read-Host 'Pressione Enter quando o tablet estiver ligado no cabo'
    & $adb wait-for-device
    Write-Host 'Instalando... se o tablet pedir confirmação, toque em "Instalar".'
    & $adb install -r $apk
    if ($LASTEXITCODE -ne 0) { Write-Warning "A instalação falhou. Tente de novo ou copie $apk para o tablet e abra lá." }
}

# 5. Atalho
Passo 'Atalho na Área de Trabalho'
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = $python }
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Segunda Tela.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $pythonw
$s.Arguments = '"' + (Join-Path $root 'pc\gui.py') + '"'
$s.WorkingDirectory = Join-Path $root 'pc'
$s.IconLocation = Join-Path $root 'pc\icon.ico'
$s.Save()
Write-Host "Atalho criado: $lnk"

Write-Host "`nPronto! Abra 'Segunda Tela' na Área de Trabalho." -ForegroundColor Green
Write-Host 'Na primeira vez, clique em "Ativar monitor do tablet" para o tablet virar uma segunda tela.'
