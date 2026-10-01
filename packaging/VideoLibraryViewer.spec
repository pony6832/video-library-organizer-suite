# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 規格檔：單一 exe，網頁檔案內嵌；資料與設定存放在 exe 旁的 data/ 與 config.json
import os
from PyInstaller.utils.hooks import collect_submodules

root = os.path.dirname(SPECPATH)
pk = os.path.join(root, "packaging")
hidden = collect_submodules("uvicorn") + ["excel_sync", "pythoncom", "pywintypes", "win32com.client"]

a = Analysis(
    [os.path.join(root, "server.py")],
    pathex=[root],
    datas=[(os.path.join(root, "static"), "static")],
    hiddenimports=hidden,
    excludes=["tkinter", "PIL", "numpy", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="VideoLibraryViewer",
    icon=os.path.join(pk, "app.ico"),
    version=os.path.join(pk, "version.txt"),
    console=True,
    upx=False,
)
