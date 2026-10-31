"""Segunda Tela: painel do PC.

Escolha USB ou Wi-Fi, o monitor e a qualidade, e clique em Iniciar.
No modo USB o app abre sozinho no tablet.
"""
import json
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from tkinter import ttk

import mss
from PIL import Image, ImageTk

import server

BG, CARD, FIELD, FG, MUTED, ACCENT = "#0B0D1A", "#151833", "#262A4D", "#F1F5F9", "#94A3B8", "#22D3EE"
STATUS = {
    "parado": ("#64748B", "Parado"),
    "aguardando": ("#F59E0B", "Aguardando o tablet…"),
    "conectado": ("#22C55E", "Conectado"),
    "erro": ("#EF4444", "Erro"),
}
CONFIG = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SegundaTela", "config.json")
# monitor 0 = automático (a tela que não é a principal, ex.: o monitor virtual do tablet)
DEFAULTS = {"mode": "usb", "monitor": 0, "quality": 70, "fps": 60, "max_width": 2000, "port": 7777}
FONT = "Segoe UI"


def resource(name):
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), name)


def lan_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # UDP não envia nada aqui; só escolhe a interface
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def is_main(m):
    return (m["left"], m["top"]) == (0, 0)


def monitor_names(mons):
    """Opções do combobox; o índice é o mesmo do sct.monitors (0 = automático)."""
    return ["Automático (segunda tela)"] + [
        f"{i}: {m['width']}x{m['height']}" + (" (principal)" if is_main(m) else "")
        for i, m in enumerate(mons) if i]


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return {**DEFAULTS, **json.load(f)}
    except (OSError, ValueError):
        return dict(DEFAULTS)


class App:
    def __init__(self, root):
        self.root, self.cfg = root, load_config()
        self.events = queue.Queue()
        self.srv = self.stop = None
        with mss.mss() as s:
            self.mons = s.monitors
        self.cfg["monitor"] = max(0, min(int(self.cfg["monitor"]), len(self.mons) - 1))

        root.title("Segunda Tela")
        root.configure(bg=BG, padx=24, pady=20)
        root.resizable(False, False)
        try:
            root.iconbitmap(resource("icon.ico"))
        except tk.TclError:
            pass
        self.style()

        # Cabeçalho: ícone, nome e status
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x")
        self.logo = ImageTk.PhotoImage(Image.open(resource("icon.png")).resize((56, 56), Image.LANCZOS))
        tk.Label(head, image=self.logo, bg=BG).pack(side="left")
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left", padx=12)
        tk.Label(titles, text="Segunda Tela", bg=BG, fg=FG, font=(FONT + " Semibold", 20)).pack(anchor="w")
        line = tk.Frame(titles, bg=BG)
        line.pack(anchor="w")
        self.dot = tk.Canvas(line, width=12, height=12, bg=BG, highlightthickness=0)
        self.dot_id = self.dot.create_oval(1, 1, 11, 11, outline="")
        self.dot.pack(side="left")
        self.status = tk.Label(line, bg=BG, fg=MUTED, font=(FONT, 11))
        self.status.pack(side="left", padx=6)

        # Cartão de ajustes
        card = tk.Frame(root, bg=CARD, padx=20, pady=16, highlightthickness=1, highlightbackground=FIELD)
        card.pack(fill="x", pady=(16, 12))
        card.columnconfigure(1, weight=1)

        def label(row, text):
            tk.Label(card, text=text, bg=CARD, fg=FG, font=(FONT, 11)).grid(
                row=row, column=0, sticky="w", pady=8, padx=(0, 16))

        label(0, "Conexão")
        modes = tk.Frame(card, bg=CARD)
        modes.grid(row=0, column=1, columnspan=2, sticky="w")
        self.mode = tk.StringVar(value=self.cfg["mode"])
        self.radios = [ttk.Radiobutton(modes, text=t, value=v, variable=self.mode, command=self.update_hint)
                       for t, v in (("USB (cabo)", "usb"), ("Wi-Fi", "wifi"))]
        for r in self.radios:
            r.pack(side="left", padx=(0, 16))
        self.hint = tk.Label(card, bg=CARD, fg=MUTED, font=(FONT, 10), justify="left", wraplength=400)
        self.hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))

        label(2, "Monitor")
        self.monitor = ttk.Combobox(card, values=monitor_names(self.mons), state="readonly", width=26,
                                    postcommand=self.refresh_monitors)
        self.monitor.current(self.cfg["monitor"])
        self.monitor.grid(row=2, column=1, columnspan=2, sticky="w")
        self.monitor.bind("<<ComboboxSelected>>", lambda e: self.show_target())
        self.target = tk.Label(card, bg=CARD, fg=ACCENT, font=(FONT, 10), justify="left", wraplength=320)
        self.target.grid(row=3, column=1, columnspan=2, sticky="w")

        for row, (key, text, lo, hi) in enumerate((("quality", "Qualidade", 30, 95), ("fps", "FPS", 5, 60)), 4):
            label(row, text)
            value = tk.Label(card, text=self.cfg[key], bg=CARD, fg=ACCENT, width=3, font=(FONT + " Semibold", 11))
            value.grid(row=row, column=2, sticky="e", padx=(8, 0))
            ttk.Scale(card, from_=lo, to=hi, value=self.cfg[key], length=260,
                      command=lambda v, k=key, l=value: self.slide(k, l, v)).grid(row=row, column=1, sticky="we")

        # Ativação única do monitor do tablet (some quando já está ativado)
        self.setup_btn = ttk.Button(root, text="Ativar monitor do tablet (só na primeira vez)",
                                    style="Setup.TButton", command=self.setup)
        if not server.virtual_ready():
            self.setup_btn.pack(fill="x", pady=(0, 10))

        self.button = ttk.Button(root, text="Iniciar", style="Accent.TButton", command=self.toggle)
        self.button.pack(fill="x")

        self.set_status("parado")
        self.update_hint()
        self.show_target()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll()

    def style(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure("TRadiobutton", background=CARD, foreground=FG, font=(FONT, 11), indicatorcolor=FIELD,
                     indicatorbackground=FIELD)
        st.map("TRadiobutton", background=[("active", CARD)], indicatorcolor=[("selected", ACCENT)],
               foreground=[("disabled", MUTED)])
        st.configure("Horizontal.TScale", background=ACCENT, troughcolor=FIELD, bordercolor=CARD,
                     lightcolor=ACCENT, darkcolor=ACCENT)
        st.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG, arrowcolor=FG,
                     bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD)
        st.map("TCombobox", fieldbackground=[("readonly", FIELD), ("disabled", CARD)],
               foreground=[("readonly", FG), ("disabled", MUTED)],
               selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)])
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", BG)
        st.configure("Accent.TButton", background=ACCENT, foreground=BG, font=(FONT + " Semibold", 13),
                     padding=12, borderwidth=0, focuscolor=ACCENT)
        st.map("Accent.TButton", background=[("active", "#67E8F9")])
        st.configure("Setup.TButton", background=FIELD, foreground=FG, font=(FONT + " Semibold", 11),
                     padding=10, borderwidth=0, focuscolor=FIELD)
        st.map("Setup.TButton", background=[("active", "#33386A"), ("disabled", CARD)],
               foreground=[("disabled", MUTED)])

    def setup(self):
        """Instala/configura o monitor virtual (uma janela de administrador do Windows)."""
        self.setup_btn.state(["disabled"])
        self.target.config(text="Ativando… confirme a janela do Windows (clique em Sim). "
                                "Na primeira vez baixa o driver (~70 MB).")

        def run():
            self.events.put(("setup", server.setup_virtual(resource("setup-monitor.ps1"), server.tablet_size())))
        threading.Thread(target=run, daemon=True).start()

    def slide(self, key, label, value):
        self.cfg[key] = int(float(value))  # o servidor lê a cada quadro: muda ao vivo
        label.config(text=self.cfg[key])

    def set_status(self, key, extra=""):
        color, text = STATUS[key]
        self.dot.itemconfig(self.dot_id, fill=color)
        self.status.config(text=f"{text} {extra}".strip())

    def refresh_monitors(self):
        """Relê as telas (o monitor virtual pode aparecer depois que o painel abriu)."""
        idx = max(0, self.monitor.current())
        with mss.mss() as s:
            self.mons = s.monitors
        self.monitor.config(values=monitor_names(self.mons))
        self.monitor.current(min(idx, len(self.mons) - 1))
        self.show_target()

    def show_target(self, sending=None):
        """Mostra qual monitor vai para o tablet (ou está indo, quando conectado)."""
        if sending:
            return self.target.config(text=f"Enviando o monitor {sending}")
        choice = max(0, self.monitor.current())
        i = server.pick_monitor(self.mons, choice)
        m = self.mons[i]
        if choice == 0 and is_main(m):
            text = "Vai enviar o monitor do tablet (ele só liga quando o tablet conectar)"
        else:
            text = f"Vai enviar o monitor {i}: {m['width']}x{m['height']}"
            if is_main(m):
                text += " (a tela principal: o tablet fica espelhado)"
        self.target.config(text=text)

    def update_hint(self):
        if self.mode.get() == "wifi":
            text = (f"No tablet, escolha Wi-Fi e digite o IP {lan_ip()} (porta {self.cfg['port']}). "
                    "Use só em rede confiável: quem estiver na rede pode ver sua tela e clicar.")
        else:
            text = "Ligue o tablet no cabo com a depuração USB ativa. Ao iniciar, o app abre sozinho no tablet."
        self.hint.config(text=text)

    def lock(self, running):
        for r in self.radios:
            r.state(["disabled"] if running else ["!disabled"])
        self.monitor.config(state="disabled" if running else "readonly")
        self.button.config(text="Parar" if running else "Iniciar")

    def toggle(self):
        if self.srv:
            return self.stop_server()
        self.cfg.update(mode=self.mode.get(), monitor=max(0, self.monitor.current()), virtual=True)
        host = "0.0.0.0" if self.cfg["mode"] == "wifi" else "127.0.0.1"
        try:
            self.srv = socket.create_server((host, self.cfg["port"]))
        except OSError:
            return self.set_status("erro", f"(porta {self.cfg['port']} ocupada?)")
        self.srv.settimeout(0.5)
        self.stop = threading.Event()
        threading.Thread(target=server.serve, args=(self.srv, self.cfg), daemon=True,
                         kwargs={"log": lambda e, d="": self.events.put((e, d)), "stop": self.stop}).start()
        self.save()
        self.lock(True)
        self.set_status("aguardando")
        if self.cfg["mode"] == "usb":
            port = self.cfg["port"]
            threading.Thread(target=lambda: self.events.put(("adb", server.open_on_tablet(port))),
                             daemon=True).start()

    def stop_server(self):
        self.stop.set()
        self.srv.close()
        self.srv = None
        self.lock(False)
        self.set_status("parado")
        self.update_hint()
        self.refresh_monitors()

    def poll(self):
        while not self.events.empty():
            event, detail = self.events.get()
            if event == "conectado":
                self.set_status("conectado", f"({detail})")
            elif event == "monitor":
                self.show_target(detail)
            elif event in ("info", "aviso"):
                self.target.config(text=detail)
            elif event == "setup":
                if detail:
                    self.setup_btn.pack_forget()
                    self.refresh_monitors()
                    self.target.config(text="Monitor do tablet ativado: ele liga sozinho quando o tablet conectar.")
                else:
                    self.setup_btn.state(["!disabled"])
                    self.target.config(text="Não ativou. Detalhes em C:\\ProgramData\\SegundaTela\\setup.log")
            elif event == "desconectado" and self.srv:
                self.set_status("aguardando")
                self.refresh_monitors()
            elif event == "adb":
                ok, msg = detail
                self.hint.config(text="App aberto no tablet." if ok else f"Não achei o tablet no cabo: {msg[:160]}")
        self.root.after(200, self.poll)

    def save(self):
        try:
            os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump({k: self.cfg[k] for k in DEFAULTS}, f, indent=2)
        except OSError:
            pass  # ajustes só não ficam salvos

    def close(self):
        if self.srv:
            self.stop_server()
        server.virtual_monitor(False)  # nunca deixa o monitor do tablet ligado sem o app
        self.cfg["mode"] = self.mode.get()
        self.save()
        self.root.destroy()


if __name__ == "__main__":
    server.dpi_aware()
    server.virtual_monitor(False)  # sobra de uma sessão que não fechou direito
    root = tk.Tk()
    App(root)
    root.mainloop()
