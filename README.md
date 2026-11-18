# 課堂搶答系統（第一階段）

本機示範活動同步、組別搶答及 Google Sheets 整合。Sheets 功能已使用測試替身驗證，**尚未經真實 Google Sheets API 或人工端到端驗收**；測試題號不會寫入試算表。

## Windows PowerShell 啟動

在 PowerShell 切換至專案根目錄。若這台電腦已有本專案的 `.venv` 且可執行，直接執行以下指令，**不需要 `py`**：

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:BUZZER_SECRET_KEY = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
.\.venv\Scripts\python.exe app.py
```

若 `.venv` 不存在或無法使用，先安裝 Python 3.10 以上並確認 `py --version` 可用，再在專案目錄建立環境：

```powershell
py -m venv .venv
```

接著執行上方四行啟動指令。若 `py` 找不到 Python，但系統已安裝 Python，也可使用該 Python 執行檔的完整路徑加上 `-m venv .venv`。虛擬環境可能依賴建立時的 Python 路徑，搬移專案或移除原 Python 後若無法執行，應重新建立環境。

每次新開 PowerShell 需重新設定金鑰；換金鑰會使既有瀏覽器 session 失效。不要提交金鑰、`.env` 或憑證。資料庫自動建立於 `instance/buzzer.sqlite3`，僅供本機測試。

## 操作

1. 開啟 `http://127.0.0.1:5000/` 選老師。若要用 Sheets，先完成下方設定，貼上試算表網址、確認講義均為單題並匯入，核對顯示的題號與題數；也可輸入以逗號分隔的測試題號。按「開始搶答」。
2. 使用另外兩個互相隔離的瀏覽器設定檔（或不同瀏覽器／無痕視窗），各自開啟同一網址選第 1、2 組。一般同一瀏覽器的普通分頁共用 cookie，不能作為獨立身分。
3. 兩組各自提交非空答案；每題每組只可送出一次。老師可看所有提交；結束前學生只看到自己的提交。
4. 老師按「結束搶答」，各頁每秒更新；學生可查看所有順位與成功答案。系統不判斷答案正確性。使用 Sheets 來源時，老師可按「匯出成功答案」，並檢查原表。

身分選擇僅適用可信任的本機示範，任何人均可自行選老師或其他組；後端會按目前 session 檢查權限，這不等同登入認證。第一版不提供重開活動；如要重做示範，先停止程式並自行備份或移除本機資料庫，再重新啟動。

## Google Sheets 設定與限制

1. 準備可編輯的單題 Guided Notes 副本並保留備份。在 Google Cloud 啟用 Sheets API，使用服務帳戶，將副本分享給服務帳戶的電子郵件並給予編輯權限。
2. 將服務帳戶 JSON 憑證放在**專案目錄之外**；不可提交 Git。啟動前在同一 PowerShell 設定 `$env:GOOGLE_APPLICATION_CREDENTIALS = '憑證的完整路徑'`。此環境變數是本機路徑，勿貼出金鑰內容。
3. 在每題答案格填入 `{{Q1}}`、`{{Q2}}` 等完整標記，數字依實際題號決定且不得重複。合併答案格請放在左上角。不同題數、題號及位置皆可，系統動態掃描整份試算表。
4. 第一版不支援題組。**系統無法可靠辨識所有題組與未標記題目**，必須由老師確認均為單題、逐題標記並核對匯入結果；勿匯入題組。若助教不允許事先加標記，現行格式不適用，需先修訂規格。
5. 從匯入到匯出期間不要變更標記或合併範圍；匯出前系統重新檢查，且只寫入有成功答案的格。讀取與寫入之間仍可能有外部編輯競態，匯出時請勿同時編輯。若顯示結果不明，請先檢查試算表，不要盲目重試。

無法存取時，檢查網路、ID、API 啟用狀態、憑證環境變數及試算表分享權限。此流程仍須在真正的 Google Sheets 副本上人工驗證，包含合併格與權限。

## 測試

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

真正 Google Sheets 存取與寫回、範本格式及助教是否允許事前標記，仍待人工確認。
