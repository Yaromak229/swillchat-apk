"""
SWILL SECURE CHAT — Android клиент (Kivy)
Замени SERVER_HOST на адрес твоего Railway сервера!
"""

import socket
import threading
import json
import base64
import hashlib
import pyaudio
import audioop
import time

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# =============================================
#  ⚙️  НАСТРОЙКИ — ИЗМЕНИ SERVER_HOST!
# =============================================
SERVER_HOST = "ВАШ_АДРЕС.railway.app"   # ← сюда вставить адрес Railway
SERVER_PORT = 5000

# Тот же ключ что и на сервере
SECRET_KEY = hashlib.sha256(b"SwillChatSecretKey2024").digest()

# Цвета
BG       = (0.07, 0.07, 0.10, 1)
DARK     = (0.11, 0.11, 0.16, 1)
ACCENT   = (0.18, 0.52, 1.00, 1)
SUCCESS  = (0.13, 0.77, 0.37, 1)
DANGER   = (0.90, 0.26, 0.21, 1)
TEXT     = (1,    1,    1,    1)
SUBTEXT  = (0.6,  0.6,  0.7,  1)
MSG_OWN  = (0.18, 0.52, 1.00, 1)
MSG_IN   = (0.18, 0.20, 0.27, 1)

# =============================================
#  ШИФРОВАНИЕ
# =============================================
def encrypt(text: str) -> str:
    cipher = AES.new(SECRET_KEY, AES.MODE_CBC)
    ct = cipher.encrypt(pad(text.encode(), AES.block_size))
    return base64.b64encode(cipher.iv + ct).decode()

def decrypt(data: str) -> str:
    raw = base64.b64decode(data)
    iv, ct = raw[:16], raw[16:]
    cipher = AES.new(SECRET_KEY, AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(ct), AES.block_size).decode()

# =============================================
#  ГОЛОСОВОЙ ЗВОНОК (UDP peer-to-peer)
# =============================================
class VoiceCall:
    CHUNK  = 1024
    RATE   = 16000
    FORMAT = pyaudio.paInt16

    def __init__(self, is_caller, target_ip, target_port, local_port):
        self.is_caller   = is_caller
        self.target_ip   = target_ip
        self.target_port = target_port
        self.local_port  = local_port
        self.running     = False
        self.pa          = None
        self.udp         = None

    def start(self):
        try:
            self.pa  = pyaudio.PyAudio()
            self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp.bind(("0.0.0.0", self.local_port))
            self.udp.settimeout(0.5)
            self.running = True

            threading.Thread(target=self._send_audio,  daemon=True).start()
            threading.Thread(target=self._recv_audio,  daemon=True).start()
            return "✅ Звонок начат"
        except Exception as e:
            return f"❌ Ошибка звонка: {e}"

    def _send_audio(self):
        stream = self.pa.open(format=self.FORMAT, channels=1,
                               rate=self.RATE, input=True,
                               frames_per_buffer=self.CHUNK)
        while self.running:
            try:
                data = stream.read(self.CHUNK, exception_on_overflow=False)
                data = audioop.lin2ulaw(data, 2)        # сжатие
                self.udp.sendto(data, (self.target_ip, self.target_port))
            except:
                pass
        stream.stop_stream()
        stream.close()

    def _recv_audio(self):
        stream = self.pa.open(format=self.FORMAT, channels=1,
                               rate=self.RATE, output=True,
                               frames_per_buffer=self.CHUNK)
        while self.running:
            try:
                data, _ = self.udp.recvfrom(4096)
                data = audioop.ulaw2lin(data, 2)        # распаковка
                stream.write(data)
            except socket.timeout:
                pass
            except:
                pass
        stream.stop_stream()
        stream.close()

    def stop(self):
        self.running = False
        time.sleep(0.3)
        if self.udp:
            self.udp.close()
        if self.pa:
            self.pa.terminate()

# =============================================
#  СЕТЕВОЙ КЛИЕНТ
# =============================================
class ChatClient:
    def __init__(self, on_event):
        self.on_event = on_event
        self.sock     = None
        self.running  = False
        self._buf     = ""

    def connect(self, name) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(8)
            self.sock.connect((SERVER_HOST, SERVER_PORT))
            self.sock.settimeout(None)
            self._send({"type": "register", "name": name})
            self.running = True
            threading.Thread(target=self._recv_loop, daemon=True).start()
            return True
        except Exception as e:
            print(f"[connect error] {e}")
            return False

    def _send(self, obj):
        try:
            raw = json.dumps(obj)
            enc = encrypt(raw)
            self.sock.send((enc + "\n").encode())
        except Exception as e:
            print(f"[send error] {e}")

    def send(self, obj):
        self._send(obj)

    def _recv_loop(self):
        while self.running:
            try:
                chunk = self.sock.recv(4096).decode()
                if not chunk:
                    break
                self._buf += chunk
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(decrypt(line))
                        Clock.schedule_once(lambda dt, m=msg: self.on_event(m), 0)
                    except Exception as e:
                        print(f"[decrypt error] {e}")
            except Exception as e:
                print(f"[recv error] {e}")
                break
        self.running = False
        Clock.schedule_once(lambda dt: self.on_event({"type": "disconnected"}), 0)

    def disconnect(self):
        self.running = False
        if self.sock:
            try: self.sock.close()
            except: pass


# =============================================
#  HELPER: красивая кнопка
# =============================================
def make_button(text, color=ACCENT, height=48, font_size="15sp"):
    btn = Button(
        text=text,
        size_hint_y=None,
        height=height,
        font_size=font_size,
        background_normal="",
        background_color=color,
        color=TEXT,
        bold=True,
    )
    return btn


# =============================================
#  ЭКРАН ПОДКЛЮЧЕНИЯ
# =============================================
class ConnectScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

        root = BoxLayout(orientation="vertical", padding=40, spacing=20)

        # Заголовок
        root.add_widget(Label(text="🔐 Swill Chat", font_size="28sp",
                              bold=True, color=ACCENT, size_hint_y=None, height=60))
        root.add_widget(Label(text="Безопасный мессенджер", font_size="14sp",
                              color=SUBTEXT, size_hint_y=None, height=30))
        root.add_widget(Label())  # spacer

        # Поле имени
        root.add_widget(Label(text="Ваше имя:", color=TEXT, size_hint_y=None,
                              height=28, halign="left"))
        self.name_input = TextInput(
            hint_text="Введите имя...",
            multiline=False,
            size_hint_y=None, height=48,
            background_color=DARK,
            foreground_color=TEXT,
            cursor_color=ACCENT,
            font_size="16sp",
        )
        root.add_widget(self.name_input)

        self.status = Label(text="", color=DANGER, size_hint_y=None, height=30)
        root.add_widget(self.status)

        btn = make_button("Войти →", color=ACCENT, height=54, font_size="17sp")
        btn.bind(on_press=self.do_connect)
        root.add_widget(btn)

        root.add_widget(Label())  # spacer
        root.add_widget(Label(text=f"Сервер: {SERVER_HOST}:{SERVER_PORT}",
                              color=SUBTEXT, font_size="11sp", size_hint_y=None, height=20))

        self.add_widget(root)

    def _upd(self, *a):
        self._bg.pos  = self.pos
        self._bg.size = self.size

    def do_connect(self, *a):
        name = self.name_input.text.strip()
        if not name:
            self.status.text = "Введите имя!"
            return
        self.status.text = "Подключение..."
        self.status.color = SUBTEXT
        app = App.get_running_app()
        app.do_connect(name, self.status)


# =============================================
#  ЭКРАН КОНТАКТОВ
# =============================================
class ContactsScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

        root = BoxLayout(orientation="vertical")

        # Header
        header = BoxLayout(size_hint_y=None, height=56, padding=(16, 8),
                           spacing=10)
        with header.canvas.before:
            Color(*DARK)
            self._hbg = Rectangle(pos=header.pos, size=header.size)
        header.bind(pos=lambda *a: setattr(self._hbg, "pos", header.pos),
                    size=lambda *a: setattr(self._hbg, "size", header.size))

        self.title_lbl = Label(text="💬 Контакты", font_size="18sp",
                               bold=True, color=TEXT)
        disc_btn = make_button("Выйти", color=DANGER, height=36, font_size="13sp")
        disc_btn.size_hint_x = None
        disc_btn.width = 80
        disc_btn.bind(on_press=lambda *a: App.get_running_app().disconnect())
        header.add_widget(self.title_lbl)
        header.add_widget(disc_btn)
        root.add_widget(header)

        # Список контактов
        scroll = ScrollView()
        self.contacts_layout = GridLayout(cols=1, spacing=4, padding=(10, 10),
                                          size_hint_y=None)
        self.contacts_layout.bind(minimum_height=self.contacts_layout.setter("height"))
        scroll.add_widget(self.contacts_layout)
        root.add_widget(scroll)

        self.add_widget(root)

    def _upd(self, *a):
        self._bg.pos  = self.pos
        self._bg.size = self.size

    def update_contacts(self, users: list, my_id: str):
        self.contacts_layout.clear_widgets()
        others = [u for u in users if u != my_id]
        if not others:
            self.contacts_layout.add_widget(
                Label(text="Пока никого нет онлайн…", color=SUBTEXT,
                      size_hint_y=None, height=40))
            return
        for user in others:
            btn = Button(
                text=f"👤  {user}",
                size_hint_y=None, height=52,
                font_size="16sp",
                background_normal="",
                background_color=DARK,
                color=TEXT,
                halign="left",
            )
            btn.bind(on_press=lambda b, u=user: App.get_running_app().open_chat(u))
            self.contacts_layout.add_widget(btn)


# =============================================
#  ЭКРАН ЧАТА
# =============================================
class ChatScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

        root = BoxLayout(orientation="vertical")

        # Header
        header = BoxLayout(size_hint_y=None, height=56, padding=(10, 8), spacing=10)
        with header.canvas.before:
            Color(*DARK)
            self._hbg = Rectangle(pos=header.pos, size=header.size)
        header.bind(pos=lambda *a: setattr(self._hbg, "pos", header.pos),
                    size=lambda *a: setattr(self._hbg, "size", header.size))

        back_btn = make_button("←", color=(0.2,0.2,0.3,1), height=38, font_size="18sp")
        back_btn.size_hint_x = None
        back_btn.width = 44
        back_btn.bind(on_press=lambda *a: App.get_running_app().go_contacts())

        self.chat_title = Label(text="Чат", font_size="17sp", bold=True, color=TEXT)

        call_btn = make_button("📞", color=SUCCESS, height=38, font_size="18sp")
        call_btn.size_hint_x = None
        call_btn.width = 48
        call_btn.bind(on_press=lambda *a: App.get_running_app().start_call())

        header.add_widget(back_btn)
        header.add_widget(self.chat_title)
        header.add_widget(call_btn)
        root.add_widget(header)

        # Сообщения
        scroll = ScrollView()
        self.msgs_layout = GridLayout(cols=1, spacing=6, padding=(10, 10),
                                      size_hint_y=None)
        self.msgs_layout.bind(minimum_height=self.msgs_layout.setter("height"))
        scroll.add_widget(self.msgs_layout)
        self.chat_scroll = scroll
        root.add_widget(scroll)

        # Ввод
        input_bar = BoxLayout(size_hint_y=None, height=56, padding=(8, 6), spacing=8)
        with input_bar.canvas.before:
            Color(*DARK)
            self._ibg = Rectangle(pos=input_bar.pos, size=input_bar.size)
        input_bar.bind(pos=lambda *a: setattr(self._ibg, "pos", input_bar.pos),
                       size=lambda *a: setattr(self._ibg, "size", input_bar.size))

        self.msg_input = TextInput(
            hint_text="Сообщение...",
            multiline=False,
            background_color=(0.16, 0.16, 0.22, 1),
            foreground_color=TEXT,
            cursor_color=ACCENT,
            font_size="15sp",
        )
        send_btn = make_button("➤", color=ACCENT, height=42, font_size="20sp")
        send_btn.size_hint_x = None
        send_btn.width = 52
        send_btn.bind(on_press=self.send_message)
        self.msg_input.bind(on_text_validate=self.send_message)

        input_bar.add_widget(self.msg_input)
        input_bar.add_widget(send_btn)
        root.add_widget(input_bar)

        self.add_widget(root)

    def _upd(self, *a):
        self._bg.pos  = self.pos
        self._bg.size = self.size

    def send_message(self, *a):
        text = self.msg_input.text.strip()
        if not text:
            return
        App.get_running_app().send_message(text)
        self.msg_input.text = ""

    def add_message(self, text, own=False, system=False):
        if system:
            lbl = Label(text=text, color=SUBTEXT, size_hint_y=None,
                        font_size="12sp", halign="center")
            lbl.bind(width=lambda l, w: setattr(l, "text_size", (w, None)))
            lbl.bind(texture_size=lambda l, s: setattr(l, "height", s[1] + 8))
        else:
            col   = MSG_OWN if own else MSG_IN
            align = "right" if own else "left"
            lbl   = Label(text=text, color=TEXT if not own else TEXT,
                          size_hint_y=None, font_size="14sp",
                          halign=align, padding=(10, 6))
            with lbl.canvas.before:
                Color(*col)
                lbl._rect = RoundedRectangle(pos=lbl.pos, size=lbl.size, radius=[10])
            lbl.bind(pos=lambda l, *a: setattr(l._rect, "pos", l.pos))
            lbl.bind(size=lambda l, *a: setattr(l._rect, "size", l.size))
            lbl.bind(width=lambda l, w: setattr(l, "text_size", (w * 0.85, None)))
            lbl.bind(texture_size=lambda l, s: setattr(l, "height", s[1] + 14))

        self.msgs_layout.add_widget(lbl)
        Clock.schedule_once(lambda dt: setattr(self.chat_scroll, "scroll_y", 0), 0.05)

    def clear_messages(self):
        self.msgs_layout.clear_widgets()


# =============================================
#  ГЛАВНОЕ ПРИЛОЖЕНИЕ
# =============================================
class SwillChatApp(App):
    def build(self):
        Window.clearcolor = BG
        self.client       = None
        self.my_id        = ""
        self.current_peer = ""
        self.current_call = None
        self._call_local_port = 0

        self.sm = ScreenManager()
        self.connect_screen  = ConnectScreen(name="connect")
        self.contacts_screen = ContactsScreen(name="contacts")
        self.chat_screen     = ChatScreen(name="chat")

        self.sm.add_widget(self.connect_screen)
        self.sm.add_widget(self.contacts_screen)
        self.sm.add_widget(self.chat_screen)
        return self.sm

    # ---------- подключение ----------
    def do_connect(self, name, status_lbl):
        def _try():
            self.client = ChatClient(self.on_event)
            ok = self.client.connect(name)
            if ok:
                self.my_id = name
            else:
                Clock.schedule_once(lambda dt: setattr(status_lbl, "text",
                    "❌ Нет соединения с сервером"), 0)
                Clock.schedule_once(lambda dt: setattr(status_lbl, "color", DANGER), 0)
        threading.Thread(target=_try, daemon=True).start()

    def disconnect(self):
        if self.current_call:
            self.current_call.stop()
            self.current_call = None
        if self.client:
            self.client.disconnect()
            self.client = None
        self.sm.current = "connect"

    # ---------- навигация ----------
    def open_chat(self, peer):
        self.current_peer = peer
        self.chat_screen.chat_title.text = f"💬 {peer}"
        self.chat_screen.clear_messages()
        self.sm.current = "chat"

    def go_contacts(self):
        self.sm.current = "contacts"

    # ---------- отправка сообщения ----------
    def send_message(self, text):
        if not self.client or not self.current_peer:
            return
        self.client.send({"type": "message", "to": self.current_peer, "text": text})
        self.chat_screen.add_message(f"Вы: {text}", own=True)

    # ---------- звонки ----------
    def start_call(self):
        if not self.current_peer:
            return
        import random
        self._call_local_port = random.randint(50000, 59999)
        self.client.send({
            "type": "call_request",
            "to": self.current_peer,
            "caller_port": self._call_local_port,
        })
        self.chat_screen.add_message("📞 Вызов…", system=True)

    def _answer_call(self, msg, accepted):
        import random
        if accepted:
            local_port = random.randint(50000, 59999)
            self.client.send({
                "type": "call_response",
                "to": msg["from"],
                "accepted": True,
                "callee_port": local_port,
            })
            # Принимающий слушает на local_port, шлёт на caller_port
            self.current_call = VoiceCall(
                is_caller=False,
                target_ip=msg["caller_ip"],
                target_port=msg["caller_port"],
                local_port=local_port,
            )
            status = self.current_call.start()
            self.chat_screen.add_message(f"🎙️ {status}", system=True)
        else:
            self.client.send({"type": "call_response", "to": msg["from"],
                              "accepted": False})

    # ---------- события сервера ----------
    def on_event(self, msg):
        t = msg.get("type")

        if t == "registered":
            self.contacts_screen.title_lbl.text = f"💬 {self.my_id}"
            self.sm.current = "contacts"

        elif t == "error":
            self.connect_screen.status.text = msg.get("text", "Ошибка")
            self.connect_screen.status.color = DANGER

        elif t == "users":
            self.contacts_screen.update_contacts(msg["list"], self.my_id)

        elif t == "message":
            sender = msg["from"]
            text   = msg["text"]
            # Если открыт чат с этим человеком
            if self.sm.current == "chat" and self.current_peer == sender:
                self.chat_screen.add_message(f"{sender}: {text}", own=False)
            else:
                # Всплывающее уведомление
                self._notify(sender, text)

        elif t == "call_request":
            from_user = msg["from"]
            layout = BoxLayout(orientation="vertical", padding=10, spacing=10)
            layout.add_widget(Label(text=f"📞 Звонок от {from_user}",
                                    color=TEXT, font_size="16sp"))
            btns = BoxLayout(spacing=10, size_hint_y=None, height=48)
            ans = make_button("Ответить", color=SUCCESS)
            dec = make_button("Отклонить", color=DANGER)
            btns.add_widget(ans)
            btns.add_widget(dec)
            layout.add_widget(btns)
            popup = Popup(title="Входящий звонок",
                          content=layout, size_hint=(0.8, 0.35))
            ans.bind(on_press=lambda *a: [self._answer_call(msg, True), popup.dismiss()])
            dec.bind(on_press=lambda *a: [self._answer_call(msg, False), popup.dismiss()])
            popup.open()

        elif t == "call_response":
            if msg.get("accepted"):
                callee_ip   = msg["callee_ip"]
                callee_port = msg["callee_port"]
                self.current_call = VoiceCall(
                    is_caller=True,
                    target_ip=callee_ip,
                    target_port=callee_port,
                    local_port=self._call_local_port,
                )
                status = self.current_call.start()
                self.chat_screen.add_message(f"🎙️ {status}", system=True)
            else:
                self.chat_screen.add_message("❌ Звонок отклонён", system=True)

        elif t == "disconnected":
            self.sm.current = "connect"

    def _notify(self, sender, text):
        layout = BoxLayout(orientation="vertical", padding=10)
        layout.add_widget(Label(text=f"Сообщение от {sender}:\n{text}",
                                color=TEXT))
        btn = make_button("OK", color=ACCENT, height=40)
        layout.add_widget(btn)
        popup = Popup(title="Новое сообщение", content=layout, size_hint=(0.75, 0.3))
        btn.bind(on_press=popup.dismiss)
        popup.open()


if __name__ == "__main__":
    SwillChatApp().run()
