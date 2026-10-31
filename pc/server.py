"""Servidor da Segunda Tela (Windows).

Envia a tela do PC ao tablet como quadros JPEG e aplica os toques como cliques do mouse.
O painel (gui.py / SegundaTela.exe) usa este módulo; também roda direto pela linha de comando:

    pip install mss pillow dxcam av
    python server.py              # só USB, porta 7777, segunda tela (ou a principal)
    python server.py --wifi        # aceita conexões da rede

USB: com o tablet no cabo e a depuração USB ativa, o servidor faz o `adb reverse`
e abre o app no tablet sozinho. Wi-Fi: no app use o IP deste PC
(só em rede confiável: não há senha).
"""
import argparse
import ctypes
import ctypes.wintypes
import gc
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
from fractions import Fraction

import av
import mss
import numpy as np
from PIL import Image, ImageDraw

try:  # só para achar o número da saída DXGI do monitor (o ddagrab do FFmpeg pede esse número)
    from dxcam.core.device import Device
    from dxcam.core.output import Output
    from dxcam.util.io import enum_dxgi_adapters
except Exception:  # sem DXGI (ex.: área de trabalho remota): captura pela CPU
    enum_dxgi_adapters = None

# ação nos 4 bits de baixo (0 down, 1 move, 2 up, 3 quadro mostrado), dedo (0-9) nos 4 de cima; x, y em 0..1
EVENT = struct.Struct(">Bff")
HEADER = struct.Struct(">4sII")  # b"H264", largura, altura; depois [int32 tamanho][quadro H.264] repetido
FRAME_LEN = struct.Struct(">I")
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
APP = "com.meuapp.segundatela/.MainActivity"
ACK = 3
IN_FLIGHT = 3  # quadros a caminho do tablet; ida-e-volta ~40 ms, 3 dão folga para 60 FPS sem acumular atraso


def _arrow():
    """Seta do mouse (branca com borda preta) já em BGRA, e a máscara de onde pintar."""
    img = Image.new("RGBA", (22, 32))
    ImageDraw.Draw(img).polygon([(1, 1), (1, 26), (7, 20), (11, 30), (15, 28), (11, 19), (19, 19)],
                                fill="white", outline="black", width=2)
    a = np.array(img)
    return a[..., [2, 1, 0, 3]], a[..., 3] > 0


ARROW, ARROW_MASK = _arrow()


def dpi_aware():
    """Pixels reais, para o clique cair no lugar certo; relógio do Windows em 1 ms
    (no padrão de 15,6 ms a captura do FFmpeg não passa de ~47 quadros/s)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        ctypes.windll.winmm.timeBeginPeriod(1)
    except (AttributeError, OSError):
        pass


def to_screen(x, y, mon):
    """Converte coordenadas 0..1 em pixels do monitor."""
    return (mon["left"] + round(x * (mon["width"] - 1)),
            mon["top"] + round(y * (mon["height"] - 1)))


def pick_monitor(monitors, choice):
    """Índice no sct.monitors. choice 0 = automático: a primeira tela que não é a
    principal (a principal fica sempre em 0,0); sem segunda tela, a principal."""
    if choice:
        return min(choice, len(monitors) - 1)
    return next((i for i, m in enumerate(monitors) if i and (m["left"], m["top"]) != (0, 0)), 1)


def mouse(action, x, y, mon, pid=0):
    """Reserva para Windows sem injeção de toque: o dedo vira o mouse (só um dedo)."""
    if pid:
        return
    user32 = ctypes.windll.user32
    user32.SetCursorPos(*to_screen(x, y, mon))
    if action == 0:
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    elif action == 2:
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


class POINTER_INFO(ctypes.Structure):
    _fields_ = [("pointerType", ctypes.c_uint32), ("pointerId", ctypes.c_uint32), ("frameId", ctypes.c_uint32),
                ("pointerFlags", ctypes.c_uint32), ("sourceDevice", ctypes.c_void_p), ("hwndTarget", ctypes.c_void_p),
                ("ptPixelLocation", ctypes.wintypes.POINT), ("ptHimetricLocation", ctypes.wintypes.POINT),
                ("ptPixelLocationRaw", ctypes.wintypes.POINT), ("ptHimetricLocationRaw", ctypes.wintypes.POINT),
                ("dwTime", ctypes.c_uint32), ("historyCount", ctypes.c_uint32), ("InputData", ctypes.c_int32),
                ("dwKeyStates", ctypes.c_uint32), ("PerformanceCount", ctypes.c_uint64),
                ("ButtonChangeType", ctypes.c_int)]


class POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [("pointerInfo", POINTER_INFO), ("touchFlags", ctypes.c_uint32), ("touchMask", ctypes.c_uint32),
                ("rcContact", ctypes.wintypes.RECT), ("rcContactRaw", ctypes.wintypes.RECT),
                ("orientation", ctypes.c_uint32), ("pressure", ctypes.c_uint32)]


PT_TOUCH, TOUCH_MASK_CONTACTAREA = 2, 1
TOUCH_DOWN = 0x10000 | 0x2 | 0x4  # POINTER_FLAG_DOWN | INRANGE | INCONTACT
TOUCH_MOVE = 0x20000 | 0x2 | 0x4  # POINTER_FLAG_UPDATE | INRANGE | INCONTACT
TOUCH_UP = 0x40000  # POINTER_FLAG_UP


class Touch:
    """Toque de verdade no Windows (InjectTouchInput): o mouse do PC fica onde está e vale
    multitoque (pinça, rolar com dois dedos). Cada envio leva todos os dedos na tela."""

    def __init__(self):
        self.user32 = ctypes.windll.user32
        if not self.user32.InitializeTouchInjection(10, 1):  # até 10 dedos, com o círculo de toque
            raise OSError("injeção de toque indisponível")
        self.fingers = {}  # id do dedo -> (x, y) em pixels
        self.lock = threading.Lock()
        threading.Thread(target=self._hold, daemon=True).start()

    def __call__(self, action, x, y, mon, pid=0):
        with self.lock:
            new = pid not in self.fingers
            if new and action != 0:
                return  # movimento/soltura de um dedo que não encostou
            self.fingers[pid] = to_screen(x, y, mon)
            flag = TOUCH_UP if action == 2 else TOUCH_DOWN if new else TOUCH_MOVE
            self._send({pid: flag})
            if action == 2:
                del self.fingers[pid]

    def _send(self, flags):
        infos = (POINTER_TOUCH_INFO * len(self.fingers))()
        for info, (pid, (x, y)) in zip(infos, self.fingers.items()):
            p = info.pointerInfo
            p.pointerType, p.pointerId = PT_TOUCH, pid
            p.pointerFlags = flags.get(pid, TOUCH_MOVE)
            p.ptPixelLocation.x, p.ptPixelLocation.y = x, y
            info.touchMask = TOUCH_MASK_CONTACTAREA
            info.rcContact.left, info.rcContact.top, info.rcContact.right, info.rcContact.bottom = x - 2, y - 2, x + 2, y + 2
        self.user32.InjectTouchInput(len(infos), infos)

    def _hold(self):
        """Dedo parado também precisa ser reenviado, senão o Windows solta o toque sozinho."""
        while True:
            time.sleep(0.05)
            with self.lock:
                if self.fingers:
                    self._send({})


_touch = None


def touch(action, x, y, mon, pid=0):
    """Toque do tablet no PC: toque de verdade do Windows; sem isso, vira mouse."""
    global _touch
    if _touch is None:
        try:
            _touch = Touch()
        except OSError:
            _touch = mouse
    _touch(action, x, y, mon, pid)


class Flow:
    """O app confirma cada quadro desenhado (ação 3); o PC espera se já há IN_FLIGHT
    a caminho. App antigo nunca confirma: aí envia sem esperar, como antes."""

    def __init__(self):
        self.cond = threading.Condition()
        self.pending = 0
        self.on = False

    def before_send(self):
        with self.cond:
            if self.on:  # timeout: quadro perdido não trava a transmissão
                self.cond.wait_for(lambda: self.pending < IN_FLIGHT, timeout=1)
            self.pending += 1

    def ack(self):
        with self.cond:
            self.on = True
            self.pending = max(0, self.pending - 1)
            self.cond.notify()


def read_events(conn, mon, inject, flow, gone):
    f = conn.makefile("rb")
    try:
        while len(chunk := f.read(EVENT.size)) == EVENT.size:
            action, x, y = EVENT.unpack(chunk)
            kind, pid = action & 0x0F, action >> 4  # 4 bits de cima: qual dedo
            if kind == ACK:
                flow.ack()
            else:
                inject(kind, x, y, mon, pid)
    except OSError:
        pass
    finally:
        gone.set()  # tablet desconectou


def dxgi_output(mon):
    """Número da saída DXGI (placa de vídeo principal) que é este monitor, achada pela posição."""
    # ponytail: só a primeira placa de vídeo (é a que o ddagrab usa); notebook com 2 GPUs pode precisar escolher.
    dev = Device(enum_dxgi_adapters()[0])
    for i, p in enumerate(dev.enum_outputs()):
        out = Output(p)
        out.update_desc()
        r = out.desc.DesktopCoordinates
        if (r.left, r.top, r.right - r.left, r.bottom - r.top) == (mon["left"], mon["top"], mon["width"], mon["height"]):
            return i
    raise RuntimeError("monitor não encontrado na placa de vídeo")


def gpu_capture(mon, size, fps):
    """Captura toda na placa de vídeo: ddagrab (já desenha o mouse) e Quick Sync convertendo
    para NV12 no tamanho do vídeo. Devolve (grafo, saída); saída.pull() espera o próximo quadro."""
    if not enum_dxgi_adapters:
        raise RuntimeError("DXGI indisponível")
    g = av.filter.Graph()
    prev = g.add("ddagrab", f"output_idx={dxgi_output(mon)}:framerate={fps}:draw_mouse=1")
    for name, args in (("hwmap", "derive_device=qsv"), ("vpp_qsv", f"w={size[0]}:h={size[1]}:format=nv12"),
                       ("hwdownload", None), ("format", "nv12")):
        f = g.add(name, args)
        prev.link_to(f)
        prev = f
    sink = g.add("buffersink")
    prev.link_to(sink)
    g.configure()
    return g, sink


def cursor_pos():
    p = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def video_size(mon, max_width):
    """Tamanho do vídeo: até max_width de largura, sempre par (exigência do H.264 4:2:0)."""
    w = min(mon["width"], max_width)
    return w & ~1, round(mon["height"] * w / mon["width"]) & ~1


def to_frame(arr, pos, mon, size):
    """Quadro BGRA -> YUV para o codificador, com a seta do mouse (a captura não traz o mouse).
    Pinta a seta no próprio arr e desfaz depois: copiar a tela inteira custaria mais."""
    x, y = pos[0] - mon["left"], pos[1] - mon["top"]
    h, w = arr.shape[:2]
    view = patch = None
    if 0 <= x < w and 0 <= y < h:
        view = arr[y:y + ARROW.shape[0], x:x + ARROW.shape[1]]
        patch = view.copy()
        m = ARROW_MASK[:view.shape[0], :view.shape[1]]
        view[m] = ARROW[:view.shape[0], :view.shape[1]][m]
    frame = av.VideoFrame.from_ndarray(arr, format="bgra").reformat(width=size[0], height=size[1], format="yuv420p")
    if view is not None:
        view[...] = patch
    return frame


def h264(size, quality, fps, pix_fmt="yuv420p"):
    """Codificador x264 para tela: sem espera entre quadros (zerolatency), sem quadros B,
    tamanho de cada quadro limitado (vbv) para nenhum travar o cabo."""
    c = av.CodecContext.create("libx264", "w")
    c.width, c.height = size
    c.pix_fmt = pix_fmt
    c.time_base = Fraction(1, fps)
    c.framerate = fps
    crf = max(12, min(40, round(51 - quality * 0.4)))  # Qualidade 70 -> crf 23
    c.options = {"preset": "ultrafast", "tune": "zerolatency", "crf": str(crf),
                 "x264-params": "keyint=600:scenecut=0:repeat-headers=1:vbv-maxrate=40000:vbv-bufsize=1500"}
    c.open()
    return c


def send_video(conn, frames, cfg, flow, size):
    """Thread que codifica e envia; a captura segue em paralelo (os dois juntos não cabem em 16 ms)."""
    enc, quality, n = None, None, 0
    try:
        while (frame := frames.get()) is not None:
            if cfg["quality"] != quality:  # Qualidade mudou no painel: recomeça o vídeo com o novo nível
                quality = cfg["quality"]
                enc = h264(size, quality, 60, frame.format.name)
            frame.pts = n
            n += 1
            data = b"".join(bytes(p) for p in enc.encode(frame))
            if data:
                flow.before_send()
                conn.sendall(FRAME_LEN.pack(len(data)) + data)
    except OSError:
        pass


def latest(q, item):
    """Põe item na fila de 1 lugar, trocando um quadro antigo ainda não codificado."""
    try:
        q.get_nowait()
    except queue.Empty:
        pass
    q.put(item)


def serve(srv, cfg, inject=touch, log=lambda event, detail="": print("tablet", event, detail),
          stop=None, once=False):
    """Atende um tablet por vez. cfg é lido a cada quadro (qualidade e FPS mudam ao vivo).

    Para parar: stop.set() e srv.close().
    """
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            conn, addr = srv.accept()
        except TimeoutError:
            continue
        except OSError:
            return
        log("conectado", addr[0])
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        virtual = cfg["monitor"] == 0 and cfg.get("virtual")
        if virtual:  # o monitor do tablet só existe enquanto o tablet está conectado
            log("info", "Ligando o monitor do tablet…")
            if not virtual_monitor(True):
                log("aviso", "O monitor do tablet não ligou (use o botão 'Ativar monitor do tablet'); enviando a tela principal")
        try:
            stream(conn, cfg, inject, log, stop)
        finally:
            if virtual:
                virtual_monitor(False)
        log("desconectado", addr[0])
        if once:
            return


def open_capture(mon, size, fps, log, attempts=10):
    """Captura pela placa de vídeo, tentando por até 2 s (a captura anterior pode estar saindo,
    ou o Windows pode estar trocando o modo da tela). (None, None) = usar a CPU por enquanto."""
    for attempt in range(attempts):
        try:
            return gpu_capture(mon, size, fps)
        except Exception as e:
            err = e
            time.sleep(0.2)
    if attempts > 1:
        log("aviso", f"Captura pela placa de vídeo falhou ({err}); usando a CPU até ela voltar")
    return None, None


def stream(conn, cfg, inject, log, stop):
    """Envia o vídeo a um tablet conectado até ele sair (ou stop)."""
    with conn, mss.mss() as sct:  # mss precisa ser usado na mesma thread que o criou
        i = pick_monitor(sct.monitors, cfg["monitor"])
        mon = sct.monitors[i]
        log("monitor", f"{i}: {mon['width']}x{mon['height']}")
        # Tamanho do vídeo fixo na conexão; se a resolução do monitor mudar, a placa reescala para ele.
        size = video_size(mon, cfg["max_width"])
        graph, sink = open_capture(mon, size, cfg["fps"], log)
        retry = time.monotonic() + 2
        flow, gone, frames = Flow(), threading.Event(), queue.Queue(maxsize=1)
        threading.Thread(target=read_events, args=(conn, mon, inject, flow, gone), daemon=True).start()
        sender = threading.Thread(target=send_video, args=(conn, frames, cfg, flow, size), daemon=True)
        try:
            conn.sendall(HEADER.pack(b"H264", *size))
            sender.start()
            while not stop.is_set() and not gone.is_set() and sender.is_alive():
                if sink:
                    try:
                        latest(frames, sink.pull())  # espera o próximo quadro da placa (no ritmo do FPS)
                        continue
                    except av.error.FFmpegError:  # tela mudou (resolução, janela de administrador,
                        graph = sink = None       # bloqueio): o Windows corta a captura; retoma
                        gc.collect()
                        with mss.mss() as s:  # posição/tamanho novos do monitor (o toque usa o mesmo mon)
                            mon.update(s.monitors[pick_monitor(s.monitors, cfg["monitor"])])
                        graph, sink = open_capture(mon, size, cfg["fps"], log)
                        retry = time.monotonic() + 2
                        continue
                if time.monotonic() > retry:  # na CPU: tenta voltar para a placa de vídeo
                    retry = time.monotonic() + 2
                    graph, sink = open_capture(mon, size, cfg["fps"], log, attempts=1)
                    if sink:
                        continue
                start = time.perf_counter()
                latest(frames, to_frame(np.array(sct.grab(mon)), cursor_pos(), mon, size))
                time.sleep(max(0.0, 1 / cfg["fps"] - (time.perf_counter() - start)))
        except (OSError, av.error.FFmpegError):
            pass
        finally:
            latest(frames, None)
            graph = sink = None  # solta a captura da tela já: o grafo do FFmpeg tem referência
            gc.collect()  # circular e, sem isso, segura a tela até a próxima coleta de lixo


# Tarefas do Windows criadas uma vez (com administrador) pelo setup-monitor.ps1:
# ligam/desligam o dispositivo "Virtual Display Driver" sem pedir senha a cada uso.
TASKS = {True: r"\SegundaTela\LigarMonitor", False: r"\SegundaTela\DesligarMonitor"}


def virtual_monitor(on, wait=10):
    """Liga/desliga o monitor virtual do tablet. Ao ligar, espera o Windows estender a área de
    trabalho para ele (se o Windows escolher espelhar ou só uma tela, força o modo Estender)."""
    try:
        r = subprocess.run(["schtasks", "/run", "/tn", TASKS[on]], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    if r.returncode != 0 or not on:
        return r.returncode == 0
    for t in range(wait * 4):
        with mss.mss() as s:
            if len(s.monitors) > 2:
                if size := tablet_size(None):
                    set_virtual_resolution(*size)
                return True
        if t == 12:  # 3 s e ainda uma tela só: Windows ligou em espelho ou "só segunda tela"
            subprocess.run(["DisplaySwitch.exe", "/extend"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        time.sleep(0.25)
    return False


class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32), ("DeviceName", ctypes.c_wchar * 32), ("DeviceString", ctypes.c_wchar * 128),
                ("StateFlags", ctypes.c_uint32), ("DeviceID", ctypes.c_wchar * 128), ("DeviceKey", ctypes.c_wchar * 128)]


class DEVMODE(ctypes.Structure):
    _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", ctypes.c_uint16),
                ("dmDriverVersion", ctypes.c_uint16), ("dmSize", ctypes.c_uint16), ("dmDriverExtra", ctypes.c_uint16),
                ("dmFields", ctypes.c_uint32), ("x", ctypes.c_long), ("y", ctypes.c_long),
                ("dmDisplayOrientation", ctypes.c_uint32), ("dmDisplayFixedOutput", ctypes.c_uint32),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                ("dmLogPixels", ctypes.c_uint16), ("dmBitsPerPel", ctypes.c_uint32), ("width", ctypes.c_uint32),
                ("height", ctypes.c_uint32), ("dmDisplayFlags", ctypes.c_uint32), ("hz", ctypes.c_uint32)]


def set_virtual_resolution(w, h):
    """Põe o monitor virtual na resolução do tablet a 60 Hz (o Windows guarda para as próximas vezes)."""
    user32 = ctypes.windll.user32
    for i in range(32):
        d = DISPLAY_DEVICE(cb=ctypes.sizeof(DISPLAY_DEVICE))
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
            return False
        if d.DeviceString == "Virtual Display Driver" and d.StateFlags & 1:  # 1 = ligado na área de trabalho
            m = DEVMODE(dmSize=ctypes.sizeof(DEVMODE))
            user32.EnumDisplaySettingsW(d.DeviceName, -1, ctypes.byref(m))
            if (m.width, m.height, m.hz) == (w, h, 60):
                return True
            m.width, m.height, m.hz = w, h, 60
            m.dmFields = 0x80000 | 0x100000 | 0x400000  # largura, altura, frequência
            return user32.ChangeDisplaySettingsExW(d.DeviceName, ctypes.byref(m), None, 1, None) == 0
    return False


def virtual_ready():
    """O monitor do tablet já foi ativado (tarefas liga/desliga criadas pelo setup-monitor.ps1)."""
    try:
        return subprocess.run(["schtasks", "/query", "/tn", TASKS[True]], capture_output=True, timeout=20,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def tablet_size(default=(1920, 1080)):
    """Resolução do tablet deitado, lida pelo cabo (adb); sem tablet no cabo, default."""
    ok, out = adb("shell", "wm", "size")
    m = re.search(r"Physical size: (\d+)x(\d+)", out) if ok else None
    if not m:
        return default
    a, b = int(m[1]), int(m[2])
    return max(a, b), min(a, b)


def setup_virtual(script, size):
    """Roda a ativação única do monitor do tablet como administrador (o Windows pede confirmação).
    Espera terminar; True se deu certo."""
    w, h = size
    cmd = (f"$p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList "
           f"'-NoProfile','-ExecutionPolicy','Bypass','-File','\"{script}\"','-Width','{w}','-Height','{h}'; "
           "exit $p.ExitCode")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=900,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and virtual_ready()


def find_adb():
    """adb no PATH, no Android SDK ou o baixado pelo instalar.ps1."""
    for adb in (shutil.which("adb"), os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\SegundaTela\platform-tools\adb.exe")):
        if adb and os.path.exists(adb):
            return adb
    return None


def adb(*args):
    exe = find_adb()
    if not exe:
        return False, "adb não encontrado (instale o Android Platform Tools)"
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def open_on_tablet(port):
    """Liga a porta pelo cabo e abre o app no tablet já conectando."""
    ok, out = adb("reverse", f"tcp:{port}", f"tcp:{port}")
    if not ok:
        return False, out or "sem tablet no cabo"
    ok, out = adb("shell", "am", "start", "-S", "-n", APP,
                  "--es", "host", "127.0.0.1", "--ei", "port", str(port), "--ez", "auto", "true")
    return ok and "Error" not in out, out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--monitor", type=int, default=0, help="0 = automático (a tela que não é a principal)")
    ap.add_argument("--quality", type=int, default=70, help="JPEG 1-95")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--max-width", type=int, default=2000)
    ap.add_argument("--wifi", action="store_true",
                    help="aceita conexões da rede (qualquer um na rede pode ver a tela e clicar)")
    a = ap.parse_args()
    dpi_aware()
    # Padrão só USB (localhost via adb reverse); --wifi abre para a rede.
    host = "0.0.0.0" if a.wifi else "127.0.0.1"
    srv = socket.create_server((host, a.port))
    print(f"aguardando tablet em {host}:{a.port}...")
    if not a.wifi:
        print("USB:", open_on_tablet(a.port)[1] or "ok")
    serve(srv, {"monitor": a.monitor, "quality": a.quality, "fps": a.fps, "max_width": a.max_width})


if __name__ == "__main__":
    main()
