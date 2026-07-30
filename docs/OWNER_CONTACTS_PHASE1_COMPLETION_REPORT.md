# 地主關係人管理 Phase 1 強化版完成報告

正式版本：

- 家中伺服器：v1.9.24
- 公司筆電客戶端：v1.9.1
- PostgreSQL：schema 10

## 1. 資料庫修改

### 資料表與欄位

- `contacts`：姓名、手機、市話、戶籍地址、聯絡地址、工作地址、身分補充、
  人員備註、啟用狀態及建立／更新時間。
- `owner_contact_relations`：地主、關係人、關係類型、關係補充、主要狀態、
  排序、關係備註、啟用狀態、停用時間、停用者及建立／更新時間。

### 索引、外鍵與唯一限制

- owner、contact、deactivated_by 均有外鍵。
- 姓名、手機、市話、戶籍地址、聯絡地址、正規化電話、地主、排序、狀態及
  停用者索引已建立。
- 同一地主與同一 contact 只能有一筆啟用關係。
- 每位地主最多一位啟用中的主要關係人。

### Migration 與 rollback

- 建立 Phase 1：schema version 9。
- 強化地址、電話搜尋及停用資料：schema version 10。
- 強化 rollback：`postgres/migrations/010_owner_contacts_enhancement_rollback.sql`
- 完整 Phase 1 rollback：`postgres/migrations/009_owner_contacts_rollback.sql`

schema 10 會先將舊 `address` 保存到戶籍地址，再移除舊欄位。兩份 rollback
均隨正式伺服器包交付。

## 2. FastAPI 伺服器修改

資料流：

```text
Windows UI
  → DesktopApiRecordRepository
  → DesktopApiClient HTTPS
  → FastAPI routes
  → OwnerContactService
  → PostgreSQL repositories
  → PostgreSQL schema 10
```

### 新增及強化模組

- `customer_api/owner_contact_schemas.py`：全部 payload、長度及條件驗證。
- `customer_api/routes_owner_contacts.py`：新舊相容 API 與統一錯誤格式。
- `customer_api/owner_contact_service.py`：交易內商業規則及審計事件。
- `customer_api/postgres_owner_contacts.py`：SQL Repository、電話正規化搜尋、
  重複評分、樂觀鎖定及 transaction。

### 伺服器負責事項

- Viewer／Editor／Admin 權限。
- 地主、contact、relation 存在與歸屬檢查。
- 新增、連結、編輯、停用、重新啟用 transaction。
- 電話忽略常見符號搜尋及地址部分搜尋。
- 高度疑似與同名弱提示，不自動合併。
- 重複有效 relation 檢查。
- 主要關係人唯一性、自動取消舊主要關係人。
- 停用時清除主要狀態並寫入時間與使用者。
- 重新啟用時不恢復主要狀態。
- `updated_at` 樂觀鎖定及 HTTP 409 併發衝突。
- 新增、連結、共用資料修改、關係修改、主要切換、停用與恢復審計。

## 3. API 清單

正式 owner API：

| 方法 | 路徑 |
|---|---|
| GET | `/api/v1/owners/{owner_id}/contacts` |
| POST | `/api/v1/owners/{owner_id}/contacts` |
| POST | `/api/v1/owners/{owner_id}/contacts/link` |
| GET | `/api/v1/owners/{owner_id}/contacts/{relation_id}` |
| PUT | `/api/v1/owners/{owner_id}/contacts/{relation_id}` |
| POST | `/api/v1/owners/{owner_id}/contacts/{relation_id}/deactivate` |
| POST | `/api/v1/owners/{owner_id}/contacts/{relation_id}/reactivate` |
| GET | `/api/v1/contacts/search` |
| POST | `/api/v1/contacts/duplicate-check` |

Windows v1.9.1 仍可使用既有
`/api/v1/records/{record_id}/owner-contacts` 相容路徑；兩組路徑共用同一個
Service 與 Repository，不是平行資料架構。

## 4. Windows 客戶端修改

- 地主詳細頁保留「關係人」分頁。
- 表格顯示主要、姓名、組合後關係、手機、市話、戶籍地址、聯絡地址、
  身分補充及狀態。
- 長地址限制欄寬並以 tooltip 顯示完整內容。
- 空資料顯示明確說明。
- 新增／編輯 Dialog 分開共用資料與目前地主關係。
- 三種地址、身分補充、地址快速填入、共用資料警告及地主連結數已完成。
- 雙擊開啟唯讀詳細資料；Editor／Admin 可再選擇編輯。
- 複製電話優先手機；多個電話可選擇。
- 複製地址優先聯絡、戶籍、工作地址；多個地址可選擇。
- 停用 Dialog 可填寫停用說明。
- Viewer 可查看及複製，但所有寫入按鈕停用。
- 客戶端沒有 SQL、psycopg 或 `customer_api` import。

## 5. 測試結果

- 強化核心、架構與交付測試：61 項通過。
- 完整系統回歸：360 項通過，0 失敗，0 跳過。
- Migration：欄位、索引、外鍵、唯一限制、version 10、transaction rollback。
- Repository：三種地址、部分搜尋、電話正規化、重複分級、排序、停用及恢復。
- Service：共用資料同步、關係隔離、主要切換、停用不影響其他地主及審計。
- FastAPI：Viewer／Editor 權限、正式 owner API、相容 API、404／409／422。
- Windows UI：空資料、長地址 tooltip、複製優先順序、唯讀權限、地主切換。
- 分層守門：Windows UI 及 API Client 不得直接操作 PostgreSQL。
- EXE 隔離驗收：13 項通過。
- 正式伺服器與客戶端 ZIP：SHA-256 核對通過。

## 6. 未完成項目

Phase 1 強化補充規格內未完成項目為 0。

聯絡歷程、提醒、導航、手機外勤、LINE Bot、家族樹、照片、永久刪除、
自動合併、Excel 匯入匯出及全域管理中心均依規格排除。
