import cv2
import time
import os
import urllib.request
import pygetwindow as gw
import pyautogui
import ctypes
from ctypes import wintypes
import sys
import json
import threading
import signal
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from core.face_detector import FaceDetector

# ================= 全局退出信号 =================

class Application:
    """管理程序生命周期和退出信号。

    所有需要发起或响应退出请求的模块，均通过 Application 实例操作，
    不直接访问任何模块级全局变量。
    """
    def __init__(self):
        self._exit_event = threading.Event()

    def request_exit(self):
        """请求退出。幂等操作——多次调用效果相同。"""
        self._exit_event.set()

    def is_exit_requested(self):
        """是否已请求退出。"""
        return self._exit_event.is_set()

    def reset(self):
        """重置退出状态（每次启动监控时调用）。"""
        self._exit_event.clear()


# 信号处理器无法避免模块级引用：signal.signal() 的 API 要求模块级回调
_app = None  # type: Application | None


def _quit_signal_handler(signum, frame):
    """Ctrl+C / SIGTERM 处理器"""
    if _app and not _app.is_exit_requested():
        print("\n[*] 收到系统信号，正在退出...")
    if _app:
        _app.request_exit()


signal.signal(signal.SIGINT, _quit_signal_handler)
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, _quit_signal_handler)


class QuitWatcher:
    """通过 Windows 全局热键 Ctrl+Alt+Q 触发退出，不依赖任何第三方库。"""

    _HOTKEY_ID = 0xC001
    MOD_ALT = 0x0001
    MOD_CTRL = 0x0002
    MOD_NOREPEAT = 0x4000
    VK_Q = 0x51
    PM_REMOVE = 1

    def __init__(self, app):
        self._app = app
        self._thread = None
        self._hk_registered = False

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="QuitWatcher")
        self._thread.start()

    def _run(self):
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, self._HOTKEY_ID,
                                     self.MOD_CTRL | self.MOD_ALT | self.MOD_NOREPEAT,
                                     self.VK_Q):
            print("[!] 注册退出热键失败（可能被其他程序占用）")
            print("[!] 请通过任务管理器结束 moyu 相关进程")
            return
        self._hk_registered = True

        try:
            msg = wintypes.MSG()
            while not self._app.is_exit_requested():
                # 使用 PeekMessage 非阻塞轮询，避免 GetMessageW 阻塞在
                # 内核导致 daemon 线程无法随主线程退出
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, self.PM_REMOVE):
                    if msg.message == 0x0312 and msg.wParam == self._HOTKEY_ID:
                        break
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.05)
        except Exception:
            pass
        finally:
            if self._hk_registered:
                user32.UnregisterHotKey(None, self._HOTKEY_ID)
            self._app.request_exit()


class TrayIcon:
    """系统托盘图标，右击弹出菜单可退出。基于 pystray + PIL 绘制图标。"""

    def __init__(self, app, tooltip="摸鱼守护神"):
        self._app = app
        self._tooltip = tooltip
        self._icon = None

    def start(self):
        """启动托盘图标（参考 eyecare 的 pystray 实现）。"""
        import pystray

        image = self._draw_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("退出摸鱼守护神 (Ctrl+Alt+Q)", self._on_quit, default=True),
        )
        self._icon = pystray.Icon("moyu_guardian", image, self._tooltip, menu)
        threading.Thread(target=self._icon.run, daemon=True).start()

    @staticmethod
    def _draw_icon_image():
        """用 PIL 绘制托盘图标，返回 PIL Image 对象。"""
        from PIL import Image, ImageDraw
        sz = 64
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        r = 4
        draw.ellipse([r, r, sz - r - 1, sz - r - 1], fill=(30, 85, 180, 255))
        draw.ellipse([12, 20, 52, 44], fill=(255, 255, 255, 255))
        draw.ellipse([25, 25, 39, 39], fill=(25, 50, 100, 255))
        draw.ellipse([29, 27, 35, 33], fill=(255, 255, 255, 200))

        for dx in (18, 26, 34, 42):
            draw.line([(dx, 14), (dx + 3, 20)], fill=(255, 255, 255, 180), width=2)

        return img

    def _on_quit(self, icon=None, item=None):
        """菜单点击退出"""
        self._app.request_exit()
        if self._icon:
            self._icon.stop()

    def stop(self):
        """停止托盘图标"""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

# 禁用鼠标角落保护
pyautogui.FAILSAFE = False

# ================= 配置文件路径 =================
# 模型跟随 exe 打包，通过 sys._MEIPASS 或脚本目录定位
_PROGRAM_DIR = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = "moyu_config.json"  # 用户配置始终在运行目录
PROTOTXT_PATH = os.path.join(_PROGRAM_DIR, "face_deploy.prototxt")
MODEL_PATH = os.path.join(_PROGRAM_DIR, "face_res10.caffemodel")

# ================= 默认配置 =================
DEFAULT_CONFIG = {
    "work_app_title": "",
    "work_app_exe": "",       # 新增：进程名，如 idea64.exe / chrome.exe
    "stealth_mode": False,
    "cooldown_time": 5.0
}

# ================= 单实例检测 =================
def ensure_single_instance():
    """确保只有一个实例运行（Windows 命名 Mutex）"""
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, "MoyuGuardian_SingleInstance")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(mutex)
        sys.exit(0)
    return mutex

# ================= 配置管理 =================
def load_config():
    """加载配置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            for key in DEFAULT_CONFIG:
                if key not in config:
                    config[key] = DEFAULT_CONFIG[key]
            return config
        except Exception:
            print(f"[!] 读取配置文件失败，使用默认配置。")
            pass
    return DEFAULT_CONFIG.copy()

def save_config(config):
    """保存配置（先写临时文件再原子替换，防止写入中断导致配置丢失）"""
    tmp = CONFIG_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except Exception as e:
        print(f"[!] 保存配置失败: {e}")

# ================= 模型下载 =================
def download_model(url, filename):
    if not os.path.exists(filename):
        print(f"[*] 正在下载模型 {filename}...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as response, open(filename, 'wb') as out_file:
                out_file.write(response.read())
            print(f"[✓] {filename} 下载完成！")
            return True
        except Exception as e:
            print(f"[!] 下载失败: {e}")
            return False
    return True

# ================= 设置窗口 =================
class SettingsWindow:
    """使用 customtkinter 的现代化设置界面"""

    WIDTH = 520
    HEIGHT = 600

    def __init__(self, config, on_save_callback=None, standalone=True):
        """
        standalone=True:  首次启动设置（没有监控在跑），关闭=退出程序
        standalone=False: 从主弹窗"修改设置"进入，关闭=回到主弹窗
        """
        self.config = config
        self.on_save_callback = on_save_callback
        self._standalone = standalone
        self._saved = False  # 标记用户是否点击了"保存并启动"
        self._title_exe_map = {}

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("摸鱼守护神 - 设置")
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 居中显示
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - self.WIDTH) // 2
        y = (self.root.winfo_screenheight() - self.HEIGHT) // 2
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

        self.create_widgets()

        # 首次启动自动加载窗口列表但不弹框
        self.refresh_windows(show_popup=False)

    def create_widgets(self):
        # ===== 底部按钮（先 pack 到 bottom，确保始终可见） =====
        btn_bar = ctk.CTkFrame(self.root, fg_color="transparent")
        btn_bar.pack(side="bottom", fill="x", padx=25, pady=(6, 22))

        ctk.CTkButton(
            btn_bar, text="取消", command=self._on_close,
            font=ctk.CTkFont(size=14),
            fg_color="transparent", border_width=1.5,
            text_color=("gray10", "gray90"),
            hover_color=("gray85", "gray30"),
            height=38, width=120,
        ).pack(side="left")

        ctk.CTkButton(
            btn_bar, text="保存并启动", command=self.save_and_start,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#10b981", hover_color="#059669",
            height=38, width=170,
        ).pack(side="right")

        # ===== 顶部标题区 =====
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(28, 5))

        ctk.CTkLabel(
            header, text="摸鱼守护神",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            header, text="智能摄像头监控 · 守护你的工作隐私",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        ).pack(anchor="w", pady=(4, 0))

        # ===== 主卡片（填充剩余空间） =====
        card = ctk.CTkFrame(self.root, corner_radius=14, border_width=0)
        card.pack(fill="both", expand=True, padx=25, pady=(15, 10))

        # ----- 目标工作应用 -----
        ctk.CTkLabel(
            card, text="目标工作应用",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(22, 4))

        ctk.CTkLabel(
            card, text="检测到多人时自动切换到此窗口",
            font=ctk.CTkFont(size=12), text_color="gray",
        ).pack(anchor="w", padx=28)

        # 下拉选择
        self.app_var = ctk.StringVar(value=self.config.get("work_app_title", ""))
        self.app_combo = ctk.CTkComboBox(
            card, variable=self.app_var,
            values=[""],
            font=ctk.CTkFont(size=13),
            width=440, height=38,
            command=self._on_app_selected,
            state="readonly",
        )
        self.app_combo.pack(fill="x", padx=28, pady=(14, 4))

        # 进程名提示
        exe_name = self.config.get("work_app_exe", "未绑定")
        self._exe_label_var = ctk.StringVar(value=f"进程名：{exe_name}")
        ctk.CTkLabel(
            card, textvariable=self._exe_label_var,
            font=ctk.CTkFont(size=11),
            text_color="#3b82f6",
        ).pack(anchor="w", padx=31, pady=(3, 0))

        # 刷新按钮
        ctk.CTkButton(
            card, text="刷新窗口列表",
            command=lambda: self.refresh_windows(show_popup=True),
            font=ctk.CTkFont(size=11),
            fg_color="transparent", border_width=1.2,
            text_color=("gray10", "gray90"),
            hover_color=("gray85", "gray30"),
            height=30, width=130,
        ).pack(anchor="w", padx=28, pady=(10, 3))

        # 提示文字
        ctk.CTkLabel(
            card,
            text="选中选项后自动绑定对应进程，切换文件标签页也能精准激活",
            font=ctk.CTkFont(size=11), text_color="gray",
        ).pack(anchor="w", padx=31, pady=(3, 14))

        # ----- 分割线 -----
        ctk.CTkFrame(card, height=1, fg_color=("gray80", "gray28")).pack(
            fill="x", padx=28, pady=4
        )

        # ----- 检测设置 -----
        ctk.CTkLabel(
            card, text="检测设置",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(16, 12))

        # 冷却时间滑块
        cd_frame = ctk.CTkFrame(card, fg_color="transparent")
        cd_frame.pack(fill="x", padx=28, pady=4)

        ctk.CTkLabel(
            cd_frame, text="冷却时间", font=ctk.CTkFont(size=13),
        ).pack(side="left")

        self.cooldown_var = ctk.IntVar(value=int(self.config.get("cooldown_time", 5)))
        self._cd_label = ctk.CTkLabel(
            cd_frame, text="", font=ctk.CTkFont(size=13), width=40,
        )
        self._cd_label.pack(side="right")

        self._cd_slider = ctk.CTkSlider(
            cd_frame, from_=1, to=60,
            variable=self.cooldown_var,
            command=self._update_cd_label,
            width=170, number_of_steps=59,
        )
        self._cd_slider.pack(side="right", padx=(0, 10))
        self._update_cd_label(self.cooldown_var.get())

        # 隐蔽模式
        stealth_frame = ctk.CTkFrame(card, fg_color="transparent")
        stealth_frame.pack(fill="x", padx=28, pady=(18, 4))

        self.stealth_var = ctk.BooleanVar(value=self.config.get("stealth_mode", False))
        ctk.CTkCheckBox(
            stealth_frame,
            text="隐蔽模式（隐藏预览窗口）",
            variable=self.stealth_var,
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w")

        ctk.CTkLabel(
            stealth_frame,
            text="启用后不显示摄像头预览，降低被发现风险",
            font=ctk.CTkFont(size=11), text_color="gray",
        ).pack(anchor="w", padx=(28, 0), pady=(3, 12))

    # ==================== 功能方法 ====================

    def _update_cd_label(self, value):
        self._cd_label.configure(text=f"{int(float(value))} 秒")

    def refresh_windows(self, show_popup=False):
        """刷新当前打开的窗口列表，排除文件资源管理器并去重 IDE 多文件窗口"""
        try:
            windows = gw.getAllWindows()
            folder_keywords = [
                "本地磁盘", "此电脑", "回收站", "控制面板", "网络",
                "Desktop", "文档", "下载", "图片", "音乐", "视频",
                "OneDrive", "Quick Access", "快速访问", "库", "个人",
            ]

            # 构建 hwnd → 进程名 的映射（需要 psutil）
            hwnd_to_exe = {}
            if HAS_PSUTIL:
                for w in windows:
                    try:
                        pid = ctypes.c_ulong()
                        ctypes.windll.user32.GetWindowThreadProcessId(w._hWnd, ctypes.byref(pid))
                        proc = psutil.Process(pid.value)
                        hwnd_to_exe[w._hWnd] = proc.name()
                    except Exception:
                        pass

            raw_titles = set()
            self._title_exe_map = {}
            for w in windows:
                if not w.title or not w.visible:
                    continue
                title = w.title.strip()
                if not title:
                    continue
                if "\\" in title or "/" in title:
                    continue
                if any(kw in title for kw in folder_keywords):
                    continue
                raw_titles.add(title)
                if w._hWnd in hwnd_to_exe:
                    self._title_exe_map[title] = hwnd_to_exe[w._hWnd]

            # 按公共后缀去重
            suffix_counter = {}
            suffix_exe_map = {}
            for title in raw_titles:
                parts = title.split(" - ")
                for n in range(1, len(parts)):
                    suffix = " - ".join(parts[n:])
                    suffix_counter[suffix] = suffix_counter.get(suffix, 0) + 1
                    if suffix not in suffix_exe_map and title in self._title_exe_map:
                        suffix_exe_map[suffix] = self._title_exe_map[title]

            display_titles = []
            covered = set()

            for suffix, count in sorted(suffix_counter.items(), key=lambda x: -x[1]):
                if count >= 2 and suffix not in display_titles:
                    display_titles.append(suffix)
                    if suffix in suffix_exe_map:
                        self._title_exe_map[suffix] = suffix_exe_map[suffix]
                    for title in raw_titles:
                        if title.endswith(" - " + suffix):
                            covered.add(title)

            for title in sorted(raw_titles):
                if title not in covered:
                    display_titles.append(title)

            self.app_combo.configure(values=display_titles)
            if show_popup:
                messagebox.showinfo(
                    "提示",
                    f"已获取 {len(display_titles)} 个窗口（原始 {len(raw_titles)} 个）",
                )
        except Exception as e:
            messagebox.showerror("错误", f"获取窗口列表失败: {e}")

    def _on_app_selected(self, value):
        """下拉框选中时，自动读取对应进程名并显示"""
        exe = self._title_exe_map.get(value, "")
        self.config["work_app_exe"] = exe
        self._exe_label_var.set(
            f"进程名：{exe if exe else '未能识别，将使用标题匹配'}"
        )

    def save_and_start(self):
        """保存设置并启动"""
        app_title = self.app_var.get().strip()
        if not app_title:
            messagebox.showwarning("提示", "请选择或输入目标应用窗口标题！")
            return

        self.config["work_app_title"] = app_title
        self.config["work_app_exe"] = self.config.get("work_app_exe", "")
        self.config["cooldown_time"] = float(self.cooldown_var.get())
        self.config["stealth_mode"] = self.stealth_var.get()

        save_config(self.config)
        self._saved = True
        self._cleanup_vars()
        self.root.destroy()

        if self.on_save_callback:
            self.on_save_callback(self.config)

    def _cleanup_vars(self):
        """释放 tkinter 变量引用，避免退出时报 RuntimeError"""
        for attr in ('app_var', 'cooldown_var', 'stealth_var', '_exe_label_var',
                      'app_combo', '_cd_label', '_cd_slider'):
            try:
                delattr(self, attr)
            except Exception:
                pass

    def _on_close(self):
        """关闭设置窗口。若为首次启动（standalone），退出程序；若为修改设置，只关窗口。"""
        self._cleanup_vars()
        self.root.destroy()
        if self._standalone:
            sys.exit(0)

    def run(self):
        self.root.mainloop()

# ================= 窗口切换模块 =================
class WindowReactor:
    def __init__(self, app_title, app_exe="", cooldown=5.0):
        self._app_title = app_title   # 标题关键词，兜底用
        self._app_exe = app_exe       # 进程名，如 idea64.exe，优先用
        self._cooldown = cooldown
        self._last_trigger = 0.0
        
    def _is_target_active(self):
        try:
            active = gw.getActiveWindow()
            if not active:
                return False

            # 策略1：标题关键词匹配
            if active.title and self._app_title in active.title:
                return True

            # 策略2：进程名匹配（IDE 切文件后标题变了，但进程不变）
            if self._app_exe and HAS_PSUTIL:
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(active._hWnd, ctypes.byref(pid))
                try:
                    proc = psutil.Process(pid.value)
                    if proc.name().lower() == self._app_exe.lower():
                        return True
                except Exception:
                    pass
        except Exception as e:
            print(f"[!] 检测活动窗口异常: {e}")
        return False

    def _find_window(self):
        """
        查找目标窗口。
        策略：
          1. 优先按进程名找到所有属于该进程的可见主窗口，取面积最大的。
          2. 退回到标题关键词模糊匹配。
        过滤工具窗口（如 IDE 的浮动工具栏），避免切到小窗。
        """
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080

        def _is_main_window(w):
            """排除工具窗口和不可见窗口"""
            if not w.visible or not w.title or not w.title.strip():
                return False
            ex_style = ctypes.windll.user32.GetWindowLongW(w._hWnd, GWL_EXSTYLE)
            return not (ex_style & WS_EX_TOOLWINDOW)

        # --- 策略1：进程名精准匹配，选面积最大的主窗口 ---
        if self._app_exe and HAS_PSUTIL:
            try:
                target_pids = {
                    p.pid for p in psutil.process_iter(['name'])
                    if p.info['name'] and p.info['name'].lower() == self._app_exe.lower()
                }
                if target_pids:
                    GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
                    candidates = []
                    for w in gw.getAllWindows():
                        if not _is_main_window(w):
                            continue
                        pid = ctypes.c_ulong()
                        GetWindowThreadProcessId(w._hWnd, ctypes.byref(pid))
                        if pid.value in target_pids:
                            area = w.width * w.height if w.width > 0 and w.height > 0 else 0
                            candidates.append((area, w))
                    if candidates:
                        candidates.sort(key=lambda x: -x[0])
                        return candidates[0][1]
            except Exception as e:
                print(f"[!] 进程查找窗口异常: {e}")

        # --- 策略2：标题关键词兜底 ---
        windows = gw.getWindowsWithTitle(self._app_title)
        return windows[0] if windows else None

    def _force_foreground(self, hwnd):
        """
        绕过 Windows 前台窗口限制 (SetForegroundWindow 限制)。
        用 AttachThreadInput 临时连接线程后强制置顶。
        """
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()

        attached = False
        if target_thread != fg_thread:
            user32.AttachThreadInput(target_thread, fg_thread, True)
            attached = True
        if target_thread != cur_thread:
            user32.AttachThreadInput(target_thread, cur_thread, True)
            attached = True

        try:
            # 如果最小化了先恢复
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                if target_thread != fg_thread:
                    user32.AttachThreadInput(target_thread, fg_thread, False)
                if target_thread != cur_thread:
                    user32.AttachThreadInput(target_thread, cur_thread, False)

    def _do_switch(self):
        win = self._find_window()
        if win:
            try:
                self._force_foreground(win._hWnd)
                return
            except Exception as e:
                print(f"[!] 激活窗口失败: {e}")
        print(f"[!] 未找到目标窗口，保底执行显示桌面。")
        try:
            pyautogui.hotkey('win', 'd')
        except Exception as e2:
            print(f"[!] 保底 Win+D 也失败: {e2}")

    def trigger(self):
        now = time.time()
        if now - self._last_trigger <= self._cooldown:
            return
        if self._is_target_active():
            print(f"[{time.strftime('%X')}] 目标窗口已在前台，跳过切换。")
            # 注意：目标已在前台时不重置冷却——下次真正需要切时不受影响
            return
        print(f"[{time.strftime('%X')}] 检测到多人！正在切换到 {self._app_title}...")
        self._do_switch()
        self._last_trigger = now  # 只在真正执行切屏时重置冷却

# ================= 主程序 =================
def run_monitor(config):
    """运行监控程序"""
    # 创建 Application 实例并设置模块级引用（供信号处理器使用）
    global _app
    app = Application()
    _app = app
    app.reset()  # 重置退出信号，防止上次遗留的 set 状态导致立即退出

    print("[*] 检查模型文件...", flush=True)
    if not download_model("https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt", PROTOTXT_PATH):
        print("[!] prototxt 下载失败", flush=True)
        messagebox.showerror("错误", "模型文件下载失败，请检查网络！")
        return
    if not download_model("https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel", MODEL_PATH):
        print("[!] caffemodel 下载失败", flush=True)
        messagebox.showerror("错误", "模型文件下载失败，请检查网络！")
        return
        
    print("[*] 正在加载神经网络...", flush=True)
    net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, MODEL_PATH)
    print("[*] 神经网络加载完成", flush=True)

    detector = FaceDetector(net)
    reactor = WindowReactor(config["work_app_title"], config.get("work_app_exe", ""), config["cooldown_time"])

    print("[*] 正在打开摄像头...", flush=True)
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("[!] 无法打开摄像头！", flush=True)
        messagebox.showerror("错误", "无法打开摄像头！可能被其他程序占用。")
        return

    stealth_mode = config.get("stealth_mode", False)

    # 全局热键退出
    quit_watcher = QuitWatcher(app)
    quit_watcher.start()

    # 系统托盘图标（右击可退出）
    tray = TrayIcon(app, "摸鱼守护神 - 右击退出")
    tray.start()

    print("=" * 50)
    print(f"摸鱼守护神已启动！")
    print(f"   目标应用: {config['work_app_title']}")
    print(f"   冷却时间: {config['cooldown_time']} 秒")
    print(f"   退出方式: 右击系统托盘图标 或 按 Ctrl+Alt+Q")
    if not stealth_mode:
        print("   也可按 ESC 键关闭预览窗口退出")
    else:
        print("   隐蔽模式运行（无预览窗口，通过托盘图标或 Ctrl+Alt+Q 退出）")
    print("=" * 50)

    fail_count = 0
    MAX_FAIL = 30

    try:
        while not app.is_exit_requested():
            success, image = cap.read()
            if not success:
                fail_count += 1
                if fail_count >= MAX_FAIL:
                    print("[!] 摄像头异常，程序退出。")
                    break
                time.sleep(0.1)
                continue
            fail_count = 0

            image = cv2.flip(image, 1)
            state = detector.process_frame(image)

            if state.edge_rising:
                reactor.trigger()

            if not stealth_mode:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
                display_img = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
                cv2.putText(display_img, f"Targets: {state.face_count}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(display_img, f"App: {config['work_app_title'][:30]}", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                cv2.putText(display_img, "Ctrl+Alt+Q to quit", (10, 450),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
                cv2.imshow('Moyu Guardian (ESC to quit)', display_img)
                key = cv2.waitKey(5) & 0xFF
                if key == 27 or cv2.getWindowProperty('Moyu Guardian (ESC to quit)', cv2.WND_PROP_VISIBLE) < 1:
                    app.request_exit()
                    break
            else:
                time.sleep(0.03)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        tray.stop()
        print("[*] 摸鱼守护神已关闭。")

def main():
    _mutex = ensure_single_instance()  # 持有引用防止 GC 释放
    config = load_config()

    while True:
        if not config.get("work_app_title"):
            def on_save(new_config):
                run_monitor(new_config)

            settings = SettingsWindow(config, on_save, standalone=True)
            settings.run()
            sys.exit(0)  # 用户关闭首次设置窗口 → 退出
        else:
            root = tk.Tk()
            root.withdraw()

            result = messagebox.askyesnocancel(
                "摸鱼守护神",
                f"当前目标应用: {config['work_app_title']}\n\n"
                "【是】- 直接启动\n"
                "【否】- 修改设置\n"
                "【取消】- 退出程序"
            )

            if result is True:
                root.destroy()
                run_monitor(config)
                return  # 监控退出 → 结束
            elif result is False:
                root.destroy()

                def on_save(new_config):
                    nonlocal config
                    config = new_config
                    run_monitor(new_config)

                settings = SettingsWindow(config, on_save, standalone=False)
                settings.run()

                if settings._saved:
                    # 保存并启动了监控，run_monitor 已返回 → 结束
                    return
                # 用户关闭了设置窗口但没保存 → 回到主弹窗
                continue
            else:
                root.destroy()
                sys.exit(0)

if __name__ == '__main__':
    main()