# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 規格檔：單一 exe，網頁檔案內嵌；資料與設定存放在 exe 旁的 data/ 與 config.json
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

root = os.path.dirname(SPECPATH)
pk = os.path.join(root, "packaging")
hidden = collect_submodules("uvicorn") + ["excel_sync", "organizer_link", "pythoncom", "pywintypes", "win32com.client"]

a = Analysis(
    [os.path.join(root, "server.py")],
    pathex=[root],
    datas=[(os.path.join(root, "static"), "static")],
    hiddenimports=hidden,
    excludes=["tkinter", "PIL", "numpy", "pytest"],
)
# 單一 exe 執行時會把內含的 dll／pyd 解壓縮後載入，「智慧型應用程式控制」會逐一檢查，
# 因此有設定簽章憑證時，先簽好這些檔案的複本再打包（見倉庫根目錄 packaging/codesign.py）
sys.path.insert(0, os.path.join(root, "..", "packaging"))
try:
    import codesign
except ImportError:  # 單獨取出 viewer 資料夾建置時沒有簽章工具
    codesign = None
if codesign is not None and codesign.configured():
    a.binaries = codesign.signed_toc(a.binaries, os.path.join(root, "build", "signed-binaries"))
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="VideoLibraryViewer",
    icon=os.path.join(pk, "app.ico"),
    version=os.path.join(pk, "version.txt"),
    console=True,
    upx=False,
)
