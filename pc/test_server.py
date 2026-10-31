"""Teste: um cliente falso recebe o vídeo H.264 (e decodifica) e envia um toque."""
import socket
import struct
import threading
import time

import av
import numpy as np

import server


def test():
    assert server.to_screen(1, 1, {"left": 0, "top": 0, "width": 1920, "height": 1080}) == (1919, 1079)

    main = {"left": 0, "top": 0, "width": 1920, "height": 1080}
    extra = {"left": 1920, "top": 0, "width": 2000, "height": 1200}
    assert server.pick_monitor([{}, main, extra], 0) == 2  # automático: a que não é a principal
    assert server.pick_monitor([{}, main], 0) == 1  # só uma tela: espelha
    assert server.pick_monitor([{}, main, extra], 1) == 1  # escolha manual
    assert server.pick_monitor([{}, main], 5) == 1  # monitor que sumiu

    mon = {"left": 1920, "top": 0, "width": 100, "height": 100}
    assert server.video_size(mon, 2000) == (100, 100)
    assert server.video_size({"width": 1366, "height": 769}, 640) == (640, 360)
    arr = np.zeros((100, 100, 4), np.uint8)
    rgb = server.to_frame(arr, (1950, 10), mon, (100, 100)).to_ndarray(format="rgb24")
    assert rgb[18, 33].min() > 200, "seta do mouse não desenhada"
    assert not arr.any(), "a seta deve sair do quadro original depois de codificar"
    rgb = server.to_frame(arr, (5, 5), mon, (100, 100)).to_ndarray(format="rgb24")
    assert rgb.max() < 40, "mouse fora do monitor não deve aparecer"

    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    got = []
    cfg = {"monitor": 1, "quality": 50, "fps": 30, "max_width": 640}
    threading.Thread(target=server.serve, args=(srv, cfg),
                     kwargs={"inject": lambda a, x, y, m, p: got.append((a, p, x, y)), "once": True},
                     daemon=True).start()

    c = socket.create_connection(("127.0.0.1", port))
    c.settimeout(10)
    f = c.makefile("rb")
    magic, w, h = server.HEADER.unpack(f.read(server.HEADER.size))
    assert magic == b"H264" and w == 640 and w % 2 == h % 2 == 0, (magic, w, h)
    n = struct.unpack(">I", f.read(4))[0]
    frames = av.CodecContext.create("h264", "r").decode(av.Packet(f.read(n)))
    assert frames and (frames[0].width, frames[0].height) == (w, h), "primeiro quadro não decodifica"

    c.sendall(server.EVENT.pack(server.ACK, 0, 0))  # confirmação de quadro não vira clique
    c.sendall(server.EVENT.pack(0, 0.5, 0.25))
    c.sendall(server.EVENT.pack(2 << 4 | 1, 0.75, 0.5))  # segundo dedo (id 2) se mexendo
    for _ in range(50):
        if len(got) == 2:
            break
        time.sleep(0.05)
    assert got == [(0, 0, 0.5, 0.25), (1, 2, 0.75, 0.5)], got
    c.close()

    # Parar: stop + close encerra serve mesmo sem tablet conectado.
    srv2 = socket.create_server(("127.0.0.1", 0))
    srv2.settimeout(0.2)
    stop = threading.Event()
    t = threading.Thread(target=server.serve, args=(srv2, cfg), kwargs={"stop": stop}, daemon=True)
    t.start()
    stop.set()
    srv2.close()
    t.join(2)
    assert not t.is_alive(), "serve não parou"
    print("ok")


if __name__ == "__main__":
    test()
