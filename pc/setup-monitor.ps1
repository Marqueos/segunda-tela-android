# Segunda Tela: prepara o monitor virtual do tablet (roda uma vez, como administrador).
# O painel chama este script pelo botão "Ativar monitor do tablet".
#
# 1. Instala o Virtual Display Driver (github.com/VirtualDrivers/Virtual-Display-Driver, MIT),
#    baixado da página oficial de releases e conferido pelo SHA256, se ainda não estiver instalado.
# 2. Configura 1 monitor com a resolução do tablet.
# 3. Cria duas tarefas do Windows que só ligam/desligam esse dispositivo. Rodam como SYSTEM;
#    qualquer usuário pode dispará-las (schtasks /run), só administrador pode alterá-las.
#    Assim o app liga o monitor quando o tablet conecta e desliga quando sai, sem pedir senha.
# 4. Desliga o monitor virtual: ele só existe enquanto o tablet estiver conectado.
#
# Desfazer: schtasks /delete /tn \SegundaTela\LigarMonitor /f
#           schtasks /delete /tn \SegundaTela\DesligarMonitor /f
#           e desinstalar "Virtual Display Driver" no Gerenciador de Dispositivos.
param([int]$Width = 1920, [int]$Height = 1080)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Url = 'https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/25.7.23/VDD.Control.25.7.23.zip'
$Sha256 = 'A701F2272E9FCF382849B24F913C6DD07597B3B1116525F2E90182F019609154'
$dir = Join-Path $env:ProgramData 'SegundaTela'
New-Item -ItemType Directory -Force $dir | Out-Null
Start-Transcript -Path (Join-Path $dir 'setup.log') -Force | Out-Null

function Find-Vdd { Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.HardwareID -contains 'Root\MttVDD' } }

try {
    # 1. Driver
    if (-not (Find-Vdd)) {
        $zip = Join-Path $dir 'VDD.Control.25.7.23.zip'
        if (-not (Test-Path $zip) -or (Get-FileHash $zip -Algorithm SHA256).Hash -ne $Sha256) {
            "Baixando $Url"
            & curl.exe -sSL --fail -o $zip $Url
            if ($LASTEXITCODE -ne 0) { throw "download falhou (curl $LASTEXITCODE)" }
        }
        $hash = (Get-FileHash $zip -Algorithm SHA256).Hash
        if ($hash -ne $Sha256) { Remove-Item $zip; throw "arquivo baixado não confere (SHA256 $hash)" }
        $vdd = Join-Path $dir 'vdd'
        New-Item -ItemType Directory -Force $vdd | Out-Null
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $z = [IO.Compression.ZipFile]::OpenRead($zip)
        try {
            foreach ($e in $z.Entries) {
                if ($e.Name -and ($e.FullName -eq 'Dependencies/devcon.exe' -or $e.FullName -like 'SignedDrivers/x86/VDD/*')) {
                    [IO.Compression.ZipFileExtensions]::ExtractToFile($e, (Join-Path $vdd $e.Name), $true)
                }
            }
        } finally { $z.Dispose() }
        & (Join-Path $vdd 'devcon.exe') install (Join-Path $vdd 'MttVDD.inf') 'Root\MttVDD'
        if (-not (Find-Vdd)) { throw "o driver não instalou (devcon $LASTEXITCODE)" }
        'Driver instalado.'
    } else {
        'Driver já instalado.'
    }

    # 2. Um monitor, com a resolução do tablet primeiro (o Windows usa a primeira da lista)
    $list = @("${Width}x${Height}") + @('1920x1080', '1600x900', '1366x768', '2560x1440' | Where-Object { $_ -ne "${Width}x${Height}" })
    $resXml = ($list | ForEach-Object {
        $w, $h = $_ -split 'x'
        "        <resolution><width>$w</width><height>$h</height><refresh_rate>60</refresh_rate></resolution>"
    }) -join "`r`n"
    New-Item -ItemType Directory -Force 'C:\VirtualDisplayDriver' | Out-Null
    @"
<?xml version='1.0' encoding='utf-8'?>
<vdd_settings>
    <monitors><count>1</count></monitors>
    <gpu><friendlyname>default</friendlyname></gpu>
    <global><g_refresh_rate>60</g_refresh_rate></global>
    <resolutions>
$resXml
    </resolutions>
    <options>
        <CustomEdid>false</CustomEdid><PreventSpoof>false</PreventSpoof><EdidCeaOverride>false</EdidCeaOverride>
        <HardwareCursor>true</HardwareCursor><SDR10bit>false</SDR10bit><HDRPlus>false</HDRPlus>
        <logging>false</logging><debuglogging>false</debuglogging>
    </options>
</vdd_settings>
"@ | Set-Content -Path 'C:\VirtualDisplayDriver\vdd_settings.xml' -Encoding UTF8
    "Resolução do monitor do tablet: ${Width}x${Height}"

    # 3. Tarefas liga/desliga
    $find = 'Get-PnpDevice | Where-Object { $_.HardwareID -contains ''Root\MttVDD'' }'
    $svc = New-Object -ComObject Schedule.Service
    $svc.Connect()
    $root = $svc.GetFolder('\')
    try { $folder = $root.GetFolder('SegundaTela') } catch { $folder = $root.CreateFolder('SegundaTela') }
    foreach ($t in @(@('LigarMonitor', 'Enable-PnpDevice'), @('DesligarMonitor', 'Disable-PnpDevice'))) {
        $def = $svc.NewTask(0)
        $def.RegistrationInfo.Description = 'Segunda Tela: liga/desliga o monitor virtual do tablet'
        $def.Settings.DisallowStartIfOnBatteries = $false
        $def.Settings.StopIfGoingOnBatteries = $false
        $def.Settings.ExecutionTimeLimit = 'PT2M'
        $def.Settings.MultipleInstances = 0
        $def.Principal.RunLevel = 1
        $action = $def.Actions.Create(0)
        $action.Path = 'powershell.exe'
        $action.Arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$find | $($t[1]) -Confirm:`$false`""
        # Administradores e SYSTEM: controle total; usuários autenticados: só ler e executar.
        $folder.RegisterTaskDefinition($t[0], $def, 6, 'SYSTEM', $null, 5, 'D:(A;;FA;;;BA)(A;;FA;;;SY)(A;;GRGX;;;AU)') | Out-Null
        "Tarefa criada: \SegundaTela\$($t[0])"
    }

    # 4. Desliga até o tablet conectar
    Find-Vdd | Disable-PnpDevice -Confirm:$false
    'Monitor do tablet desligado; liga sozinho quando o tablet conectar.'
    'OK'
} catch {
    "ERRO: $_"
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
