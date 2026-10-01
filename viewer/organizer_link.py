# -*- coding: utf-8 -*-
"""
直接讀取 Video Library Organizer 的分析資料庫（媒體整理成果\\catalog.sqlite）。
- 只以唯讀模式開啟，不寫入 Organizer 的資料庫
- 欄位內容的產生方式必須與 Organizer 寫 Excel 時一致（media_catalog/excel_catalog.py）
- 人工修改仍寫回 Excel；Organizer 重建 Excel 時會依隱藏工作表 _organizer_baseline 保留這些修改
"""
import json
import ntpath
from contextlib import contextmanager
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

RESULT_DIR = "媒體整理成果"
DB_NAME = "catalog.sqlite"
BASELINE_SHEET = "_organizer_baseline"

# Organizer 的狀態與媒體類型標籤（對應 excel_catalog._STATUS_LABELS / _MEDIA_LABELS）
STATUS_LABELS = {
    "pending": "待處理",
    "processing": "處理中",
    "analyzed": "待確認",
    "completed": "完成",
    "skipped": "略過",
    "failed": "失敗",
    "missing": "來源已移除",
}
OWN_STATUS_LABELS = frozenset(STATUS_LABELS.values())
MEDIA_LABELS = {
    "image/jpeg": "照片 (JPEG)",
    "image/png": "照片 (PNG)",
    "image/webp": "照片 (WebP)",
    "image/heic": "照片 (HEIC)",
    "video/mp4": "影片 (MP4)",
    "video/quicktime": "影片 (MOV)",
    "video/x-matroska": "影片 (MKV)",
    "video/webm": "影片 (WebM)",
}

# 人工修改會被 Organizer 保留的欄位（Excel 欄位名稱 → 面板欄位）
CONTENT_FIELDS = {"狀態": "status", "內容描述": "description", "重點": "highlights",
                  "關鍵字": "keywords", "拍攝時間": "shot_time"}
# 由 Organizer 依實際檔案與分析紀錄產生、每次重建都會重寫的欄位
OWNED_FIELDS = ("filename", "media_type", "processed_time", "md_path", "backup_path", "error")


def _text(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        v = v.isoformat()
    s = str(v).strip()
    return s or None


def path_key(p):
    """Organizer 以完整路徑（不分大小寫）對應同一部影片"""
    return (p or "").casefold()


def is_human_value(field, value):
    """空白與 Organizer 自己的狀態標籤不算人工修改（與 Organizer 的判斷一致）"""
    if value is None:
        return False
    return not (field == "status" and value in OWN_STATUS_LABELS)


def find_catalog(folder):
    """
    由使用者給的資料夾找出 Organizer 的成果：可以是來源資料夾或其中的「媒體整理成果」。
    回傳 (excel 路徑, 資料庫路徑)；找不到回傳 None
    """
    folder = Path(folder)
    result = folder if folder.name.casefold() == RESULT_DIR.casefold() else folder / RESULT_DIR
    db_path = result / DB_NAME
    if not db_path.is_file():
        return None
    legacy = result / "媒體清冊.xlsx"
    excel = legacy if legacy.is_file() else result / f"{result.parent.name}_媒體清冊.xlsx"
    if not excel.is_file():
        found = sorted(result.glob("*_媒體清冊.xlsx"))
        if len(found) != 1:
            return None
        excel = found[0]
    return str(excel.resolve()), str(db_path.resolve())


def database_beside(excel_path):
    """Excel 清冊旁邊若有 Organizer 的資料庫則回傳其路徑"""
    if not excel_path:
        return None
    p = Path(excel_path).parent / DB_NAME
    if not p.is_file():
        return None
    try:
        with _connect(p) as conn:
            conn.execute("SELECT 1 FROM media_records LIMIT 1")
    except sqlite3.Error:
        return None
    return str(p.resolve())


def _uri(path):
    p = str(Path(path).resolve()).replace("\\", "/")
    if p.startswith("//"):  # 網路路徑：file:////server/share/...
        return "file://" + quote(p, safe="/:") + "?mode=ro"
    return "file:///" + quote(p, safe="/:") + "?mode=ro"


@contextmanager
def _connect(path):
    conn = sqlite3.connect(_uri(path), uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def db_stamp(path):
    """資料庫（含交易日誌）最後修改時間；用來判斷 Organizer 是否寫入了新資料"""
    stamp = 0.0
    for p in (path, path + "-journal", path + "-wal"):
        try:
            stamp = max(stamp, os.path.getmtime(p))
        except OSError:
            pass
    return stamp


def _timestamp(v):
    try:
        t = datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.timestamp()


def read_records(path):
    """
    讀取 Organizer 的分析紀錄，回傳 {path_key: {欄位: 值, "_updated": 時間戳}}，
    內容與 Organizer 寫進 Excel 的一致（不含已移除的來源）
    """
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT normalized_path, media_type, status, description, highlights_json, keywords_json, "
            "error, markdown_path, backup_path, updated_at FROM media_records "
            "WHERE status <> 'missing' ORDER BY updated_at, rowid").fetchall()
    out = {}
    for r in rows:
        full = r["normalized_path"]
        out[path_key(full)] = {
            "full_path": full,
            "filename": ntpath.basename(full),
            "status": STATUS_LABELS.get(r["status"], r["status"]),
            "media_type": MEDIA_LABELS.get(r["media_type"], r["media_type"]),
            "description": _text(r["description"]),
            "highlights": _text("；".join(json.loads(r["highlights_json"] or "[]"))),
            "keywords": _text("、".join(json.loads(r["keywords_json"] or "[]"))),
            "shot_time": None,
            "processed_time": _text(r["updated_at"]) if r["status"] in ("analyzed", "completed") else None,
            "md_path": _text(r["markdown_path"]),
            "backup_path": _text(r["backup_path"]),
            "error": _text(r["error"]),
            "_updated": _timestamp(r["updated_at"]),
        }
    return out


def read_baseline(wb):
    """
    讀取 Organizer 上次寫入 Excel 的值（隱藏工作表）。回傳 {path_key: {欄位: 值}}；
    舊版清冊沒有這張表時回傳 None
    """
    if BASELINE_SHEET not in wb.sheetnames:
        return None
    fields = list(CONTENT_FIELDS.values())
    out = {}
    for row in wb[BASELINE_SHEET].iter_rows(min_row=2, values_only=True):
        if row and row[0]:
            cells = list(row[1:]) + [None] * len(fields)
            out[str(row[0])] = {f: _text(cells[i]) for i, f in enumerate(fields)}
    return out
