# 程式碼簽章（通過「智慧型應用程式控制」）

Windows 11 的「智慧型應用程式控制」（Smart App Control）開啟時，會擋下沒有有效數位簽章、且在微軟雲端沒有信譽紀錄的程式，而且會**逐一檢查程式載入的每個執行檔**（.exe、.dll、.pyd），不只安裝檔。要讓本程式在這些電腦上執行，必須用**受信任機構發給的程式碼簽章憑證**簽署所有執行檔；自己產生的憑證不會被採信。

建置流程已經支援簽章：設定好憑證後執行同一個建置指令，就會自動簽署

- 整理工具（Organizer）資料夾裡所有未簽章的 .exe／.dll／.pyd；
- 影像圖書館（Viewer）單一 exe 內含、執行時會解壓縮的所有 .dll／.pyd，以及 exe 本身；
- 安裝檔與解除安裝程式。

已經有有效簽章的第三方檔案（例如 Microsoft 的 VC++ 執行階段）保持原簽章。沒有設定憑證時，建置照常完成，只會提示「未簽章」。

## 1. 取得憑證

| 方式 | 發行者顯示 | 說明 |
|---|---|---|
| 向憑證商購買「程式碼簽章憑證」（OV） | 你或公司的名稱 | 例如 Certum、Sectigo、SSL.com、DigiCert、台灣網路認證（TWCA）。需要身分驗證；私鑰依規定放在 USB 硬體金鑰或憑證商的雲端簽章服務 |
| [SignPath Foundation](https://signpath.org/)（開源專案免費） | SignPath Foundation | 需 OSI 開源授權、在 CI 上自動建置、申請並通過審核 |
| [Microsoft Artifact Signing](https://learn.microsoft.com/azure/artifact-signing/) | 你或公司的名稱 | 官方首選，但個人開發者限美國、加拿大；組織限部分國家，目前不含台灣 |

剛簽章的新版本仍可能短暫出現 SmartScreen 提示，下載量累積後會消失；「智慧型應用程式控制」則只要簽章有效就會放行。

## 2. 設定憑證（擇一）

在執行建置的 PowerShell 視窗設定環境變數：

```powershell
# A. 憑證已安裝在 Windows 憑證存放區（USB 硬體金鑰或雲端簽章服務通常會裝在這裡）
$env:VLO_SIGN_THUMBPRINT = "<憑證指紋 40 個字元>"

# B. .pfx 憑證檔
$env:VLO_SIGN_PFX = "D:\certs\codesign.pfx"
$env:VLO_SIGN_PFX_PASSWORD = "<密碼>"

# C. 使用 signtool.exe 的參數（例如 Artifact Signing 或憑證商指定的工具）
$env:VLO_SIGNTOOL = "C:\Program Files (x86)\Windows Kits\10\bin\<版本>\x64\signtool.exe"
$env:VLO_SIGNTOOL_ARGS = "/dlib <Azure.CodeSigning.Dlib.dll> /dmdf <metadata.json>"
```

選用：`VLO_TIMESTAMP_URL`（時間戳記伺服器，預設 `http://timestamp.digicert.com`，可改用憑證商提供的網址）、`VLO_SIGN_REQUIRED=1`（有任何執行檔未簽章就讓建置失敗，正式發布建議開啟）。

憑證指紋可用 `Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Format-List Subject, Thumbprint` 查詢。密碼與 .pfx 檔請勿提交到 Git。

## 3. 建置與確認

```powershell
$env:VLO_SIGN_REQUIRED = "1"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-desktop.ps1 -BuildId <新的ID>
```

建置記錄會顯示 `code signing: ...` 與 `code signing check: N of N executable files signed`。也可以單獨檢查任何資料夾或檔案：

```powershell
.venv\Scripts\python.exe packaging/codesign.py verify --require dist\<ID>
```

在已開啟「智慧型應用程式控制」的電腦上，對安裝檔按右鍵 →「內容」→「數位簽章」，應看到你的憑證名稱，且安裝與執行不會被擋。

## 實作說明

- `packaging/codesign.py`：簽章與檢查工具（只簽尚未簽章的檔案；有效的第三方簽章保留）。
- `viewer/packaging/VideoLibraryViewer.spec`：打包前把要內含的 .dll／.pyd 複製一份簽章後再打包，不會修改 Python 環境本身。
- 部分 Python 發行版附帶的 Tcl/Tk DLL 留有指向已不存在簽章的欄位，Windows 會拒絕簽署；工具會先清除這個空指標（只影響要打包的複本）。
- `packaging/MediaCatalogVideoDesktop.iss`：有設定憑證時，Inno Setup 透過同一個工具簽署安裝檔與解除安裝程式。
- 已用一張不受信任的測試憑證驗證整個流程：安裝後所有執行檔、解除安裝程式，以及影像圖書館執行時解壓縮的所有檔案都帶有簽章，程式功能正常。
