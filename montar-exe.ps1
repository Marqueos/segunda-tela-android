# Segunda Tela: monta o SegundaTela.exe (painel do PC num arquivo só).
# Rode pelo Montar-EXE.bat (clique duas vezes). Precisa do Python 3.10+ (o Instalar.bat confere).
# Resultado: dist\SegundaTela.exe, na pasta deste projeto.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$pc = Join-Path $root 'pc'
$work = Join-Path $env:TEMP 'SegundaTela-build'  # arquivos temporários da montagem ficam fora do projeto

$python = $null
foreach ($cmd in @('python', 'py')) {
    $exe = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($exe) { $python = $exe.Source; break }
}
if (-not $python) { throw 'Python não encontrado. Rode o Instalar.bat primeiro.' }

Write-Host '== Bibliotecas (requirements.txt + PyInstaller)' -ForegroundColor Cyan
& $python -m pip install --user --disable-pip-version-check -q -r (Join-Path $pc 'requirements.txt') pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'pip falhou.' }

Write-Host '== Teste' -ForegroundColor Cyan
& $python (Join-Path $pc 'test_server.py')
if ($LASTEXITCODE -ne 0) { throw 'O teste falhou; o exe não foi montado.' }

Write-Host '== Montando o exe (1 a 3 minutos)' -ForegroundColor Cyan
Push-Location $pc
try {
    # caminhos absolutos: com --specpath, relativos seriam lidos a partir da pasta temporária
    & $python -m PyInstaller --noconfirm --clean --onefile --windowed --name SegundaTela `
        --icon "$pc\icon.ico" --add-data "$pc\icon.ico;." --add-data "$pc\icon.png;." --add-data "$pc\setup-monitor.ps1;." `
        --collect-all dxcam --collect-all av --hidden-import comtypes.stream `
        --workpath $work --specpath $work --distpath (Join-Path $root 'dist') gui.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falhou.' }
} finally {
    Pop-Location
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $pc '__pycache__') -ErrorAction SilentlyContinue
}
Write-Host "`nPronto: $(Join-Path $root 'dist\SegundaTela.exe')" -ForegroundColor Green
