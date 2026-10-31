# Segunda Tela

Use um tablet Android como **segunda tela do Windows** (área de trabalho estendida), pelo cabo USB ou pelo Wi-Fi, com toque de verdade (multitoque).

- Vídeo H.264 a até 60 quadros por segundo: o PC captura e codifica, e o tablet decodifica no chip de vídeo.
- O Windows enxerga um monitor de verdade, criado pelo [Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver) (MIT). Ele só fica ligado enquanto o tablet está conectado.
- Toques do tablet viram toques do Windows: tocar, arrastar, pinça, rolar com dois dedos e segurar.

## Instalação

1. Baixe esta pasta (botão **Code > Download ZIP** no GitHub) e extraia.
2. Clique duas vezes em **`Instalar.bat`**. Ele:
   - confere o Python 3.10+ e, se faltar, oferece instalar pelo `winget`;
   - instala as bibliotecas do PC (`pc/requirements.txt`);
   - baixa o `adb` oficial do Google, se você não tiver;
   - instala o app no tablet pelo cabo (`release/SegundaTela.apk`);
   - cria o atalho **Segunda Tela** na Área de Trabalho.
3. Abra **Segunda Tela** e, na primeira vez, clique em **Ativar monitor do tablet**. O Windows pede confirmação de administrador uma vez. Isso:
   - baixa o Virtual Display Driver da página oficial de releases e confere o SHA256;
   - instala o driver e configura a resolução do tablet;
   - cria duas tarefas do Windows (`\SegundaTela\LigarMonitor` e `\SegundaTela\DesligarMonitor`) que só ligam ou desligam esse monitor. Assim o app não pede senha a cada conexão.
4. Clique em **Iniciar**. No modo USB, o app abre sozinho no tablet.

### No tablet

Ative a **Depuração USB**: Configurações > Sobre > toque 7 vezes em "Número da versão" > Opções do desenvolvedor > Depuração USB. Em tablets Xiaomi/MIUI, ative também "Instalar via USB" e toque em **Instalar** quando o tablet pedir.

### Wi-Fi

No painel, escolha **Wi-Fi**. No tablet, digite o IP mostrado no painel. **Use só em rede confiável:** não há senha, e quem estiver na rede pode ver sua tela e tocar nela. No modo USB, o PC só aceita conexões do próprio cabo (`127.0.0.1`).

## Requisitos

- Windows 10/11 com placa de vídeo Intel (a captura usa DXGI e Intel Quick Sync). Em outras placas, o app usa a captura pela CPU, que é bem mais lenta.
- Tablet Android 8.0 ou mais novo.
- Para 60 quadros/s em telas pesadas, deixe o notebook na tomada.

## Estrutura

| Pasta | O que é |
|---|---|
| `pc/server.py` | Captura (FFmpeg `ddagrab`), vídeo H.264, toque (InjectTouchInput) e o liga/desliga do monitor |
| `pc/gui.py` | Painel (tkinter) |
| `pc/setup-monitor.ps1` | Ativação única do monitor virtual (administrador) |
| `pc/test_server.py` | Teste: `python pc/test_server.py` |
| `android/` | App Android (Kotlin, sem dependências) |
| `release/SegundaTela.apk` | App já compilado |
| `tools/icons.py` | Gera os ícones |

## Compilar

- **App Android** (precisa do JDK 17+ e do Android SDK): `cd android` e depois `gradlew.bat assembleDebug`. O APK sai em `android/app/build/outputs/apk/debug/`.
- **Executável do PC** (opcional): clique duas vezes em **`Montar-EXE.bat`**. Ele instala o PyInstaller, roda o teste e gera `dist/SegundaTela.exe`. Esse arquivo é um programa só, com o painel, o FFmpeg e o script de ativação dentro.

## Protocolo (TCP, big-endian)

- PC → tablet: `"H264"`, depois `int32` largura e `int32` altura. Em seguida, repetido: `[int32 tamanho][quadro H.264 Annex B]`.
- Tablet → PC, repetido: `[byte ação | dedo << 4][float x][float y]`, com x e y de 0 a 1. As ações são 0 encostar, 1 mover, 2 soltar e 3 quadro mostrado (usado para controlar o fluxo).

## Desinstalar

- Apague as tarefas: `schtasks /delete /tn \SegundaTela\LigarMonitor /f` e `schtasks /delete /tn \SegundaTela\DesligarMonitor /f`.
- Desinstale "Virtual Display Driver" no Gerenciador de Dispositivos.
- Apague o atalho, a pasta `%LOCALAPPDATA%\SegundaTela` e a pasta `%ProgramData%\SegundaTela`.

## Licença

MIT (veja `LICENSE`). O Virtual Display Driver é de outro projeto (MIT) e é baixado da página oficial dele; ele não vem incluído aqui.
