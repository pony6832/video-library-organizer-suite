# Video Library Viewer 影像圖書館

影像搜尋資料庫的一部分。把 [Video Library Organizer](../README.md) 產生的「媒體清冊」Excel，變成可以瀏覽、搜尋、挑選和播放的影像圖書館總目錄。清冊的每個欄位都能直接編輯，修改會即時寫回原始 Excel。

<img src="packaging/app.png" width="96" alt="icon">

## 快速上手（不需要安裝 Python、Codex 或 Claude）
1. 到 [Releases](https://github.com/pony6832/video-library-organizer-suite/releases) 下載 `VideoLibraryViewer.exe`
2. 在 D 槽或桌面建立一個資料夾，例如 `D:\影像圖書館\`，把 exe 放進去
   - 不建議放在 `C:\Program Files`。那裡無法寫入，資料會改存到 `%LOCALAPPDATA%\VideoLibraryViewer`
3. 雙擊 `VideoLibraryViewer.exe`
   - 如果出現藍色的「Windows 已保護您的電腦」視窗，按「**其他資訊**」→「**仍要執行**」（程式沒有數位簽章才會出現，只有第一次會問）
4. 程式會先做**環境檢查**，接著自動開啟瀏覽器
5. 第一次使用時，網頁上方會提示「尚未安裝 ffmpeg」。按「**自動下載安裝**」等它跑完（約 110 MB），縮圖和影片資訊就會自動產生
6. 按右上角「**環境檢查**」→「**建立捷徑**」，之後從桌面「影像圖書館」開啟即可
7. 點「匯入清冊」，輸入 Organizer 分析過的影片資料夾或 Excel 路徑，或直接把 Excel 拖曳到網頁上

**日常使用**
- 黑色的主控台視窗就是程式本體，關掉它程式就會結束。程式已在執行時再雙擊一次，只會開啟瀏覽器
- 資料庫、縮圖、Excel 備份、ffmpeg 都放在 exe 旁邊（`data\`、`ffmpeg\`、`config.json`）。整個資料夾複製到別台電腦也能直接用
- 要讓區網其他電腦連線：把 `LAN-share.bat` 放在 exe 旁邊並雙擊，對方開啟 `http://你的IP:8765/`
- 連接埠 8765 被其他程式佔用時，會自動改用下一個可用的連接埠

### 環境檢查
啟動時，主控台會列出檢查結果；網頁右上角「環境檢查」按鈕旁的燈號是綠色／黃色／紅色，點開可以看詳細內容並一鍵處理。

| 項目 | 說明 |
|---|---|
| 作業系統 | 建議 Windows 10／11 64 位元 |
| 資料存放位置 | 程式資料夾不能寫入時，會自動改存到使用者資料夾 |
| 磁碟可用空間 | 少於 2 GB 會提醒（代理檔和縮圖需要空間） |
| ffmpeg／ffprobe | 縮圖、預覽、時長、轉檔代理檔需要；可一鍵自動下載安裝 |
| Microsoft Excel | 有安裝時，清冊開著也能直接寫入；沒安裝也不影響使用 |
| 長路徑支援 | 清冊路徑超過 260 字元又沒開啟長路徑時會提醒 |
| 影片檔案存取 | 顯示清冊中有幾個影片讀得到，讀不到時可到「路徑對應」調整 |
| 桌面捷徑 | 可一鍵建立 |

指令列：`VideoLibraryViewer.exe --check`（只做檢查）、`--install-ffmpeg`（只安裝 ffmpeg）、`--port 8765`、`--host 0.0.0.0`、`--import 清冊.xlsx 或 Organizer 分析過的資料夾`（程式已在執行時，會交給執行中的程式匯入）、`--no-browser`

### ffmpeg 自動安裝的運作方式
- 依序從 [gyan.dev 官方 GitHub](https://github.com/GyanD/codexffmpeg/releases)（約 110 MB）、[GitHub BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) 和 [gyan.dev 網站](https://www.gyan.dev/ffmpeg/builds/) 下載。每個檔案都會以官方提供的 **SHA-256 校驗碼**驗證，不符就捨棄；某個來源太慢（30 秒後低於 200 KB/s）時，會自動改用下一個
- 只會把 `ffmpeg.exe`、`ffprobe.exe` 和授權檔放到程式資料夾的 `ffmpeg\`，不需要系統管理員權限，也不會修改系統 PATH 或登錄檔
- 會自動使用 Windows 的 Proxy 設定。若公司網路擋下載，請手動下載 [ffmpeg-release-essentials.zip](https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip)，解壓縮後把資料夾改名為 `ffmpeg`，放到 exe 旁邊，再按「重新檢查」
- 程式依序在這些位置尋找 ffmpeg：程式資料夾的 `ffmpeg\bin\` → exe 旁的 `ffmpeg.exe` → 系統 PATH

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
- 在 Excel 裡改過內容後，按「重新載入」即可把變更套用到面板（Organizer 清冊會自動重新載入）

## 與 Video Library Organizer 一起使用
- **直接連結分析資料庫**：匯入時輸入 Organizer 分析過的影片資料夾（或其中的「媒體整理成果」資料夾、清冊 Excel），面板會以唯讀方式讀取旁邊的 `catalog.sqlite`。Organizer 每分析完一部影片，幾秒內就會出現在面板上，不必等 Excel 更新，也不必重新匯入；左側清冊卡片會顯示「🔗 已連結 Organizer 資料庫」。面板不會寫入 Organizer 的資料庫
- **修改照舊寫回 Excel**：Organizer 0.3.0 Beta 3 起，重建 Excel 時會保留人工修改。在面板或 Excel 中改過的「狀態」「內容描述」「重點」「關鍵字」「拍攝時間」，以及自行新增的欄位（例如挑選、評等、備註、自訂欄位），即使影片重新分析也以人工修改為準。比對依據是清冊中的隱藏工作表「_organizer_baseline」，請勿刪除
- **Organizer 重建 Excel 後會自動重新載入**，只套用其中的人工修改；尚未寫入 Excel 的面板修改不會被覆蓋
- 檔名、完整路徑、媒體類型、處理時間、Markdown／備份路徑、錯誤原因由 Organizer 產生，面板編輯這些欄位時會顯示提醒
- 空白，或選 Organizer 自己的狀態（待處理、待確認、完成、失敗…）時，會依分析結果顯示，與 Organizer 重建 Excel 時的規則相同
- 1.2.0 以前匯入的 Organizer 清冊，啟動後會自動建立連結
- Organizer 0.3.0 Beta 5 起，安裝 Organizer 時會一併安裝影像圖書館；在 Organizer 按「開啟影像圖書館」就會開啟並連結目前的資料夾。要給沒有裝 Organizer 的同事使用，仍可單獨下載本程式
- 請搭配 Organizer 0.3.0 Beta 4 以上版本；舊版 Organizer（0.3.0 Beta 2 以前）仍會覆蓋面板的修改

## 路徑對應
如果影片的實際位置和清冊上的路徑不同（例如網路磁碟已對應成 `Z:\`），到「⚙ 設定 → 路徑對應」新增規則，例如 `\\192.168.1.10\` → `Z:\`。

## 從原始碼執行／自行建置
```powershell
python -m pip install -r requirements.txt
python server.py --open                                         # 開發模式
powershell -ExecutionPolicy Bypass -File packaging\build.ps1    # 建置 dist\VideoLibraryViewer.exe
```
需要 Python 3.10 以上。每次推送到 `main`（或開 Pull Request）時，GitHub Actions 會自動建置 exe 並測試能否啟動。產出的 exe 可在 [Actions](https://github.com/pony6832/video-library-organizer-suite/actions) 該次執行頁面最下方的 Artifacts 下載（設定檔：倉庫根目錄的 `.github/workflows/viewer.yml`）。

## 專案結構
```
server.py      後端（FastAPI）：匯入、目錄、串流、縮圖、代理檔、編輯 API
excel_sync.py  寫回 Excel（openpyxl／Excel COM）
organizer_link.py  唯讀讀取 Organizer 的分析資料庫與 Excel 比對表
static/        前端（原生 JavaScript，無建置步驟）
packaging/     PyInstaller 規格、建置腳本、圖示、版本資訊、區網分享啟動檔
```
