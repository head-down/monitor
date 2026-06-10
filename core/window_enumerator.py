"""窗口枚举模块。

从系统中获取可见窗口标题列表，排除系统文件夹窗口，
并按公共后缀去重（IDE 多文件标签页如 "Foo.java - MyProject"）。

接口:
    enumerator = WindowEnumerator()
    display_titles, title_exe_map = enumerator.enumerate()
"""
import ctypes
import pygetwindow as gw

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class WindowEnumerator:
    """枚举当前可见窗口标题，过滤并去重。

    用法:
        enumerator = WindowEnumerator()
        titles, exe_map = enumerator.enumerate()
        # titles: ["MyProject", "chrome.exe", ...]
        # exe_map: {"MyProject": "idea64.exe", ...}
    """

    def __init__(self):
        self._folder_keywords = [
            "本地磁盘", "此电脑", "回收站", "控制面板", "网络",
            "Desktop", "文档", "下载", "图片", "音乐", "视频",
            "OneDrive", "Quick Access", "快速访问", "库", "个人",
        ]

    def enumerate(self):
        """返回 (display_titles, title_exe_map) 元组。"""
        windows = gw.getAllWindows()

        # 构建 hwnd → 进程名 的映射
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

        # 收集原始标题
        raw_titles = set()
        title_exe_map = {}
        for w in windows:
            if not w.title or not w.visible:
                continue
            title = w.title.strip()
            if not title:
                continue
            if "\\" in title or "/" in title:
                continue
            if any(kw in title for kw in self._folder_keywords):
                continue
            raw_titles.add(title)
            if w._hWnd in hwnd_to_exe:
                title_exe_map[title] = hwnd_to_exe[w._hWnd]

        # 按公共后缀去重（IDE 多文件标签页）
        suffix_counter = {}
        suffix_exe_map = {}
        for title in raw_titles:
            parts = title.split(" - ")
            for n in range(1, len(parts)):
                suffix = " - ".join(parts[n:])
                suffix_counter[suffix] = suffix_counter.get(suffix, 0) + 1
                if suffix not in suffix_exe_map and title in title_exe_map:
                    suffix_exe_map[suffix] = title_exe_map[title]

        display_titles = []
        covered = set()

        for suffix, count in sorted(suffix_counter.items(), key=lambda x: -x[1]):
            if count >= 2 and suffix not in display_titles:
                display_titles.append(suffix)
                if suffix in suffix_exe_map:
                    title_exe_map[suffix] = suffix_exe_map[suffix]
                for title in raw_titles:
                    if title.endswith(" - " + suffix):
                        covered.add(title)

        for title in sorted(raw_titles):
            if title not in covered:
                display_titles.append(title)

        return display_titles, title_exe_map
