# Video Library Viewer 影像圖書館

把 [Video Library Organizer](https://github.com/pony6832/video-library-organizer) 產生的「媒體清冊」Excel，變成可以瀏覽、搜尋、挑選和播放的影像圖書館總目錄。清冊的每個欄位都能直接編輯，修改會即時寫回原始 Excel。

<img src="packaging/app.png" width="96" alt="icon">

## 下載與執行（免安裝 Python）
1. 到 [Releases](../../releases) 下載 `VideoLibraryViewer.exe`
2. 把它放在任一資料夾（例如 `D:\影像圖書館\`）後雙擊執行。程式會開一個主控台視窗，並自動開啟瀏覽器 `http://127.0.0.1:8765/`
3. 點「匯入清冊」，輸入 Excel 路徑，或直接把 Excel 拖曳到網頁上

- 關閉主控台視窗就會結束程式。程式已在執行時再雙擊一次，只會開啟瀏覽器
- 資料庫、縮圖快取、Excel 備份放在 exe 旁邊的 `data\`；設定存在 `config.json`。整個資料夾搬到別處也能繼續使用
- 要讓區網其他電腦連線：執行 `LAN-share.bat`（或 `VideoLibraryViewer.exe --host 0.0.0.0`），對方開啟 `http://你的IP:8765/`
- 其他參數：`--port 8765`、`--import 清冊.xlsx`、`--no-browser`

### ffmpeg（縮圖、預覽、讀取時長、轉檔代理檔需要）
exe 會依序尋找：exe 旁的 `ffmpeg\bin\ffmpeg.exe` → exe 旁的 `ffmpeg.exe` → 系統 PATH。
沒有 ffmpeg 也能瀏覽清冊和播放影片，只是沒有縮圖和技術資訊。安裝方式擇一：
- `winget install Gyan.FFmpeg`
- 從 <https://www.gyan.dev/ffmpeg/builds/> 下載 essentials 版，解壓縮後把資料夾改名為 `ffmpeg`，放在 exe 旁邊

## 功能
**總目錄**
- 格狀檢視：縮圖、時長、狀態、描述、關鍵字；滑鼠在縮圖上左右移動可預覽整段影片
- 清單檢視：Excel 全部欄位加上技術資訊，點欄位標題可排序
- 全文搜尋（`/` 鍵），符合的文字會標示出來；左側可依資料夾、狀態、已挑選、標記點、媒體類型、關鍵字篩選
- 可多選後批次挑選、改狀態、加入或移除關鍵字、匯出、播放

**播放器**
- 進度條懸停會顯示畫面預覽；可逐格前進後退，J／K／L 倒轉與快轉變速，速度 0.25×～8×
- 時間碼 HH:MM:SS:FF、A-B 區段循環、整段循環、自動播放下一部、播放清單
- 標記點（可記錄入點→出點）、擷取畫面存成 PNG、全螢幕、子母畫面、記住上次播放位置
- 遇到瀏覽器不支援的編碼（例如 4:2:2 10-bit），可一鍵產生 H.264 代理檔再播放
- 按 `?` 可查看全部快捷鍵

**編輯與寫回 Excel**
- 播放器右側按「✎ 編輯所有欄位」，或在單一欄位上按「✎ 編輯」。關鍵字和重點用標籤方式編輯：按 Enter 新增、按 ✕ 刪除、雙擊修改
- 清單檢視中，雙擊儲存格就能直接修改
- 「全部關鍵字」視窗可以重新命名、合併或刪除關鍵字，套用到所有媒體
- 每次修改都有紀錄，可以逐筆還原
- 只寫入被修改的儲存格；每份清冊第一次寫入前會先備份到 `data\backups\`
- Excel 正開著這份清冊時：若有安裝 Microsoft Excel，會直接寫入那個已開啟的視窗；否則修改會先排隊，等你關閉 Excel 後自動寫入
- 在 Excel 裡改過內容後，按「重新載入」即可把變更套用到面板

> 與 Organizer 一起使用時請注意：Organizer 批次結束時會從它自己的 SQLite 重建 Excel。如果用面板修改清冊後，又用 Organizer 重新分析同一份清冊，面板寫入的修改可能會被覆蓋。

## 路徑對應
如果影片的實際位置和清冊上的路徑不同（例如網路磁碟已對應成 `Z:\`），到「⚙ 設定 → 路徑對應」新增規則，例如 `\\192.168.1.10\` → `Z:\`。

## 從原始碼執行／自行建置
```powershell
python -m pip install -r requirements.txt
python server.py --open                                         # 開發模式
powershell -ExecutionPolicy Bypass -File packaging\build.ps1    # 建置 dist\VideoLibraryViewer.exe
```
需要 Python 3.10 以上。`packaging/github-actions-build.yml` 是 GitHub Actions 自動建置與冒煙測試的設定，複製到 `.github/workflows/` 即可啟用。

## 專案結構
```
server.py      後端（FastAPI）：匯入、目錄、串流、縮圖、代理檔、編輯 API
excel_sync.py  寫回 Excel（openpyxl／Excel COM）
static/        前端（原生 JavaScript，無建置步驟）
packaging/     PyInstaller 規格、建置腳本、圖示、版本資訊、區網分享啟動檔
```
