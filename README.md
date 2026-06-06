# 摸鱼守护 (Monitor)

基于 OpenCV DNN 人脸检测的实时监控工具。检测到多人靠近时自动切换到 IDE，避免社死。

## 原理

- 摄像头实时采集画面，每 3 帧跑一次人脸检测降低 CPU 占用
- 检测到 >1 人时连续 8 帧确认防止误触发
- 确认后通过 `pygetwindow` 查找 IDEA 窗口并执行 minimize → restore → activate 绕过 Windows 焦点拦截
- 5 秒冷却防止疯狂切屏

## 运行

```bash
cd monitor
python monitor.py
```

## 依赖

```bash
pip install opencv-python numpy pygetwindow pyautogui
```

## 配置

编辑 `monitor.py` 顶部配置区：

| 配置项 | 说明 |
|--------|------|
| `WORK_APP_TITLE` | 目标 IDE 窗口标题关键词 |
| `STEALTH_MODE` | 是否隐藏预览窗口 |
| `COOLDOWN_TIME` | 切屏冷却时间（秒） |

## 平台

仅限 Windows（依赖 `pygetwindow` 和 Windows 窗口 API）。
