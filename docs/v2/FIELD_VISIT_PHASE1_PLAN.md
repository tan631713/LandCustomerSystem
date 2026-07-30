# v2.0 手機 Web 外勤模式：Phase 1 分析與實作計畫

更新日期：2026-07-24

## 1. 現況結論

現有手機網站不是獨立系統，而是由 FastAPI 在 `/mobile/` 提供的同源 PWA：

```text
customer_mobile_web/index.html
customer_mobile_web/app.js
customer_mobile_web/styles.css
        ↓ Bearer Token、/api/v1/*
customer_api/app.py
        ↓
PostgreSQLCustomerDataSource
        ↓
PostgreSQL
```

必須保留此入口、登入方式與同源 API。外勤模式直接加入現有手機網站，不建立第二套手機資料庫，也不另外部署一份靜態網站。

## 2. 已確認的既有資料與功能

| 範圍 | 現有實作 | 外勤模式處理方式 |
|---|---|---|
| 地主 | `owners` | 重用，不建立第二份地主資料 |
| 土地 | `lands` | 重用；表內已有土地座標欄位 |
| 所有權 | `ownerships` | 作為桌面「一列資料」及外勤行程的主要關聯 |
| 所有權座標 | `ownership_locations` | 第一階段沿用，支援人工座標；後續補地理編碼狀態 |
| 拜訪紀錄 | `contact_logs` | 重用，手機新增後桌面可直接讀取 |
| 下次追蹤 | `follow_up_reminders` | 重用，拜訪紀錄可同步建立追蹤 |
| 附件 | `attachments` | 重用既有上傳、縮圖、SHA-256 與伺服器儲存 |
| 稽核 | `audit_logs` | 重用，外勤新增與狀態變更寫入相同稽核系統 |
| 登入 | Bearer Token、伺服器端 session | 完全沿用 |
| 角色 | `admin`、`editor`、`viewer` | 第一階段映射成外勤能力，後端仍需逐項驗證 |

### 可直接重用的 API

- 登入、登出及目前使用者：`/api/v1/auth/*`
- 地主、土地與所有權資料查詢
- 拜訪紀錄：`/api/v1/records/{record_id}/contact-logs`
- 下次追蹤
- 附件清單、上傳、縮圖、檢視、更新與刪除
- 所有權座標：`GET /api/v1/record-locations`、`PUT /api/v1/records/{record_id}/location`

### 已發現、後續必須修正的限制

`customer_api/middleware.py` 現在送出 `geolocation=()`，瀏覽器會拒絕手機定位。接上 GPS 的批次必須改為只允許本站使用定位，其他高風險功能繼續禁止。

## 3. 資料庫設計

### 新增資料表

#### `field_visit_routes`

- `id`
- `visit_date`
- `user_id`
- `title`
- `status`
- `start_latitude`
- `start_longitude`
- `total_distance_km`
- `started_at`
- `completed_at`
- `created_at`
- `updated_at`

唯一性建議：同一使用者、同一日期、同一個未封存的今日行程不得重複建立。

#### `field_visit_route_items`

- `id`
- `route_id`
- `owner_id`
- `ownership_id`
- `land_id`
- `route_order`
- `status`
- `priority`
- `is_order_locked`
- `estimated_distance_km`
- `arrived_at`
- `completed_at`
- `postponed_until`
- `note`
- `created_at`
- `updated_at`

唯一性建議：同一行程內的 `ownership_id` 不可重複。

#### `field_visit_status_history`

- `id`
- `route_item_id`
- `old_status`
- `new_status`
- `user_id`
- `latitude`
- `longitude`
- `note`
- `created_at`

### 擴充既有資料表

第一階段不新增另一套地主座標表，改為擴充 `ownership_locations`：

- `geocode_status`
- `geocode_source`
- `geocoded_at`
- `geocode_error`
- `address_fingerprint`

地址變更時以 `address_fingerprint` 判斷舊座標是否失效，並將狀態改為 `pending`。人工座標使用 `manual`，不可被自動地理編碼覆蓋。

附件第一版仍以 `ownership_id` 連回桌面既有附件功能；若需要精確顯示「某次拜訪的照片」，再以可為 NULL 的欄位向後相容擴充：

- `contact_log_id`
- `field_visit_route_item_id`

## 4. 後端模組與 API

### 新增模組

- `customer_api/field_visit_routing.py`：Haversine、最近鄰居、優先、延後、無座標及手動鎖定規則
- `customer_api/postgres_field_visits.py`：行程 repository/data-source mixin
- `customer_api/field_visit_service.py`：狀態轉換、重排、冪等與交易邏輯
- `customer_api/routes_field_visits.py`：外勤 API
- `customer_api/field_visit_permissions.py`：角色到能力的集中映射

### 建議 API 路徑

為避免修改既有 v1 回傳格式，第一階段新增：

- `GET /api/v1/field-visits/today`
- `POST /api/v1/field-visits`
- `GET /api/v1/field-visits/{route_id}`
- `PATCH /api/v1/field-visits/{route_id}`
- `DELETE /api/v1/field-visits/{route_id}`
- `POST /api/v1/field-visits/{route_id}/items`
- `PATCH /api/v1/field-visit-items/{item_id}`
- `DELETE /api/v1/field-visit-items/{item_id}`
- `POST /api/v1/field-visits/{route_id}/reorder`
- `POST /api/v1/field-visits/{route_id}/optimize`
- `POST /api/v1/field-visit-items/{item_id}/start`
- `POST /api/v1/field-visit-items/{item_id}/complete`
- `POST /api/v1/field-visit-items/{item_id}/skip`
- `POST /api/v1/field-visit-items/{item_id}/postpone`

拜訪紀錄與附件優先沿用既有 API，不複製資料模型。

### 防止重複送出

- 建立行程、加入項目、狀態切換、完成拜訪及新增紀錄使用 `Idempotency-Key`。
- 伺服器保存操作結果或建立唯一約束。
- 狀態切換必須在單一資料庫交易內同時寫入目前狀態、狀態歷史與稽核紀錄。
- 完成 API 失敗時，前端不得自動前往下一位。

## 5. 權限設計

第一階段先保留既有三種角色，集中映射能力：

| 能力 | admin | editor | viewer |
|---|---:|---:|---:|
| `field_visit_view` | 是 | 是 | 是 |
| 建立、修改、排序、完成 | 是 | 是 | 否 |
| 上傳附件 | 是 | 是 | 否 |
| 刪除本人附件 | 是 | 是 | 否 |
| 刪除任何附件／外勤管理 | 是 | 否 | 否 |

前端只負責改善操作體驗；真正的權限判斷全部在 API。

## 6. 手機頁面

在現有 `customer_mobile_web` 內新增：

1. 今日外勤首頁
2. 建立／編輯今日行程
3. 行程清單
4. 單一地主外勤主畫面
5. 行程完成摘要

既有的地主／土地搜尋、拜訪紀錄表單、附件相簿及壓縮上傳直接重用。

外勤主畫面固定顯示導航、完成、略過、延後與下一位等單手操作按鈕；沒有座標時以地址產生 Google Maps 網址，地址也空白時禁止導航。

## 7. v1.8.x 相容性風險與控制

| 風險 | 控制方式 |
|---|---|
| 舊桌面端不知道外勤欄位 | 新資料放新表；既有表只加可為 NULL 或有預設值的欄位 |
| 改變既有 API 造成舊客戶端失效 | 只新增 API，不改既有回傳格式 |
| 拜訪／附件各自形成兩套資料 | 強制重用 `contact_logs`、`attachments` |
| 地址變更後沿用錯誤座標 | 地址指紋不同即標記 `pending`，人工座標另有來源 |
| migration 中途失敗 | 單一交易、版本紀錄、約束與索引驗證、測試資料庫先演練 |
| Viewer 可執行寫入 | 每個寫入端點在伺服器驗證能力 |
| 手機重複點擊 | 前端鎖定按鈕＋伺服器冪等 |
| 外勤 GPS 被安全標頭封鎖 | 僅將本站 geolocation 改為允許，不開放相機／麥克風 API |
| 重排覆蓋人工順序 | 鎖定項目保留指定位置；套用前顯示預覽與確認 |

## 8. 小批次實作順序

1. **路線計算核心**：純 Python service 與單元／1,000 筆效能測試，不改資料庫。
2. **migration**：三張外勤表、座標狀態欄位、索引、約束與 rollback 驗證。
3. **repository 與狀態服務**：交易、狀態歷史、稽核、冪等。
4. **API**：今日行程、項目、排序與狀態端點，補完整 API 權限測試。
5. **手機 GPS 與導航**：允許本站定位、錯誤與重試、Google Maps 網址。
6. **手機外勤畫面**：今日清單、單人卡片、進度、上一位／下一位。
7. **拜訪與附件整合**：沿用既有 contact/attachment，補刪除本人權限。
8. **整合驗收**：桌面可見性、網路失敗、重複送出、瀏覽器與全套測試。

每一批完成後都執行：

```text
python -m unittest discover -s tests -q
```

## 9. 預計修改檔案

### 第一批新增

- `customer_api/field_visit_routing.py`
- `tests/test_field_visit_routing.py`
- `docs/v2/FIELD_VISIT_PHASE1_PLAN.md`

### 後續批次新增

- `customer_api/postgres_field_visits.py`
- `customer_api/field_visit_service.py`
- `customer_api/field_visit_permissions.py`
- `customer_api/routes_field_visits.py`
- 對應 repository、API、migration、效能與整合測試

### 後續批次修改

- `postgres/schema.sql`
- `customer_api/postgres_schema.py`
- `customer_api/postgres_source.py`
- `customer_api/data_source_base.py`
- `customer_api/schemas.py`
- `customer_api/app.py`
- `customer_api/middleware.py`
- `customer_mobile_web/index.html`
- `customer_mobile_web/app.js`
- `customer_mobile_web/styles.css`
- `customer_mobile_web/service-worker.js`
- `tests/test_customer_api.py`

任何正式修改前仍會檢查打包流程實際使用的是根目錄 `customer_mobile_web`，避免誤改重複目錄。

## 10. 已完成批次

- 批次 1：獨立路線計算核心與 1,000 筆效能測試。
- 批次 2：PostgreSQL schema 8 外勤資料表、地理編碼中繼資料、既有拜訪／附件可選關聯、冪等鍵資料表及人工 rollback 指令。
- 批次 3：集中式角色權限、狀態轉換規則、請求雜湊，以及 PostgreSQL 行程建立、加入項目、查詢、狀態歷史、稽核與冪等交易。
- 批次 4：今日行程、建立行程、加入地主，以及開始／完成／略過／延後等核心 API；所有寫入強制使用 `Idempotency-Key`。
- 批次 5：路線最佳化預覽、確認後原子套用、過期預覽衝突保護及手動鎖定重排 API。
- 批次 6：手機本站 GPS 權限、手動定位與重試提示、記憶體內定位狀態，以及座標優先／地址備援的 Google Maps 導航網址工具。
- 批次 7：手機今日外勤入口、行程進度、單一地主卡片、完整清單、上一位／下一位、開始外勤、GPS 路線確認及 Google Maps／電話快捷操作。
- 批次 8：手機開始拜訪、完成、略過與延後操作視窗，現場備註、可選 GPS、冪等寫入，以及伺服器成功後才自動顯示下一位地主。
- 批次 9：外勤卡片直接開啟同一筆所有權的既有拜訪紀錄與照片附件，顯示現有筆數，依角色提供新增或唯讀查看，手機寫入後與桌面共用同一份資料。
- 批次 10：手機端搜尋姓名、地區、地段、地號或地址，批次勾選所有權資料；今天沒有行程時自動建立，已有行程時忽略重複資料並加入新地主。
- 批次 11：手機端查看與調整尚未完成的拜訪順序，儲存後鎖定人工順序；「移除」改寫為保留歷程的取消狀態，伺服器只允許取消尚未開始的項目，並提供可稽核的恢復功能。
- 批次 12：外勤途中可重新取得目前 GPS，預覽並確認後只重排尚未完成的地主；正在拜訪的地主保留第一位，已完成、略過及取消項目保持原位，網路或定位失敗時不改變既有順序。
- 批次 13：行程全部處理完成後顯示今日成果摘要；統計完成、略過、移除、預估距離、開始與完成時間及外勤耗時，並可展開回顧完整清單。
- 批次 14：手機行程編輯加入「設為優先／取消優先」；由伺服器驗證待拜訪狀態、寫入優先權與稽核紀錄，設為優先時解除該筆人工位置鎖定，重新規劃後依既有路線核心優先安排。
- 批次 15：人工排序的項目顯示「固定順序」，並提供「恢復自動排序」一次解除尚未完成項目的位置鎖定；解除時保留目前畫面順序，之後由使用者按「重新規劃路線」預覽並確認新的自動順序。
- 批次 16：附件刪除權限由伺服器統一判定；Editor 只能刪除自己上傳的附件、Admin 可刪除全部、Viewer 唯讀。手機只顯示有權限的刪除按鈕，舊附件無上傳者紀錄時僅 Admin 可刪除。
- 批次 17：從今日行程卡片新增的聯絡紀錄與照片附件，會保存目前 field_visit_route_item_id；聯絡紀錄在已有定位時一併保存 GPS。伺服器驗證行程、地主與使用者一致，手機以「本次行程」標示關聯資料。
- 批次 18：網路中斷時保留狀態、聯絡紀錄與附件草稿，以相同冪等鍵安全重送，伺服器未確認成功前不切換下一位。
- 批次 19：地主地址變更後立即將舊座標標記為待重新定位，只有重新人工儲存有效經緯度後才恢復路線排序使用。
- 批次 20：公司筆電可將勾選地主批次加入指定日期的共用行程，沿用既有行程並忽略重複資料。
- 批次 21：公司筆電加入地主時可設定優先拜訪，自動規劃會先安排優先群組。
- 批次 22：正式驗證 10、100、1,000 位地主的路線完整性與效能，並在套用前檢查遺漏及重複。
- 批次 23：正式打包前強制執行手機建立行程到桌面讀回紀錄與附件的完整端到端驗收。
- 批次 24：手機登入前檢查網路、VPN、家中伺服器與 PostgreSQL，以明確中文區分失敗原因。
- 批次 25：PWA 主動偵測伺服器手機資源新版並提供一鍵套用，不必手動清除 Safari 快取。
- 批次 26：更新提示可暫緩；附件、地主選取與人工排序尚未完成時阻止重新載入並說明原因。
- 批次 27：安全更新後恢復原頁面、原行程地主、持分詳細資料、拜訪動作與無未儲存選取的行程搜尋內容。
