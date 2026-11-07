import ctypes
import tkinter as tk
import threading
import time
import os
import struct
import re
import winreg
import subprocess
from pynput import keyboard, mouse
from pynput.keyboard import Controller as KBController, Key
from pynput.mouse import Controller as MouseController, Button

# Библиотеки для патчера
try:
    import vdf
    import requests
    HAS_PATCHER_DEPS = True
except ImportError:
    HAS_PATCHER_DEPS = False

# ===== OCR OFF: библиотеки зрения и OCR временно отключены =====
# Раскомментируй блок ниже, чтобы вернуть OCR.
# try:
#     import mss
#     import numpy as np
#     import cv2
#     import pytesseract
#     HAS_OCR = True
# except ImportError:
#     HAS_OCR = False
HAS_OCR = False  # OCR OFF

try:
    from PIL import Image, ImageTk, ImageEnhance
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

keyboard_ctrl = KBController()
mouse_ctrl = MouseController()

_last_tornado_time = None
RESUME_TIMEOUT = 15.0
_current_auto_level = 1
_current_auto_quas = 1

# ================= КОНСТАНТЫ ДЛЯ ПАТЧЕРА =================
DOTA_APP_ID = "570"
DEFAULT_SEARCH_HEX_STRING = "00 00 00 00 00 00 2E 40 00 00 96 44 00 00 E1 44"
SERVER_SEARCH_HEX_STRING_LINK = "https://raw.githubusercontent.com/searayeah/dota-camera-distance/main/current_hex_string"
DEFAULT_DISTANCE = "1200"
STEAM_REGISTRY_KEY = "SOFTWARE\\WOW6432Node\\Valve\\Steam"
CLIENT_DLL_PATH = "\\steamapps\\common\\dota 2 beta\\game\\dota\\bin\\win64\\client.dll"
LIBRARY_FOLDERS_PATH = "\\steamapps\\libraryfolders.vdf"

BINDABLE_COMBOS = [
    "WWE R alt+D", "EEW R D", "QQQ R D", "QWE R D", "WWW R D",
    "QEE R D", "QQW R D", "QQE R D", "EEE R D", "QWW R D",
    "EEQ R D", "EEE R alt+D"
]

def set_distance(search_hex_string, distance, client_dll_path):
    search_hex_string = search_hex_string.lower().replace(" ", "").strip()
    default_distance_hex = struct.pack("f", float(DEFAULT_DISTANCE)).hex()
    distance_hex = struct.pack("f", float(distance)).hex()

    distance_hex_length = len(distance_hex)
    distance_index = search_hex_string.find(default_distance_hex)

    if distance_index == -1:
        raise Exception("Не удалось найти стандартную дистанцию в HEX-строке.")

    search_hex_string_regex = re.compile(
        search_hex_string[:distance_index]
        + f"\\w{{{distance_hex_length}}}"
        + search_hex_string[distance_index + distance_hex_length :]
    )

    distance_hex_string = (
        search_hex_string[:distance_index]
        + distance_hex
        + search_hex_string[distance_index + distance_hex_length :]
    )

    with open(client_dll_path, "rb") as f:
        client_dll_hex = f.read().hex()

    client_dll_hex_new, changes_count = re.subn(
        search_hex_string_regex, distance_hex_string, client_dll_hex, 1
    )

    if changes_count == 0:
        raise Exception("Не удалось найти HEX-значение в client.dll. Возможно, файл уже пропатчен или изменился после обновления.")

    with open(client_dll_path, "wb") as f:
        f.write(bytes.fromhex(client_dll_hex_new))

def get_steam_path():
    hkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, STEAM_REGISTRY_KEY)
    steam_path = winreg.QueryValueEx(hkey, "InstallPath")[0]
    winreg.CloseKey(hkey)
    return steam_path

def get_steam_library_path(steam_path):
    library_folders = vdf.load(open(steam_path + LIBRARY_FOLDERS_PATH, encoding='utf-8'))["libraryfolders"]
    for key in library_folders:
        if str(DOTA_APP_ID) in library_folders[key]["apps"]:
            return library_folders[key]["path"]
    return None

def get_current_hex_string():
    try:
        response = requests.get(SERVER_SEARCH_HEX_STRING_LINK, timeout=5)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException:
        return DEFAULT_SEARCH_HEX_STRING

# ================= ОСНОВНОЙ КОД =================

def level_delay(lvl: int) -> float:
    d = 7.0 - (lvl * 0.3)
    if lvl >= 6: d -= 0.3
    if lvl >= 12: d -= 0.3
    if lvl >= 18: d -= 0.3
    return max(0.0, d)

def tornado_delay(n: int) -> float:
    return 1.0 + n * 0.2

KEY_MAP = {
    "alt": Key.alt, "ctrl": Key.ctrl, "shift": Key.shift,
    "space": Key.space, "enter": Key.enter, "tab": Key.tab,
}

ALL_COMBOS = {
    "WWE R alt+D": {"keys": ["w", "w", "e", "r", ("alt", "d")], "icon": "Alacrity_icon"},
    "EEW R D": {"keys": ["e", "e", "w", "r", "d"], "icon": "Chaos_Meteor_icon"},
    "QQQ R D": {"keys": ["q", "q", "q", "r", "d"], "icon": "Cold_Snap_icon"},
    "QWE R D": {"keys": ["q", "w", "e", "r", "d"], "icon": "Deafening_Blast_icon"},
    "WWW R D": {"keys": ["w", "w", "w", "r", "d"], "icon": "Emp_icon"},
    "QEE R D": {"keys": ["q", "e", "e", "r", "d"], "icon": "Forge_Spirit_icon"},
    "QQW R D": {"keys": ["q", "q", "w", "r", "d"], "icon": "Ghost_Walk_icon"},
    "QQE R D": {"keys": ["q", "q", "e", "r", "d"], "icon": "Ice_Wall_icon"},
    "EEE R D": {"keys": ["e", "e", "e", "r", "d"], "icon": "Sun_Strike_icon"},
    "QWW R D": {"keys": ["q", "w", "w", "r", "d"], "icon": "Tornado_icon"},
    "C":       {"keys": ["c"], "icon": "Refresher_icon"},
    "EEE R alt+D": {"keys": ["e", "e", "e", "r", ("alt", "d")], "icon": "Kataklizm_icon"},
    "3":       {"keys": ["3"], "icon": "Glepnir_icon"},
    "EEQ R D": {"keys": ["e", "e", "q", "r", "d"], "icon": "Chaos_Meteor_icon"},
}

TABS_DATA = {
    "1": ["QQE R D", "QEE R D", "WWE R alt+D"],
    "2": ["QQQ R D", "QQE R D", "QEE R D", "QWE R D"],
    "3": ["QWW R D", "EEE R D", "EEW R D", "QWE R D"],
    "4": ["WWE R alt+D", "3", "EEE R alt+D", "EEW R D", "QWE R D", "QEE R D", "QQQ R D"],
    "5": ["WWE R alt+D","QWW R D", "EEE R alt+D", "WWW R D", "EEW R D", "QWE R D", "QQE R D", "C", "EEE R alt+D", "EEW R D", "QWE R D", "WWW R D", "EEQ R D", "QQE R D", "WWE R alt+D", "QQQ R D"]
}

def press_key(k):
    if isinstance(k, tuple):
        mod, key = k
        keyboard_ctrl.press(KEY_MAP.get(mod, mod))
        time.sleep(0.03)
        keyboard_ctrl.press(KEY_MAP.get(key, key))
        time.sleep(0.02)
        keyboard_ctrl.release(KEY_MAP.get(key, key))
        keyboard_ctrl.release(KEY_MAP.get(mod, mod))
    else:
        key_obj = KEY_MAP.get(k, k)
        keyboard_ctrl.press(key_obj)
        time.sleep(0.02)
        keyboard_ctrl.release(key_obj)

def smart_sleep(seconds, stop_event):
    end = time.time() + seconds
    while time.time() < end:
        if stop_event.is_set(): return False
        time.sleep(min(0.05, max(0.001, end - time.time())))
    return True

def run_combo(keys, delay_after, stop_event):
    last_key_time = None
    n = len(keys)
    for j, k in enumerate(keys):
        if stop_event.is_set():
            return 'keys_interrupted', last_key_time
        press_key(k)
        last_key_time = time.time()
        if j < n - 1:
            if not smart_sleep(0.07, stop_event):
                return 'keys_interrupted', last_key_time
    if not smart_sleep(delay_after, stop_event):
        return 'delay_interrupted', last_key_time
    return 'done', last_key_time

def run_section(section_name, lvl, tornado_d, stop_event, start_index=0):
    global _last_tornado_time
    delay = level_delay(lvl)
    combos = TABS_DATA.get(section_name, [])
    i = start_index

    if i > 0 and i - 1 < len(combos) and combos[i - 1] == "QWW R D" and _last_tornado_time is not None:
        torn_d = tornado_d
        if i < len(combos) and combos[i] in ("EEE R D", "EEE R alt+D"):
            torn_d -= 1.6
        required = max(delay, torn_d)

        elapsed = time.time() - _last_tornado_time
        wait = required - elapsed
        if wait > 0:
            if not smart_sleep(wait, stop_event):
                return i, False

    while i < len(combos):
        if stop_event.is_set():
            return i, False
        combo_name = combos[i]
        if combo_name not in ALL_COMBOS:
            i += 1
            continue

        post_delay = delay
        if combo_name == "QWW R D":
            torn_d = tornado_d
            if i + 1 < len(combos) and combos[i + 1] in ("EEE R D", "EEE R alt+D"):
                torn_d -= 1.8
            post_delay = max(delay, torn_d)

        status, last_t = run_combo(ALL_COMBOS[combo_name]["keys"], post_delay, stop_event)

        if combo_name == "QWW R D" and status in ('delay_interrupted', 'done') and last_t is not None:
            _last_tornado_time = last_t

        if status == 'keys_interrupted':
            return i, False
        if status == 'delay_interrupted':
            return i + 1, False
        i += 1

    return i, True

# ================= СЛОВАРИ ЯЗЫКОВ И ТЕМ =================
TRANSLATIONS = {
    "Русский": {
        "title": "Invoker Combo", "settings": "Настройки",
        "bind": "BIND", "lvl": "lvl:", "tornado": "TORNADO:",
        "tab_ability": "1. Бинды способностей", "tab_cam": "2. Отдаление камеры",
        "tab_creep": "3. Крипстоп", "tab_armlet": "4. Абуз армлета",
        "tab_heal": "5. Авто-хил", "tab_settings": "6. Настройки",
        "ability_title": "Бинды способностей", "ability_hint": "ЛКМ по кнопке — забиндить. ПКМ — сброс.\nЛКМ/ПКМ при бинде — отмена.",
        "cam_title": "Отдаление камеры", "cam_warn": "ВАЖНО: Dota 2 должна быть закрыта!",
        "cam_dist": "Дистанция (рекомендуемо 1600):", "cam_btn": "Пропатчить и Запустить Dota",
        "cam_ready": "Готово к запуску", "cam_copy": "Скопировать (Ctrl+V в игре)",
        "dev": "Эта функция находится на доработке.",
        "lang_lbl": "Язык:", "theme_lbl": "Тема:"
    },
    "Українська": {
        "title": "Invoker Combo", "settings": "Налаштування",
        "bind": "BIND", "lvl": "lvl:", "tornado": "TORNADO:",
        "tab_ability": "1. Бінди здібностей", "tab_cam": "2. Віддалення камери",
        "tab_creep": "3. Крипстоп", "tab_armlet": "4. Абуз армлету",
        "tab_heal": "5. Авто-хіл", "tab_settings": "6. Налаштування",
        "ability_title": "Бінди здібностей", "ability_hint": "ЛКМ по кнопці — забиндити. ПКМ — скинути.\nЛКМ/ПКМ при бінді — скасувати.",
        "cam_title": "Віддалення камери", "cam_warn": "ВАЖЛИВО: Dota 2 має бути закрита!",
        "cam_dist": "Дистанція (рекомендовано 1600):", "cam_btn": "Пропатчити та Запустити Dota",
        "cam_ready": "Готово до запуску", "cam_copy": "Скопіювати (Ctrl+V у грі)",
        "dev": "Ця функція знаходиться в розробці.",
        "lang_lbl": "Мова:", "theme_lbl": "Тема:"
    },
    "English": {
        "title": "Invoker Combo", "settings": "Settings",
        "bind": "BIND", "lvl": "lvl:", "tornado": "TORNADO:",
        "tab_ability": "1. Ability Binds", "tab_cam": "2. Camera Distance",
        "tab_creep": "3. Creep Stop", "tab_armlet": "4. Armlet Abuse",
        "tab_heal": "5. Auto Heal", "tab_settings": "6. Settings",
        "ability_title": "Ability Binds", "ability_hint": "LMB to bind. RMB to reset.\nLMB/RMB while binding - cancel.",
        "cam_title": "Camera Distance", "cam_warn": "WARNING: Dota 2 must be closed!",
        "cam_dist": "Distance (recommended 1600):", "cam_btn": "Patch and Launch Dota",
        "cam_ready": "Ready to launch", "cam_copy": "Copy (Ctrl+V in game)",
        "dev": "This feature is under development.",
        "lang_lbl": "Language:", "theme_lbl": "Theme:"
    }
}

THEMES = {
    "Чёрный-Красный": {"bg": "#121212", "panel": "#1a1a1a", "text": "#aaaaaa", "accent": "#ff4545", "btn": "#1e1e1e", "btn_dark": "#333333"},
    "Чёрный-Белый":   {"bg": "#000000", "panel": "#111111", "text": "#ffffff", "accent": "#ffffff", "btn": "#222222", "btn_dark": "#444444"},
    "Серый-Чёрный":   {"bg": "#333333", "panel": "#444444", "text": "#dddddd", "accent": "#000000", "btn": "#222222", "btn_dark": "#555555"}
}

class App:
    def __init__(self, root):
        self.root = root
        self.stop_event = threading.Event()
        self.worker = None
        self.auto_threads_running = True

        self.binding_mode = False
        self.bind_ready_time = 0
        self.bound_key = None
        self.bound_key_pressed = False
        self.combo_running = False

        self.ability_binds = {}
        self.ability_bind_btns = {}
        self.current_binding_target = None
        self.ability_bind_mode = False

        self.section_index = 0
        self.last_release_time = None

        self.drag_data = None
        self.drag_win = None
        self.show_inventory = False
        self.is_pinned = True

        self.icon_cache = {}
        self.dark_icon_cache = {}
        self.bind_icon_cache = {}
        self.ICON_SIZE = (32, 32)

        root.title("Invoker Combo Builder")
        root.resizable(False, False)
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        self.current_section = tk.StringVar(value="1")

        self.lang_var = tk.StringVar(value="Русский")
        self.theme_var = tk.StringVar(value="Чёрный-Красный")

        self.lang_var.trace_add("write", lambda *a: self.apply_language())
        self.theme_var.trace_add("write", lambda *a: self.apply_theme())

        # ================= КАСТОМНЫЙ TITLE BAR =================
        self.title_bar = tk.Frame(root, height=20)
        self.title_bar.pack(fill="x", side="top")
        self.title_bar.pack_propagate(False)

        self.icon_lbl = tk.Label(self.title_bar, text="🪶", font=("Segoe UI", 8))
        self.icon_lbl.pack(side="left", padx=(4, 2))

        self.title_lbl = tk.Label(self.title_bar, text="Invoker Combo", font=("Segoe UI", 8))
        self.title_lbl.pack(side="left")

        self.close_btn = tk.Label(self.title_bar, text="✕", font=("Segoe UI", 8, "bold"), cursor="hand2")
        self.close_btn.pack(side="right", padx=4)
        self.close_btn.bind("<Button-1>", lambda e: self.root.destroy())

        self.min_btn = tk.Label(self.title_bar, text="—", font=("Segoe UI", 8, "bold"), cursor="hand2")
        self.min_btn.pack(side="right", padx=2)
        self.min_btn.bind("<Button-1>", self.minimize_window)

        self.pin_btn = tk.Label(self.title_bar, text="📌", font=("Segoe UI", 8), cursor="hand2")
        self.pin_btn.pack(side="right", padx=2)
        self.pin_btn.bind("<Button-1>", self.toggle_pin)

        self.title_bar.bind("<ButtonPress-1>", self.start_window_move)
        self.title_bar.bind("<B1-Motion>", self.move_window)

        # ================= ВЕРХНЯЯ ПАНЕЛЬ =================
        self.top_bar = tk.Frame(root)
        self.top_bar.pack(fill="x", padx=3, pady=2)

        self.gear_btn = tk.Button(self.top_bar, text="⚙", font=("Segoe UI", 9), bd=0, relief="flat", command=self.toggle_inventory)
        self.gear_btn.pack(side="left")

        self.menu_btn = tk.Button(self.top_bar, text="☰", font=("Segoe UI", 10, "bold"), bd=0, relief="flat", command=self.open_large_window)
        self.menu_btn.pack(side="left", padx=(2, 0))

        self.tabs_frame = tk.Frame(self.top_bar)
        self.tabs_frame.pack(side="left", padx=2)

        self.tab_buttons = {}
        for name in ["1", "2", "3", "4", "5"]:
            btn = tk.Button(self.tabs_frame, text=name, width=2, font=("Segoe UI", 7, "bold"), bd=0, relief="flat", command=lambda n=name: self.switch_tab(n))
            btn.pack(side="left", padx=1)
            self.tab_buttons[name] = btn

        self.bind_btn = tk.Button(self.top_bar, text="BIND", width=5, font=("Segoe UI", 7, "bold"), bd=0, relief="flat")
        self.bind_btn.pack(side="right", padx=(1, 0))
        self.bind_btn.bind("<Button-1>", self.on_bind_click)
        self.bind_btn.bind("<Button-3>", self.on_unbind_click)

        self.clear_btn = tk.Button(self.top_bar, text="X", width=1, font=("Segoe UI", 7, "bold"), bd=0, relief="flat", command=self.on_unbind_click)
        self.clear_btn.pack(side="right")

        # ================= ИНВЕНТАРЬ =================
        self.inventory_frame = tk.Frame(root, bd=1, relief="solid")
        self.inv_label = tk.Label(self.inventory_frame, text="Available Combos (Drag to Add)", font=("Segoe UI", 7))
        self.inv_label.pack(pady=1)
        self.inv_grid = tk.Frame(self.inventory_frame)
        self.inv_grid.pack(pady=1)

        # ================= РАБОЧАЯ ОБЛАСТЬ =================
        self.workspace_outer = tk.Frame(root)
        self.workspace_outer.pack(fill="x", expand=False, padx=3, pady=2)
        self.workspace_frame = tk.Frame(self.workspace_outer)
        self.workspace_frame.pack(fill="x", expand=False)

        # ================= НИЖНЯЯ ПАНЕЛЬ =================
        self.bottom_frame = tk.Frame(root)
        self.bottom_frame.pack(fill="x", padx=4, pady=(0, 3), side="bottom")

        self.lvl_lbl_title = tk.Label(self.bottom_frame, text="lvl:", font=("Segoe UI", 7))
        self.lvl_lbl_title.pack(side="left")
        self.lvl_var = tk.IntVar(value=1)
        self.lvl_var.trace_add("write", lambda *a: self._update_lvl_label())
        self.lvl_spinbox = tk.Spinbox(self.bottom_frame, from_=1, to=30, width=2, textvariable=self.lvl_var, bd=0, relief="flat", font=("Segoe UI", 7))
        self.lvl_spinbox.pack(side="left", padx=2)
        self.lvl_label = tk.Label(self.bottom_frame, text=f"({level_delay(1):.1f}s)", font=("Segoe UI", 7))
        self.lvl_label.pack(side="left")

        self.tornado_lbl_title = tk.Label(self.bottom_frame, text="TORNADO:", font=("Segoe UI", 7))
        self.tornado_lbl_title.pack(side="left", padx=(8, 0))
        self.tornado_var = tk.IntVar(value=1)
        self.tornado_var.trace_add("write", lambda *a: self._update_tornado_label())
        self.tornado_spinbox = tk.Spinbox(self.bottom_frame, from_=1, to=9, width=2, textvariable=self.tornado_var, bd=0, relief="flat", font=("Segoe UI", 7))
        self.tornado_spinbox.pack(side="left", padx=2)
        self.tornado_label = tk.Label(self.bottom_frame, text=f"({tornado_delay(1):.1f}s)", font=("Segoe UI", 7))
        self.tornado_label.pack(side="left")

        self.switch_tab("1")
        self.root.bind("<B1-Motion>", self.on_drag)
        self.root.bind("<ButtonRelease-1>", self.stop_drag)

        self.kb_listener = keyboard.Listener(on_press=self.on_keyboard_press, on_release=self.on_keyboard_release)
        self.kb_listener.daemon = True
        self.kb_listener.start()

        self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
        self.mouse_listener.daemon = True
        self.mouse_listener.start()

        # ===== OCR OFF: авто-уровень и авто-Quas отключены =====
        # if HAS_OCR:
        #     threading.Thread(target=self.auto_level_loop, daemon=True).start()
        #     threading.Thread(target=self.auto_quas_loop, daemon=True).start()

        self.apply_theme()
        self.apply_language()

    # ================= БОЛЬШОЕ ОКНО С РАЗДЕЛАМИ =================
    def open_large_window(self):
        if hasattr(self, 'large_window') and self.large_window.winfo_exists():
            self.large_window.lift()
            return

        self.large_window = tk.Toplevel(self.root)
        self.large_window.overrideredirect(True)
        self.large_window.geometry(f"650x380+{self.root.winfo_x()-200}+{self.root.winfo_y()-250}")

        self.settings_title_bar = tk.Frame(self.large_window, height=24)
        self.settings_title_bar.pack(fill="x", side="top")
        self.settings_title_bar.pack_propagate(False)

        self.settings_icon = tk.Label(self.settings_title_bar, text="🪶", font=("Segoe UI", 9))
        self.settings_icon.pack(side="left", padx=(6, 2))

        self.settings_title = tk.Label(self.settings_title_bar, text="Настройки", font=("Segoe UI", 9))
        self.settings_title.pack(side="left")

        self.settings_close = tk.Label(self.settings_title_bar, text="✕", font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.settings_close.pack(side="right", padx=6)
        self.settings_close.bind("<Button-1>", lambda e: self.large_window.destroy())

        def start_move(event):
            self.large_window._drag_x = event.x
            self.large_window._drag_y = event.y

        def do_move(event):
            x = self.large_window.winfo_x() - self.large_window._drag_x + event.x
            y = self.large_window.winfo_y() - self.large_window._drag_y + event.y
            self.large_window.geometry(f"+{x}+{y}")

        self.settings_title_bar.bind("<ButtonPress-1>", start_move)
        self.settings_title_bar.bind("<B1-Motion>", do_move)
        self.settings_icon.bind("<ButtonPress-1>", start_move)
        self.settings_icon.bind("<B1-Motion>", do_move)
        self.settings_title.bind("<ButtonPress-1>", start_move)
        self.settings_title.bind("<B1-Motion>", do_move)

        self.main_container = tk.Frame(self.large_window)
        self.main_container.pack(fill="both", expand=True)

        self.content_frame = tk.Frame(self.main_container)
        self.content_frame.pack(side="right", fill="both", expand=True)

        self.sidebar = tk.Frame(self.main_container, width=210)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.btn_tab1 = tk.Button(self.sidebar, text="1. Бинды", bd=0, relief="flat", anchor="w", padx=10, pady=5, command=lambda: self.show_section("ability_binds"))
        self.btn_tab1.pack(fill="x", pady=(10, 2))
        self.btn_tab2 = tk.Button(self.sidebar, text="2. Камера", bd=0, relief="flat", anchor="w", padx=10, pady=5, command=lambda: self.show_section("camera"))
        self.btn_tab2.pack(fill="x", pady=2)
        self.btn_tab3 = tk.Button(self.sidebar, text="3. Крипстоп", bd=0, relief="flat", anchor="w", padx=10, pady=5, command=lambda: self.show_section("creepstop"))
        self.btn_tab3.pack(fill="x", pady=2)
        self.btn_tab4 = tk.Button(self.sidebar, text="4. Армлет", bd=0, relief="flat", anchor="w", padx=10, pady=5, command=lambda: self.show_section("armlet"))
        self.btn_tab4.pack(fill="x", pady=2)
        self.btn_tab5 = tk.Button(self.sidebar, text="5. Авто-хил", bd=0, relief="flat", anchor="w", padx=10, pady=5, command=lambda: self.show_section("autoheal"))
        self.btn_tab5.pack(fill="x", pady=2)
        self.btn_tab6 = tk.Button(self.sidebar, text="6. Настройки", bd=0, relief="flat", anchor="w", padx=10, pady=5, command=lambda: self.show_section("settings"))
        self.btn_tab6.pack(fill="x", pady=2)

        self.frames = {}

        # --- Раздел 1 ---
        self.frames["ability_binds"] = tk.Frame(self.content_frame)
        self.lbl_ability_title = tk.Label(self.frames["ability_binds"], text="Бинды", font=("Segoe UI", 11, "bold"))
        self.lbl_ability_title.pack(pady=(10, 2))
        self.lbl_ability_hint = tk.Label(self.frames["ability_binds"], text="ЛКМ по кнопке — забиндить. ПКМ — сброс.\nЛКМ/ПКМ при бинде — отмена.", font=("Segoe UI", 8), justify="center")
        self.lbl_ability_hint.pack(pady=(0, 10))

        self.grid_frame = tk.Frame(self.frames["ability_binds"])
        self.grid_frame.pack(padx=10, pady=5, fill="both", expand=True)
        row, col = 0, 0
        for combo in BINDABLE_COMBOS:
            icon = self.get_bind_icon(ALL_COMBOS[combo]["icon"])
            if icon:
                btn = tk.Button(self.grid_frame, text=combo, image=icon, compound="left", anchor="w", width=145, font=("Segoe UI", 8))
            else:
                btn = tk.Button(self.grid_frame, text=combo, width=15, font=("Segoe UI", 8))

            btn.grid(row=row, column=col, padx=2, pady=2)
            btn.bind("<Button-1>", lambda e, c=combo: self.on_ability_bind_click(e, c))
            btn.bind("<Button-3>", lambda e, c=combo: self.on_ability_unbind_click(e, c))
            self.ability_bind_btns[combo] = btn
            col += 1
            if col > 2: col = 0; row += 1

        # --- Раздел 2 ---
        self.frames["camera"] = tk.Frame(self.content_frame)
        self.lbl_cam_title = tk.Label(self.frames["camera"], text="Камера", font=("Segoe UI", 11, "bold"))
        self.lbl_cam_title.pack(pady=(15, 5))
        self.lbl_cam_warn = tk.Label(self.frames["camera"], text="Дота закрыта?", font=("Segoe UI", 9))
        self.lbl_cam_warn.pack(pady=(0, 5))

        self.cam_frame = tk.Frame(self.frames["camera"])
        self.cam_frame.pack(pady=5)
        self.lbl_cam_dist = tk.Label(self.cam_frame, text="Дистанция:", font=("Segoe UI", 9))
        self.lbl_cam_dist.pack(side="left")
        self.cam_dist_var = tk.IntVar(value=1600)
        self.cam_spinbox = tk.Spinbox(self.cam_frame, from_=1130, to=3000, width=5, textvariable=self.cam_dist_var, bd=0, relief="flat", font=("Segoe UI", 9))
        self.cam_spinbox.pack(side="left", padx=5)

        self.btn_patch = tk.Button(self.frames["camera"], text="Патч", font=("Segoe UI", 9, "bold"), bd=0, relief="flat", command=self.patch_camera)
        self.btn_patch.pack(pady=5)
        self.cam_status = tk.Label(self.frames["camera"], text="Готово", font=("Segoe UI", 9))
        self.cam_status.pack(pady=(0, 5))

        self.separator = tk.Frame(self.frames["camera"], height=1, width=400)
        self.separator.pack(pady=5)

        self.lbl_cam_ingame = tk.Label(self.frames["camera"], text="В игре:", font=("Segoe UI", 10, "bold"))
        self.lbl_cam_ingame.pack(pady=(5, 2))
        self.btn_copy_cmd = tk.Button(self.frames["camera"], text="Копировать", font=("Segoe UI", 9, "bold"), bd=0, relief="flat", command=self.copy_cam_command)
        self.btn_copy_cmd.pack(pady=5)

        # --- Раздел 3, 4, 5 ---
        self.frames["creepstop"] = tk.Frame(self.content_frame)
        self.lbl_creep_title = tk.Label(self.frames["creepstop"], text="Крипстоп", font=("Segoe UI", 11, "bold"))
        self.lbl_creep_title.pack(pady=(30, 10))
        self.lbl_creep_dev = tk.Label(self.frames["creepstop"], text="В разработке", font=("Segoe UI", 10))
        self.lbl_creep_dev.pack()

        self.frames["armlet"] = tk.Frame(self.content_frame)
        self.lbl_armlet_title = tk.Label(self.frames["armlet"], text="Армлет", font=("Segoe UI", 11, "bold"))
        self.lbl_armlet_title.pack(pady=(30, 10))
        self.lbl_armlet_dev = tk.Label(self.frames["armlet"], text="В разработке", font=("Segoe UI", 10))
        self.lbl_armlet_dev.pack()

        self.frames["autoheal"] = tk.Frame(self.content_frame)
        self.lbl_heal_title = tk.Label(self.frames["autoheal"], text="Авто-хил", font=("Segoe UI", 11, "bold"))
        self.lbl_heal_title.pack(pady=(30, 10))
        self.lbl_heal_dev = tk.Label(self.frames["autoheal"], text="В разработке", font=("Segoe UI", 10))
        self.lbl_heal_dev.pack()

        # --- Раздел 6: Настройки ---
        self.frames["settings"] = tk.Frame(self.content_frame)
        self.lbl_settings_title = tk.Label(self.frames["settings"], text="Настройки", font=("Segoe UI", 11, "bold"))
        self.lbl_settings_title.pack(pady=(20, 15))

        self.lang_frame = tk.Frame(self.frames["settings"])
        self.lang_frame.pack(pady=10)
        self.lbl_lang = tk.Label(self.lang_frame, text="Язык:", font=("Segoe UI", 9))
        self.lbl_lang.pack(side="left", padx=10)
        self.lang_menu = tk.OptionMenu(self.lang_frame, self.lang_var, "Русский", "Українська", "English")
        self.lang_menu.config(bd=0, relief="flat", font=("Segoe UI", 9))
        self.lang_menu.pack(side="left")

        self.theme_frame = tk.Frame(self.frames["settings"])
        self.theme_frame.pack(pady=10)
        self.lbl_theme = tk.Label(self.theme_frame, text="Тема:", font=("Segoe UI", 9))
        self.lbl_theme.pack(side="left", padx=10)
        self.theme_menu = tk.OptionMenu(self.theme_frame, self.theme_var, "Чёрный-Красный", "Чёрный-Белый", "Серый-Чёрный")
        self.theme_menu.config(bd=0, relief="flat", font=("Segoe UI", 9))
        self.theme_menu.pack(side="left")

        self.show_section("ability_binds")

        self.apply_theme()
        self.apply_language()

    def get_bind_icon(self, base_name):
        if not HAS_PIL: return None
        if base_name in self.bind_icon_cache: return self.bind_icon_cache[base_name]
        img_path = self.find_image_path(base_name)
        if not img_path: return None
        try:
            img = Image.open(img_path).convert("RGBA")
            try: resample = Image.Resampling.LANCZOS
            except AttributeError: resample = Image.LANCZOS
            img = img.resize((20, 20), resample)
            tk_img = ImageTk.PhotoImage(img)
            self.bind_icon_cache[base_name] = tk_img
            return tk_img
        except Exception: return None

    # ================= ПРИМЕНЕНИЕ ЯЗЫКА =================
    def apply_language(self):
        t = TRANSLATIONS[self.lang_var.get()]

        self.title_lbl.config(text=t["title"])
        self.bind_btn.config(text=t["bind"])
        self.lvl_lbl_title.config(text=t["lvl"])
        self.tornado_lbl_title.config(text=t["tornado"])

        if hasattr(self, 'large_window') and self.large_window.winfo_exists():
            self.settings_title.config(text=t["settings"])
            self.btn_tab1.config(text=t["tab_ability"])
            self.btn_tab2.config(text=t["tab_cam"])
            self.btn_tab3.config(text=t["tab_creep"])
            self.btn_tab4.config(text=t["tab_armlet"])
            self.btn_tab5.config(text=t["tab_heal"])
            self.btn_tab6.config(text=t["tab_settings"])

            self.lbl_ability_title.config(text=t["ability_title"])
            self.lbl_ability_hint.config(text=t["ability_hint"])

            self.lbl_cam_title.config(text=t["cam_title"])
            self.lbl_cam_warn.config(text=t["cam_warn"])
            self.lbl_cam_dist.config(text=t["cam_dist"])
            self.btn_patch.config(text=t["cam_btn"])
            self.cam_status.config(text=t["cam_ready"])
            self.lbl_cam_ingame.config(text=t["cam_copy"])

            self.lbl_creep_dev.config(text=t["dev"])
            self.lbl_armlet_dev.config(text=t["dev"])
            self.lbl_heal_dev.config(text=t["dev"])

            self.lbl_lang.config(text=t["lang_lbl"])
            self.lbl_theme.config(text=t["theme_lbl"])

    # ================= ПРИМЕНЕНИЕ ТЕМЫ =================
    def apply_theme(self):
        c = THEMES[self.theme_var.get()]

        def recolor(widget):
            try:
                w_class = widget.winfo_class()
                if w_class in ("Frame", "Toplevel", "Tk"):
                    is_panel = False
                    if hasattr(self, 'content_frame') and widget == self.content_frame: is_panel = True
                    if hasattr(self, 'inventory_frame') and widget == self.inventory_frame: is_panel = True
                    if hasattr(self, 'sidebar') and widget == self.sidebar: is_panel = True
                    if hasattr(self, 'title_bar') and widget == self.title_bar: is_panel = True
                    if hasattr(self, 'settings_title_bar') and widget == self.settings_title_bar: is_panel = True

                    if is_panel:
                        widget.config(bg=c["panel"])
                    else:
                        widget.config(bg=c["bg"])

                elif w_class == "Label":
                    if widget.cget("bg") in ("#1a1a1a", "#111111", "#444444"):
                        widget.config(bg=c["panel"], fg=c["text"])
                    elif widget in (self.pin_btn, self.close_btn, self.min_btn):
                        widget.config(bg=c["panel"], fg=c["accent"] if widget == self.pin_btn else c["text"])
                    else:
                        widget.config(bg=c["bg"], fg=c["text"])

                elif w_class in ("Button", "Checkbutton", "Radiobutton"):
                    if widget in (self.bind_btn, self.menu_btn):
                        widget.config(bg=c["accent"], fg="#ffffff")
                    elif widget == self.clear_btn:
                        widget.config(bg=c["btn_dark"], fg=c["text"])
                    elif widget in self.tab_buttons.values():
                        if widget.cget("bg") == "#ff4545" or widget.cget("bg") == c["accent"]:
                            widget.config(bg=c["accent"], fg="#ffffff")
                        else:
                            widget.config(bg=c["btn"], fg=c["text"])
                    elif widget in (getattr(self, 'btn_patch', None), getattr(self, 'btn_copy_cmd', None)):
                        widget.config(bg="#ff8c00" if widget == self.btn_patch else "#28a745", fg="#ffffff")
                    else:
                        if widget.cget("bg") != "#aaaaaa":
                            widget.config(bg=c["btn"], fg=c["text"], activebackground=c["accent"])

                elif w_class == "Spinbox":
                    widget.config(bg=c["btn"], fg="#ffffff", buttonbackground=c["btn_dark"], insertbackground="white")

                elif w_class == "Entry":
                    widget.config(bg=c["btn"], fg="#ffffff", insertbackground=c["text"])

                elif w_class == "OptionMenu":
                    widget.config(bg=c["btn"], fg=c["text"])
                    widget["menu"].config(bg=c["panel"], fg=c["text"])
            except Exception:
                pass

            for child in widget.winfo_children():
                recolor(child)

        recolor(self.root)
        if hasattr(self, 'large_window') and self.large_window.winfo_exists():
            recolor(self.large_window)
            for combo, btn in self.ability_bind_btns.items():
                if btn.cget("bg") != "#aaaaaa" and btn.cget("bg") != "#28a745":
                    icon = self.get_bind_icon(ALL_COMBOS[combo]["icon"])
                    btn.config(bg=c["btn"], fg=c["text"], image=icon, compound="left")

    # ================= ОСТАЛЬНАЯ ЛОГИКА =================
    def show_section(self, name):
        for frame in self.frames.values():
            frame.pack_forget()
        self.frames[name].pack(fill="both", expand=True)

    def on_ability_bind_click(self, event, combo_name):
        self.ability_bind_mode = True
        self.current_binding_target = combo_name
        self.bind_ready_time = time.time() + 0.3
        icon = self.get_bind_icon(ALL_COMBOS[combo_name]["icon"])
        self.ability_bind_btns[combo_name].config(text="Жду...", image=icon, compound="left", bg="#aaaaaa")

    def on_ability_unbind_click(self, event, combo_name):
        if combo_name in self.ability_binds:
            del self.ability_binds[combo_name]
        icon = self.get_bind_icon(ALL_COMBOS[combo_name]["icon"])
        self.ability_bind_btns[combo_name].config(text=combo_name, image=icon, compound="left")
        self.apply_theme()

    def patch_camera(self):
        if not HAS_PATCHER_DEPS:
            self.cam_status.config(text="Ошибка: Установите vdf и requests", fg="#ff4545")
            return

        self.btn_patch.config(state="disabled", bg="#aaaaaa")
        self.cam_status.config(text="Инициализация...", fg="#ffcc00")

        def _update_status(text, color="#ffcc00"):
            self.root.after(0, lambda: self.cam_status.config(text=text, fg=color))

        def _patch_thread():
            try:
                exe_path = os.path.join(os.getcwd(), "Dota2Patcher.exe")

                if not os.path.exists(exe_path):
                    _update_status("Скачивание Dota2Patcher с GitHub...")
                    self.download_latest_patcher(exe_path)

                _update_status("Запуск патчера (с настройками FOV)...", "#28a745")
                time.sleep(0.5)

                keyboard_ctrl.press(Key.shift)
                time.sleep(0.1)

                result = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe_path, None, None, 1)

                time.sleep(0.5)
                keyboard_ctrl.release(Key.shift)

                if result <= 32:
                    raise Exception("Запуск отменен (Вы нажали 'Нет' в окне UAC).")

                _update_status("Настрой FOV в окне патчера!", "#ffcc00")
                time.sleep(5.0)

                _update_status("Запуск Dota 2...", "#ffcc00")
                os.startfile("steam://rungameid/570")

                _update_status("Успех! Дота запускается. Приятной игры.", "#28a745")

            except Exception as e:
                _update_status(f"Ошибка: {str(e)}", "#ff4545")
            finally:
                self.root.after(0, lambda: self.btn_patch.config(state="normal", bg="#ff8c00"))

        threading.Thread(target=_patch_thread, daemon=True).start()

    def copy_cam_command(self):
        dist = self.cam_dist_var.get()
        cmd = f"dota_camera_distance {dist}"

        self.root.clipboard_clear()
        self.root.clipboard_append(cmd)
        self.root.update()

        self.cam_status.config(text=f"Скопировано: {cmd}", fg="#28a745")

    def download_latest_patcher(self, save_path):
        api_url = "https://api.github.com/repos/Wolf49406/Dota2Patcher/releases/latest"
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()

        data = response.json()
        download_url = None
        for asset in data.get("assets", []):
            if asset["name"].endswith(".exe"):
                download_url = asset["browser_download_url"]
                break

        if not download_url:
            raise Exception("Не удалось найти .exe файл в последнем релизе.")

        r = requests.get(download_url, stream=True, timeout=30)
        r.raise_for_status()

        with open(save_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    def on_bind_click(self, event):
        if self.combo_running: return
        self.binding_mode = True
        self.ability_bind_mode = False
        self.bind_ready_time = time.time() + 0.3
        self.bind_btn.config(text="..", bg="#aaaaaa")

    def on_unbind_click(self, event=None):
        global _last_tornado_time
        self.bound_key = None
        self.binding_mode = False
        self.bound_key_pressed = False
        self.section_index = 0
        self.last_release_time = None
        _last_tornado_time = None
        self.bind_btn.config(text="BIND", bg="#ff4545")
        self.apply_theme()

    def get_key_name(self, k):
        if isinstance(k, keyboard.Key):
            return k.name.upper()
        elif isinstance(k, keyboard.KeyCode):
            return k.char.upper() if k.char else str(k).replace("Key.", "").upper()
        elif isinstance(k, mouse.Button):
            if k == mouse.Button.left: return "M:L"
            if k == mouse.Button.right: return "M:R"
            if k == mouse.Button.middle: return "M:M"
            name = str(k)
            if name in ["Button.x1", "Button.button8"]: return "M4"
            if name in ["Button.x2", "Button.button9"]: return "M5"
            return name.replace("Button.", "M:").upper()
        return str(k)

    def process_trigger_press(self, k):
        if self.binding_mode or self.ability_bind_mode:
            return

        for combo_name, key in self.ability_binds.items():
            if key is not None and k == key:
                if not self.combo_running:
                    self.stop_event.clear()
                    threading.Thread(target=self._run_single_combo, args=(combo_name,), daemon=True).start()
                return

        if self.bound_key is None or k != self.bound_key:
            return
        if self.bound_key_pressed:
            return
        self.bound_key_pressed = True

        if self.combo_running:
            return

        combos = TABS_DATA.get(self.current_section.get(), [])
        start_index = 0
        if (self.last_release_time is not None
                and 0 < self.section_index < len(combos)
                and time.time() - self.last_release_time <= RESUME_TIMEOUT):
            start_index = self.section_index

        self.stop_event.clear()
        self.combo_running = True
        self.root.after(0, lambda si=start_index: self.start_macro(si))

    def process_trigger_release(self, k):
        if self.ability_bind_mode:
            if time.time() < self.bind_ready_time:
                return

            combo = self.current_binding_target
            icon = self.get_bind_icon(ALL_COMBOS[combo]["icon"])

            if isinstance(k, mouse.Button) and k in (mouse.Button.left, mouse.Button.right):
                if combo in self.ability_binds:
                    del self.ability_binds[combo]
                self.root.after(0, lambda: self.ability_bind_btns[combo].config(text=combo, image=icon, compound="left", bg=THEMES[self.theme_var.get()]["btn"]))
            else:
                self.ability_binds[combo] = k
                name = self.get_key_name(k)
                disp_name = name if len(name) <= 8 else name[:8]
                self.root.after(0, lambda: self.ability_bind_btns[combo].config(text=disp_name, image=icon, compound="left", bg="#28a745"))

            self.ability_bind_mode = False
            return

        if self.binding_mode:
            if time.time() < self.bind_ready_time:
                return
            self.bound_key = k
            self.binding_mode = False
            name = self.get_key_name(k)
            disp_name = name if len(name) <= 6 else name[:6]
            self.root.after(0, lambda: self.bind_btn.config(text=disp_name, bg="#28a745"))
            return

        if self.bound_key is not None and k == self.bound_key:
            self.bound_key_pressed = False
            self.stop_event.set()
            self.last_release_time = time.time()

    def on_keyboard_press(self, key):
        self.process_trigger_press(key)

    def on_keyboard_release(self, key):
        self.process_trigger_release(key)

    def on_mouse_click(self, x, y, button, pressed):
        if pressed:
            self.process_trigger_press(button)
        else:
            self.process_trigger_release(button)

    def _run_single_combo(self, combo_name):
        self.combo_running = True
        try:
            lvl = int(self.lvl_var.get()) if int(self.lvl_var.get()) >= 1 else 1
            delay = level_delay(lvl)
            run_combo(ALL_COMBOS[combo_name]["keys"], delay, self.stop_event)
        finally:
            self.combo_running = False

    # ===== OCR OFF: auto_level_loop отключён =====
    # def auto_level_loop(self):
    #     global _current_auto_level
    #     monitor = {"top": 1015, "left": 925, "width": 35, "height": 35}
    #
    #     with mss.mss() as sct:
    #         while self.auto_threads_running:
    #             try:
    #                 img = np.array(sct.grab(monitor))
    #                 gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    #                 gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    #                 _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    #
    #                 config = '--psm 10 -c tessedit_char_whitelist=0123456789'
    #                 text = pytesseract.image_to_string(thresh, config=config).strip()
    #
    #                 if text.isdigit():
    #                     lvl = int(text)
    #                     if 1 <= lvl <= 30:
    #                         _current_auto_level = lvl
    #                         self.root.after(0, lambda l=lvl: self.update_auto_level_ui(l))
    #             except: pass
    #             time.sleep(0.5)

    def update_auto_level_ui(self, lvl):
        # OCR OFF: заглушка, чтобы случайный вызов не падал
        self.lvl_var.set(lvl)
        self.lvl_spinbox.config(bg="#1e4a1e")

    # ===== OCR OFF: auto_quas_loop отключён =====
    # def auto_quas_loop(self):
    #     global _current_auto_quas
    #     monitor = {"top": 980, "left": 600, "width": 720, "height": 100}
    #
    #     with mss.mss() as sct:
    #         while self.auto_threads_running:
    #             try:
    #                 img = np.array(sct.grab(monitor))
    #                 hsv = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    #                 hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)
    #
    #                 lower_yellow = np.array([15, 100, 100])
    #                 upper_yellow = np.array([40, 255, 255])
    #                 mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
    #
    #                 cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    #
    #                 valid_squares = 0
    #                 for c in cnts:
    #                     x, y, w, h = cv2.boundingRect(c)
    #                     if 4 < w < 25 and 4 < h < 25 and 0.6 < w/h < 1.5:
    #                         valid_squares += 1
    #
    #                 if 1 <= valid_squares <= 7:
    #                     _current_auto_quas = valid_squares
    #                     self.root.after(0, lambda q=valid_squares: self.update_auto_quas_ui(q))
    #
    #             except: pass
    #             time.sleep(0.5)

    def update_auto_quas_ui(self, lvl):
        # OCR OFF: заглушка, чтобы случайный вызов не падал
        self.tornado_var.set(lvl)
        self.tornado_spinbox.config(bg="#1e4a1e")

    def resize_window(self):
        self.root.update_idletasks()
        w = 240
        h = self.root.winfo_reqheight()

        if not hasattr(self, '_initial_pos_set'):
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()

            start_x = 1365
            start_y = int(sh * 0.6)

            self.root.geometry(f"{w}x{h}+{start_x}+{start_y}")
            self._initial_pos_set = True
        else:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            self.root.geometry(f"{w}x{h}+{x}+{y}")

    def find_image_path(self, base_name):
        valid_exts = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
        if not os.path.exists("icons"): os.makedirs("icons")
        for f in os.listdir("icons"):
            f_lower = f.lower()
            if f_lower.startswith(base_name.lower() + ".") and f_lower.endswith(valid_exts):
                return os.path.join("icons", f)
        return None

    def get_icon(self, base_name):
        if not HAS_PIL: return None
        if base_name in self.icon_cache: return self.icon_cache[base_name]
        img_path = self.find_image_path(base_name)
        if not img_path: return None
        try:
            img = Image.open(img_path).convert("RGBA")
            try: resample = Image.Resampling.LANCZOS
            except AttributeError: resample = Image.LANCZOS
            img = img.resize(self.ICON_SIZE, resample)
            tk_img = ImageTk.PhotoImage(img)
            self.icon_cache[base_name] = tk_img
            return tk_img
        except Exception: return None

    def get_dark_icon(self, base_name):
        if not HAS_PIL: return None
        if base_name in self.dark_icon_cache: return self.dark_icon_cache[base_name]
        img_path = self.find_image_path(base_name)
        if not img_path: return None
        try:
            img = Image.open(img_path).convert("RGBA")
            try: resample = Image.Resampling.LANCZOS
            except AttributeError: resample = Image.LANCZOS
            img = img.resize(self.ICON_SIZE, resample)
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(0.3)
            tk_img = ImageTk.PhotoImage(img)
            self.dark_icon_cache[base_name] = tk_img
            return tk_img
        except Exception: return None

    def toggle_pin(self, event):
        self.is_pinned = not self.is_pinned
        self.root.attributes("-topmost", self.is_pinned)
        self.pin_btn.config(fg="#ff4545" if self.is_pinned else "#555555")

    def minimize_window(self, event=None):
        self.root.overrideredirect(False)
        self.root.iconify()
        self.root.bind("<Map>", self.on_restore)

    def on_restore(self, event):
        if self.root.state() == 'normal':
            self.root.overrideredirect(True)

    def start_window_move(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def move_window(self, event):
        x = self.root.winfo_x() - self._drag_x + event.x
        y = self.root.winfo_y() - self._drag_y + event.y
        self.root.geometry(f"+{x}+{y}")

    def _update_lvl_label(self):
        try:
            lvl = int(self.lvl_var.get())
            if 1 <= lvl <= 30:
                self.lvl_label.config(text=f"({level_delay(lvl):.1f}s)")
            else:
                self.lvl_label.config(text="(1..30)")
        except: pass

    def _update_tornado_label(self):
        try:
            n = int(self.tornado_var.get())
            if 1 <= n <= 9:
                self.tornado_label.config(text=f"({tornado_delay(n):.1f}s)")
            else:
                self.tornado_label.config(text="(1..9)")
        except: pass

    def toggle_inventory(self):
        self.show_inventory = not self.show_inventory
        if self.show_inventory:
            self.inventory_frame.pack(fill="x", padx=3, pady=2, before=self.workspace_outer)
            self.gear_btn.config(fg="#ff4545")
        else:
            self.inventory_frame.pack_forget()
            self.gear_btn.config(fg="#aaaaaa")
        self.refresh_ui()

    def switch_tab(self, tab_name):
        global _last_tornado_time
        self.current_section.set(tab_name)
        self.section_index = 0
        self.last_release_time = None
        _last_tornado_time = None
        for name, btn in self.tab_buttons.items():
            if name == tab_name:
                btn.config(bg=THEMES[self.theme_var.get()]["accent"], fg="#ffffff")
            else:
                btn.config(bg=THEMES[self.theme_var.get()]["btn"], fg=THEMES[self.theme_var.get()]["text"])
        self.refresh_ui()

    def refresh_ui(self):
        self.render_inventory()
        self.render_workspace()
        self.root.after(10, self.resize_window)

    def create_combo_widget(self, parent, name, bg, fg, is_active=False):
        if is_active:
            icon_img = self.get_dark_icon(ALL_COMBOS[name]["icon"])
        else:
            icon_img = self.get_icon(ALL_COMBOS[name]["icon"])

        if icon_img:
            lbl = tk.Label(parent, image=icon_img, bg=bg, relief="ridge", bd=1, cursor="hand2")
        else:
            lbl = tk.Label(parent, text=name, bg=bg, fg=fg, font=("Segoe UI", 6, "bold"),
                           width=6, height=1, relief="ridge", bd=1, cursor="hand2")

        lbl._combo_name = name
        return lbl

    def render_inventory(self):
        for w in self.inv_grid.winfo_children(): w.destroy()
        if not self.show_inventory: return

        tab = self.current_section.get()
        active_items = TABS_DATA[tab]

        for i, name in enumerate(ALL_COMBOS.keys()):
            in_active = name in active_items
            bg = "#2a2a2a" if in_active else "#383838"
            fg = "#555555" if in_active else "#ffffff"

            lbl = self.create_combo_widget(self.inv_grid, name, bg, fg, is_active=in_active)
            row, col = divmod(i, 4)
            lbl.grid(row=row, column=col, padx=1, pady=1, sticky="nsew")

            lbl.bind("<ButtonPress-1>", lambda e, n=name: self.start_drag(e, n, "inventory"))

    def render_workspace(self):
        for w in self.workspace_frame.winfo_children(): w.destroy()
        tab = self.current_section.get()
        combos = TABS_DATA[tab]

        for i, name in enumerate(combos):
            lbl = self.create_combo_widget(self.workspace_frame, name, "#2a2a2a", "#ffffff", is_active=False)
            row, col = divmod(i, 4)
            lbl.grid(row=row, column=col, padx=1, pady=1, sticky="nsew")
            lbl.bind("<ButtonPress-1>", lambda e, n=name: self.start_drag(e, n, "workspace"))

    def start_drag(self, event, item_name, source):
        self.drag_data = {"item": item_name, "source": source}

        original_widget = event.widget
        dark_img = self.get_dark_icon(ALL_COMBOS[item_name]["icon"])
        if dark_img and hasattr(original_widget, 'config'):
            original_widget.config(image=dark_img)

        self.drag_win = tk.Toplevel(self.root)
        self.drag_win.overrideredirect(True)
        self.drag_win.attributes("-topmost", True)

        icon_img = self.get_icon(ALL_COMBOS[item_name]["icon"])
        if icon_img:
            lbl = tk.Label(self.drag_win, image=icon_img, bg="#ff4545", relief="solid", bd=1)
        else:
            lbl = tk.Label(self.drag_win, text=item_name, bg="#ff4545", fg="white", font=("Segoe UI", 6, "bold"), relief="solid", bd=1)

        lbl.pack()
        self.drag_win.geometry(f"+{event.x_root+3}+{event.y_root+3}")

    def on_drag(self, event):
        if self.drag_win:
            self.drag_win.geometry(f"+{event.x_root+3}+{event.y_root+3}")

    def stop_drag(self, event):
        if not self.drag_win: return
        self.drag_win.destroy()
        self.drag_win = None

        target_widget = self.root.winfo_containing(event.x_root, event.y_root)
        if not target_widget:
            self.refresh_ui()
            return

        widget = target_widget
        is_inv = False
        is_ws = False

        while widget:
            if widget == self.inventory_frame: is_inv = True; break
            if widget == self.workspace_frame: is_ws = True; break
            widget = widget.master

        tab = self.current_section.get()
        item = self.drag_data["item"]

        if is_inv:
            if self.drag_data["source"] == "workspace":
                if item in TABS_DATA[tab]:
                    TABS_DATA[tab].remove(item)

        elif is_ws:
            if self.drag_data["source"] == "inventory":
                TABS_DATA[tab].append(item)
            elif self.drag_data["source"] == "workspace":
                if hasattr(target_widget, "_combo_name"):
                    target_name = target_widget._combo_name
                    if target_name != item:
                        try:
                            idx_from = TABS_DATA[tab].index(item)
                            idx_to = TABS_DATA[tab].index(target_name)
                            TABS_DATA[tab].pop(idx_from)
                            TABS_DATA[tab].insert(idx_to, item)
                        except ValueError: pass
                else:
                    TABS_DATA[tab].remove(item)
                    TABS_DATA[tab].append(item)

        self.refresh_ui()

    def start_macro(self, start_index):
        sec = self.current_section.get()

        try:
            lvl = int(self.lvl_var.get())
            if not (1 <= lvl <= 30):
                self.combo_running = False
                return
        except:
            self.combo_running = False
            return

        try:
            torn = int(self.tornado_var.get())
            if not (1 <= torn <= 9):
                torn = 1
        except:
            torn = 1

        self.worker = threading.Thread(
            target=self._run_worker,
            args=(sec, lvl, tornado_delay(torn), start_index),
            daemon=True
        )
        self.worker.start()

    def _run_worker(self, sec, lvl, tornado_d, start_index):
        try:
            idx, completed = run_section(sec, lvl, tornado_d, self.stop_event, start_index)
            if completed:
                self.section_index = 0
                self.last_release_time = None
            else:
                self.section_index = idx
        finally:
            self.combo_running = False

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = App(root)
        root.mainloop()
    except Exception as e:
        import traceback
        from tkinter import messagebox
        traceback.print_exc()
        err_root = tk.Tk()
        err_root.withdraw()
        messagebox.showerror("Ошибка", str(e))
        err_root.destroy()
