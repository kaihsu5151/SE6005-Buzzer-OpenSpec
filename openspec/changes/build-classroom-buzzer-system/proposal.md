# Proposal

## Why

課堂以紙本收回與黑板作答進行搶答耗費時間。建立本機可展示的多人搶答系統，讓老師使用 Google Sheets 學習單並同步主持活動。

## What Changes

- 提供老師與學生組別入口、後端權限檢查、活動開始與結束及每秒狀態同步。
- 依題目與組別提交不可修改的非空答案，按伺服器接受順序計算各題順位，不判斷正確性。
- 老師隨時檢視所有提交；學生於結束前只見本組資訊，結束後查看全部結果。
- 動態匯入 Google Sheets 題目與答案格位置，將成功答案寫回原表，保留未作答格及其他內容。
- 僅涵蓋正式需求核心；題組、CSV 與公平順位等額外功能不在第一版範圍。

## Capabilities

### New Capabilities

- `activity-control`: 角色、組別、活動階段同步與資料可見性。
- `group-buzzing`: 組別答案提交、並行順位與結果。
- `guided-notes`: Google Sheets 動態匯入及安全寫回。

### Modified Capabilities

無。

## Impact

新增 Flask、SQLite、本機瀏覽器介面及 Google Sheets API 整合；需要外部授權、測試與操作說明。已檢視兩份本機 Excel 範本的儲存格與合併結構；Google Sheets 原始表及 API 讀寫、授權與合併格行為尚未驗證。範本未包含本設計的題目標記，匯入前需準備格式；助教能否配合此步驟仍待確認。
