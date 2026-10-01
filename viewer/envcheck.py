# -*- coding: utf-8 -*-
"""
環境檢查與 ffmpeg 自動安裝。
- check_all(): 回傳各項檢查結果，供主控台與網頁「環境檢查」面板顯示
- FfmpegInstaller: 從官方來源下載 ffmpeg，驗證 SHA-256 後安裝到程式資料夾（不需系統管理員權限）
"""
import hashlib
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# 依序嘗試；每個來源都有 SHA-256 校驗碼。GitHub 的 CDN 通常快很多，因此優先使用
FFMPEG_SOURCES = [
    {
        "name": "gyan.dev 官方 GitHub（GyanD/codexffmpeg）",
        "github_repo": "GyanD/codexffmpeg",
        "asset_re": r"^ffmpeg-[\d.]+-essentials_build\.zip$",
    },
    {
        "name": "GitHub BtbN/FFmpeg-Builds",
        "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "sha256_url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256",
    },
    {
        "name": "gyan.dev 網站",
        "url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "sha256_url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256",
    },
]
SLOW_AFTER_S = 30          # 下載 30 秒後
SLOW_BYTES_PER_S = 200_000  # 平均低於 200 KB/s 就改用下一個來源（最後一個來源不會中止）


class SlowSource(Exception):
    pass
UA = {"User-Agent": "VideoLibraryViewer/1.1 (+https://github.com/pony6832/video-library-organizer-suite)"}


def _open(url, timeout=30):
    # urllib 會自動使用 Windows 的系統 Proxy 設定（公司網路常見）
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def tool_version(path):
    try:
        r = subprocess.run([path, "-version"], capture_output=True, timeout=15, creationflags=NO_WINDOW)
        first = r.stdout.decode("utf-8", "replace").splitlines()[0] if r.returncode == 0 and r.stdout else ""
        m = re.search(r"version\s+(\S+)", first)
        return m.group(1) if m else (first[:40] or None)
    except Exception:
        return None


def writable(d):
    try:
        Path(d).mkdir(parents=True, exist_ok=True)
        t = Path(d) / f".write_test_{os.getpid()}"
        t.write_text("ok")
        t.unlink()
        return True
    except OSError:
        return False


def port_free(port, host="127.0.0.1"):
    with socket.socket() as s:
        return s.connect_ex((host, port)) != 0


def excel_installed():
    if sys.platform != "win32":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application\CLSID"))
        return True
    except OSError:
        return False


def long_paths_enabled():
    if sys.platform != "win32":
        return True
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem")
        v, _ = winreg.QueryValueEx(k, "LongPathsEnabled")
        return bool(v)
    except OSError:
        return False


def item(key, label, status, detail, action=None):
    """status: ok / warn / error / info"""
    return {"key": key, "label": label, "status": status, "detail": detail, "action": action}


def check_all(ctx):
    """
    ctx: {"home": 程式資料夾, "base": exe 所在資料夾, "ff": 尋找工具的函式, "port": 埠號,
          "media_total": n, "media_available": n, "max_path_len": n, "home_fallback": bool}
    """
    out = []
    # 作業系統
    ver = platform.platform()
    bits = platform.architecture()[0]
    is_win = sys.platform == "win32"
    win_ok = is_win and (sys.getwindowsversion().major >= 10)
    out.append(item("os", "作業系統", "ok" if win_ok and bits == "64bit" else "warn",
                    f"{ver}（{bits}）" + ("" if win_ok else "；建議使用 Windows 10／11 64 位元")))

    # 程式資料夾
    home = ctx["home"]
    if ctx.get("home_fallback"):
        out.append(item("home", "資料存放位置", "warn",
                        f"程式所在資料夾無法寫入，資料改存到 {home}。若要攜帶使用，請把程式放到可寫入的資料夾（例如 D:\\影像圖書館）"))
    else:
        out.append(item("home", "資料存放位置", "ok", str(home)))

    # 磁碟空間
    try:
        free = shutil.disk_usage(home).free
        gb = free / 1024 ** 3
        out.append(item("disk", "磁碟可用空間", "ok" if gb >= 2 else "warn",
                        f"{gb:.1f} GB" + ("" if gb >= 2 else "；空間不足時無法產生縮圖與代理檔")))
    except OSError:
        pass

    # ffmpeg / ffprobe
    for name, use in (("ffmpeg", "產生縮圖、預覽與轉檔代理檔"), ("ffprobe", "讀取時長、解析度與編碼")):
        p = ctx["ff"](name)
        found = os.path.isfile(p) or bool(shutil.which(p))
        v = tool_version(p) if found else None
        if v:
            out.append(item(name, name, "ok", f"版本 {v}（{p if os.path.isfile(p) else shutil.which(p)}）"))
        else:
            out.append(item(name, name, "error", f"未安裝，無法{use}。可按「自動下載安裝」一鍵安裝", "install_ffmpeg"))

    # Excel
    out.append(item("excel", "Microsoft Excel", "ok" if excel_installed() else "info",
                    "已安裝：清冊在 Excel 中開啟時也能直接寫入" if excel_installed()
                    else "未安裝（不影響使用）：清冊被其他程式開啟時，修改會等檔案關閉後再寫入"))

    # 長路徑
    mpl = ctx.get("max_path_len") or 0
    lp = long_paths_enabled()
    if mpl > 250 and not lp:
        out.append(item("longpath", "長路徑支援", "warn",
                        f"清冊中最長的路徑有 {mpl} 個字元，超過 Windows 預設的 260 字元上限，這些檔案可能讀不到。請 IT 開啟「LongPathsEnabled」"))
    else:
        out.append(item("longpath", "長路徑支援", "ok" if lp else "info",
                        "已開啟" if lp else f"未開啟（目前清冊最長路徑 {mpl} 字元，不受影響）"))

    # 影片可存取
    t, a = ctx.get("media_total", 0), ctx.get("media_available", 0)
    if t:
        out.append(item("media", "影片檔案存取", "ok" if a == t else ("warn" if a else "error"),
                        f"{a} / {t} 個檔案可讀取" + ("" if a == t else "；請確認已連上網路磁碟，或到「設定 → 路徑對應」調整"),
                        None if a == t else "open_settings"))
    else:
        out.append(item("media", "影片檔案存取", "info", "尚未匯入清冊"))

    # 網路服務
    out.append(item("port", "網頁服務", "ok", f"http://127.0.0.1:{ctx['port']}/"))

    # 桌面捷徑
    if getattr(sys, "frozen", False):
        lnk = desktop_dir() / "影像圖書館.lnk"
        out.append(item("shortcut", "桌面捷徑", "ok" if lnk.exists() else "info",
                        "已建立" if lnk.exists() else "尚未建立，可按「建立捷徑」方便下次開啟",
                        None if lnk.exists() else "create_shortcut"))
    return out


def summarize(items):
    if any(i["status"] == "error" for i in items):
        return "error"
    if any(i["status"] == "warn" for i in items):
        return "warn"
    return "ok"


def desktop_dir():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        v, _ = winreg.QueryValueEx(k, "Desktop")
        return Path(os.path.expandvars(v))
    except OSError:
        return Path.home() / "Desktop"


def create_shortcut(target, workdir, icon=None):
    """在桌面建立「影像圖書館」捷徑"""
    lnk = desktop_dir() / "影像圖書館.lnk"
    try:
        import pythoncom
        import win32com.client
        def _make():  # COM 物件須在 CoUninitialize 之前釋放，因此包在函式內
            s = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(lnk))
            s.TargetPath = str(target)
            s.WorkingDirectory = str(workdir)
            s.IconLocation = str(icon or target)
            s.Description = "影像圖書館 媒體清冊檢視面板"
            s.Save()

        pythoncom.CoInitialize()
        try:
            _make()
        finally:
            pythoncom.CoUninitialize()
    except ImportError:
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
              f"$s.TargetPath='{target}';$s.WorkingDirectory='{workdir}';$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, creationflags=NO_WINDOW)
    return str(lnk)


class FfmpegInstaller:
    """背景下載並安裝 ffmpeg 到 <dest>/bin/"""

    def __init__(self, dest, on_done=None):
        self.dest = Path(dest)
        self.on_done = on_done
        self.state = {"state": "idle"}
        self._t = None

    def status(self):
        return dict(self.state)

    def start(self):
        if self._t and self._t.is_alive():
            return self.status()
        self.state = {"state": "running", "phase": "準備下載", "progress": 0.0, "downloaded": 0, "total": 0,
                      "source": "", "errors": []}
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self.status()

    def _run(self):
        errors = []
        for n, src in enumerate(FFMPEG_SOURCES):
            try:
                self.state.update(source=src["name"], phase="取得校驗碼", progress=0.0, downloaded=0, total=0, speed=0)
                url, expected = self._resolve(src)
                zpath = self._download(url, expected, allow_slow=(n == len(FFMPEG_SOURCES) - 1))
                self.state.update(phase="解壓縮")
                self._extract(zpath)
                try:
                    os.remove(zpath)
                except OSError:
                    pass
                self.state.update(phase="驗證")
                v = tool_version(str(self.dest / "bin" / "ffmpeg.exe"))
                if not v or not tool_version(str(self.dest / "bin" / "ffprobe.exe")):
                    raise RuntimeError("安裝後無法執行 ffmpeg")
                self.state = {"state": "done", "phase": "完成", "progress": 1.0, "version": v,
                              "path": str(self.dest / "bin"), "source": src["name"]}
                if self.on_done:
                    self.on_done()
                return
            except Exception as e:  # 含 SlowSource：記錄後改用下一個來源
                errors.append(f"{src['name']}：{e}")
                self.state["errors"] = errors
        self.state = {"state": "error", "phase": "失敗", "errors": errors,
                      "msg": "自動下載失敗。可能是公司網路封鎖了下載，請改用手動安裝（見說明）。"}

    def _resolve(self, src):
        """回傳 (下載網址, 預期 SHA-256)"""
        if src.get("github_repo"):
            import json
            with _open(f"https://api.github.com/repos/{src['github_repo']}/releases/latest") as r:
                rel = json.loads(r.read().decode("utf-8"))
            for a in rel.get("assets", []):
                if re.match(src["asset_re"], a.get("name", "")):
                    dg = (a.get("digest") or "").lower()
                    if not re.fullmatch(r"sha256:[0-9a-f]{64}", dg):
                        raise RuntimeError("發行版本沒有提供校驗碼")
                    return a["browser_download_url"], dg.split(":", 1)[1]
            raise RuntimeError("找不到可用的 ffmpeg 壓縮檔")
        return src["url"], self._expected_sha(src)

    def _expected_sha(self, src):
        with _open(src["sha256_url"]) as r:
            text = r.read().decode("utf-8", "replace")
        fname = src["url"].rsplit("/", 1)[-1]
        for line in text.splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            if len(parts) == 1 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                return parts[0].lower()
            if len(parts) >= 2 and parts[-1].lstrip("*") == fname and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                return parts[0].lower()
        raise RuntimeError("找不到校驗碼")

    def _download(self, url, expected, allow_slow=False):
        self.dest.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".zip", prefix="ffmpeg_", dir=self.dest)
        os.close(fd)
        h = hashlib.sha256()
        self.state.update(phase="下載中")
        try:
            with _open(url, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                self.state["total"] = total
                done, t0 = 0, time.time()
                while True:
                    chunk = r.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    el = max(time.time() - t0, 0.001)
                    self.state.update(downloaded=done, progress=(done / total) if total else 0,
                                      speed=done / el)
                    if not allow_slow and el > SLOW_AFTER_S and done / el < SLOW_BYTES_PER_S \
                            and (not total or done < total * 0.8):
                        raise SlowSource(f"下載速度過慢（{done / el / 1024:.0f} KB/s），改用下一個來源")
            if h.hexdigest() != expected:
                raise RuntimeError("檔案校驗失敗（SHA-256 不符），已捨棄")
            return tmp
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def _extract(self, zpath):
        bindir = self.dest / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        want = {"ffmpeg.exe", "ffprobe.exe"}
        got = set()
        with zipfile.ZipFile(zpath) as z:
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                base = name.rsplit("/", 1)[-1]
                if base.lower() in want and "/bin/" in "/" + name:
                    with z.open(info) as src, open(bindir / base.lower(), "wb") as out:
                        shutil.copyfileobj(src, out)
                    got.add(base.lower())
                elif base.upper().startswith("LICENSE") and name.count("/") <= 1:
                    with z.open(info) as src, open(self.dest / base, "wb") as out:
                        shutil.copyfileobj(src, out)
        if got != want:
            raise RuntimeError("壓縮檔內找不到 ffmpeg.exe / ffprobe.exe")
