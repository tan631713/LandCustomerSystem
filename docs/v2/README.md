# 土地資料系統 v2.0 第一階段

狀態：規格凍結與平台基礎  
正式資料異動：無  
基線：家中伺服器 v1.8.9、公司筆電 v1.8.2、LINE Bot v0.30.0、iPhone PWA 隨伺服器 v1.8.9

## 本階段目標

在不改寫正式 PostgreSQL 與附件庫的前提下，固定 v2.0 的 API、資料庫、權限、相容、測試與回復邊界。第二階段只能依照本資料夾的契約實作；若要變更必須先更新規格與決策紀錄。

## 交付物

- `V2_SPECIFICATION.md`：產品邊界、功能範圍、非目標及完成定義。
- `API_V2_CONTRACT.md`：API v2 路徑、回應格式、分頁、衝突、版本與錯誤契約。
- `SCHEMA_V2_DRAFT.sql`：PostgreSQL schema 8～12 草案；檔案本身禁止直接執行。
- `PERMISSION_MATRIX.md`：桌面、手機、LINE 與背景服務的角色／資料範圍權限。
- `COMPATIBILITY_ROLLBACK.md`：v1 過渡期、最低版本、升級關卡及回復條件。
- `TEST_BASELINE.md`：v1.8.9 的 232 項測試基線及 v2 新增測試門檻。
- `baseline/v1.8.9-baseline.json`：由程式產生的路由、schema、版本與關鍵檔案雜湊快照。
- `tools/v2_baseline_audit.py`：只讀盤點工具，不開啟正式資料庫。

## 第一階段完成條件

1. 現有 92 個 `/api/v1` 路由及兩個公開系統路由已納入基線。
2. PostgreSQL schema 7 與 SQLite 相容 schema 8 已固定。
3. v2 API、標準錯誤、分頁、樂觀鎖與能力協商已定義。
4. schema 8～12 的目的、先後順序與回復邊界已定義。
5. Admin、Editor、Viewer、LINE 權限與背景服務矩陣已完成。
6. 公司筆電 v1.8.2、LINE Bot v0.30.0 與舊 PWA 的相容政策已完成。
7. `python -m unittest discover -s tests -q` 全部通過。
8. 尚未在家中主機執行正式備份與回復演練；此項必須在第二階段開始前由家中主機完成。

## 禁止事項

- 不在此階段修改 `postgres/schema.sql` 或正式資料。
- 不讓手機、桌面或 LINE Bot 直接連 PostgreSQL。
- 不在診斷、稽核或錯誤訊息記錄帳密、DSN、私鑰、完整身分證或查詢內容。
- 不把 v1 寫入永久保留；v2 正式切換後，舊客戶端只提供有限讀取過渡期。
- 不以付費雲端作為 v2 必要相依。

