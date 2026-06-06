import cv2
import numpy as np
import time
import os
import urllib.request
import pygetwindow as gw
import pyautogui

# 禁用鼠标角落保护（防止摸鱼时鼠标乱甩导致程序崩溃）
pyautogui.FAILSAFE = False 

# ================= 摸鱼生存配置区 =================
# 【核心模式选择】强制切换为应用切换模式
ACTION_MODE = 'SWITCH_APP' 

# 【已为你修改】目标工作软件：IntelliJ IDEA 2025.3.4
# 注：pygetwindow 是模糊匹配，只要 IDEA 的窗口标题中包含这串字符，就能精准抓取并置顶！
WORK_APP_TITLE = "jw-zhyg-api" 

# 隐蔽模式：True 为彻底后台运行（无黑框无预览），False 为显示黑白线条预览（用于测试）
STEALTH_MODE = False 

# 触发切屏的冷却时间（秒）。
# 设为 5 秒是为了防止老板站在你背后时，程序疯狂闪烁切屏。
COOLDOWN_TIME = 5.0 
# ==================================================

PROTOTXT_PATH = "face_deploy.prototxt"
MODEL_PATH = "face_res10.caffemodel"

def download_model(url, filename):
    if not os.path.exists(filename):
        print(f"[*] 首次运行，正在下载深度学习模型 {filename}...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as response, open(filename, 'wb') as out_file:
                out_file.write(response.read())
            print(f"[✓] {filename} 下载完成！")
        except Exception as e:
            print(f"[!] 自动下载失败: {e}。请手动下载并放在同级目录。")
            raise SystemExit()

def is_idea_active():
    """检查 IDEA 窗口是否已经在最前面"""
    try:
        active = gw.getActiveWindow()
        if active and WORK_APP_TITLE in active.title:
            return True
    except Exception:
        pass
    return False

def stealth_alert():
    """无声且隐蔽的切屏动作 (绕过 Windows 焦点限制版)"""
    try:
        if ACTION_MODE == 'SHOW_DESKTOP':
            pyautogui.hotkey('win', 'd')
        elif ACTION_MODE == 'SWITCH_APP':
            windows = gw.getWindowsWithTitle(WORK_APP_TITLE)
            if windows:
                win = windows[0]
                
                # --- 绕过 Windows 焦点拦截的黑科技 ---
                # 1. 先让它最小化
                win.minimize()
                time.sleep(0.1) # 稍微停顿 0.1 秒
                # 2. 再恢复并激活，这通常能骗过 Windows 让它成功置顶
                win.restore()
                win.activate()
                # ------------------------------------
            else:
                print(f"[!] 没找到 IDEA 窗口，保底执行显示桌面。")
                pyautogui.hotkey('win', 'd')
    except Exception as e:
        # 切屏失败，保底显示桌面（如果连这都失败，提醒用户手动操作）
        print(f"[!] 切屏失败: {e}，保底执行显示桌面。")
        try:
            pyautogui.hotkey('win', 'd')
        except Exception:
            print("[!] 显示桌面也失败了，请手动切屏！")

# ================= 模块: FaceDetector =================
class FaceDetector:
    """人脸检测 + 连续帧去抖

    接口:
      detect(image) -> int  返回当前帧检测到的人数
      is_people_nearby() -> bool  去抖后的多人确认
    """
    def __init__(self, net, confirm_frames=8, dnn_skip=3, threshold=0.4):
        self._net = net
        self._confirm_frames = confirm_frames
        self._dnn_skip = dnn_skip
        self._threshold = threshold
        self._face_count = 0
        self._alone_state = True
        self._confirm_counter = 0
        self._frame_idx = 0

    def detect(self, image):
        self._frame_idx += 1
        if self._frame_idx % self._dnn_skip == 0:
            blob = cv2.dnn.blobFromImage(cv2.resize(image, (300, 300)), 1.0,
                                          (300, 300), (104.0, 177.0, 123.0))
            self._net.setInput(blob)
            detections = self._net.forward()
            self._face_count = 0
            for i in range(0, detections.shape[2]):
                if detections[0, 0, i, 2] > self._threshold:
                    self._face_count += 1
        return self._face_count

    def is_people_nearby(self):
        cur_alone = (self._face_count <= 1)
        if cur_alone == self._alone_state:
            self._confirm_counter = 0
        else:
            self._confirm_counter += 1
            if self._confirm_counter >= self._confirm_frames:
                self._alone_state = cur_alone
                self._confirm_counter = 0
        return not self._alone_state

    @property
    def face_count(self):
        return self._face_count


# ================= 模块: WindowReactor =================
class WindowReactor:
    """窗口切换反应

    接口:
      trigger() -> None  触发切屏动作（带冷却守卫）
    """
    def __init__(self, app_title, cooldown=5.0):
        self._app_title = app_title
        self._cooldown = cooldown
        self._last_trigger = 0.0

    def _is_target_active(self):
        try:
            active = gw.getActiveWindow()
            if active and self._app_title in active.title:
                return True
        except Exception:
            pass
        return False

    def _do_switch(self):
        try:
            windows = gw.getWindowsWithTitle(self._app_title)
            if windows:
                win = windows[0]
                win.minimize()
                time.sleep(0.1)
                win.restore()
                win.activate()
            else:
                print(f"[!] 没找到 {self._app_title} 窗口，保底执行显示桌面。")
                pyautogui.hotkey('win', 'd')
        except Exception as e:
            print(f"[!] 切屏失败: {e}，保底执行显示桌面。")
            try:
                pyautogui.hotkey('win', 'd')
            except Exception:
                print("[!] 显示桌面也失败了，请手动切屏！")

    def trigger(self):
        now = time.time()
        if now - self._last_trigger <= self._cooldown:
            return  # 冷却中
        if self._is_target_active():
            print(f"[{time.strftime('%X')}] info 检测到有人靠近，{self._app_title} 已在最前面，跳过切屏。")
        else:
            print(f"[{time.strftime('%X')}] !! 检测到有人靠近！正在召唤 {self._app_title}...")
            self._do_switch()
        self._last_trigger = now


# ================= 主程序 =================
def main():
    download_model("https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt", PROTOTXT_PATH)
    download_model("https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel", MODEL_PATH)

    print("[*] 正在加载神经网络...")
    net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, MODEL_PATH)

    detector = FaceDetector(net)
    reactor = WindowReactor(WORK_APP_TITLE, COOLDOWN_TIME)

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("[!] 错误：无法打开摄像头（可能被其他软件占用）。")
        return

    fail_count = 0
    MAX_FAIL = 30

    print("=" * 40)
    print(".. IDEA 摸鱼守护神已在后台静默启动！")
    print(f"   当前防御目标: {WORK_APP_TITLE}")
    if not STEALTH_MODE:
        print("   (预览窗口已开启，按 ESC 退出)")
    else:
        print("   (完全隐形模式，如需退出请在任务管理器结束 Python 进程)")
    print("=" * 40)

    people_nearby = False

    while True:
        success, image = cap.read()
        if not success:
            fail_count += 1
            if fail_count >= MAX_FAIL:
                print("[!] 摄像头连续抓取失败，可能已断开，程序退出。")
                break
            time.sleep(0.1)
            continue
        fail_count = 0

        image = cv2.flip(image, 1)
        detector.detect(image)

        # 检测到多人靠近时触发切屏
        if detector.is_people_nearby():
            if not people_nearby:
                people_nearby = True
                reactor.trigger()
        else:
            people_nearby = False

        # 调试模式：显示黑白线条
        if not STEALTH_MODE:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
            display_img = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
            cv2.putText(display_img, f"Targets: {detector.face_count}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow('Debug Mode (ESC to quit)', display_img)
            if cv2.waitKey(5) & 0xFF == 27:
                break
        else:
            time.sleep(0.03)

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()