# -*- mode: python ; coding: utf-8 -*-
import os
import customtkinter
from PyInstaller.utils.hooks import collect_data_files

# 收集 customtkinter 的 assets（主题文件、字体、图标）
_ctk_datas = collect_data_files('customtkinter')

# 额外显式添加 customtkinter 的主题 JSON 文件，防止 collect_data_files 漏收
_ctk_base = os.path.dirname(customtkinter.__file__)
_ctk_datas += [
    (os.path.join(_ctk_base, 'assets', 'themes', f), os.path.join('customtkinter', 'assets', 'themes'))
    for f in os.listdir(os.path.join(_ctk_base, 'assets', 'themes'))
    if f.endswith('.json')
]

a = Analysis(
    ['monitor.py'],
    pathex=[],
    binaries=[],
    datas=[('face_deploy.prototxt', '.'), ('face_res10.caffemodel', '.'), ('monitor_icon.ico', '.')] + _ctk_datas,
    hiddenimports=['customtkinter', 'cv2', 'pygetwindow', 'pyautogui', 'psutil', 'tkinter', 'PIL', 'pystray'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# onedir 模式：EXE 不包含 binaries/datas，由 COLLECT 散布到文件夹
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MoyuGuardian',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=r'd:\DevelopTools\mine\monitor\monitor_icon.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MoyuGuardian',
)
