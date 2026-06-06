# 摸鱼守护 (Monitor)

[![GitHub stars](https://img.shields.io/github/stars/head-down/monitor?style=flat-square&color=gold)](https://github.com/head-down/monitor/stargazers)
[![GitHub license](https://img.shields.io/github/license/head-down/monitor?style=flat-square&color=blue)](https://github.com/head-down/monitor/blob/master/LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?style=flat-square&logo=windows)](https://github.com/head-down/monitor)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue?style=flat-square&logo=python)](https://www.python.org/)
[![Status](https://img.shields.io/badge/status-working-brightgreen?style=flat-square)](https://github.com/head-down/monitor)

基于 OpenCV DNN 人脸检测的实时监控工具。检测到多人靠近时自动切换到 IDE，避免社死。

## 星标趋势

[![Star History Chart](https://api.star-history.com/svg?repos=head-down/monitor&type=Date)](https://star-history.com/#head-down/monitor&Date)

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

## 许可证

MIT License - 仅供学习娱乐，摸鱼有风险，下班需努力。
