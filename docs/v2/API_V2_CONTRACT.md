# FastAPI v2 契約

狀態：第一階段凍結草案。第二階段可以新增欄位，但不可刪除已列必填欄位或改變語意。

## 1. 共通路徑與標頭

- API 根路徑：`/api/v2`
- JSON：UTF-8、ISO 8601 時間、日期使用 `YYYY-MM-DD`
- 回應標頭：
  - `X-LCS-API-Version: 2`
  - `X-LCS-Server-Version: 2.0.0`
  - `X-LCS-Request-ID: <opaque id>`
- v1 過渡路由加上：
  - `Deprecation: true`
  - `Sunset: <正式公告日期>`
  - `Link: </api/v2/system/capabilities>; rel="successor-version"`

## 2. 能力協商

### `GET /api/v2/system/capabilities`

登入前可用，只提供版本與能力，不提供資料庫路徑、IP、帳號、schema 細節或主機名稱。

```json
{
  "product": "land-customer-system",
  "server_version": "2.0.0",
  "api_versions": [1, 2],
  "preferred_api_version": 2,
  "minimum_clients": {
    "desktop": "2.0.0",
    "mobile_pwa": "2.0.0",
    "line_bot": "2.0.0"
  },
  "write_policy": "v2_only",
  "features": [
    "global_search",
    "optimistic_locking",
    "workflow_v2",
    "notification_receipts",
    "attachment_integrity",
    "audit_export"
  ],
  "maintenance": false,
  "server_time": "2026-07-22T12:00:00+08:00"
}
```

## 3. 登入與工作階段

| 方法與路徑 | 用途 | 權限 |
|---|---|---|
| `POST /api/v2/auth/login` | 登入並回傳使用者、Token、到期時間與角色能力 | 公開、受節流 |
| `POST /api/v2/auth/logout` | 使目前 Token 失效 | 已登入 |
| `GET /api/v2/auth/me` | 目前角色、資料範圍、遮罩與可用功能 | 已登入 |
| `PUT /api/v2/auth/password` | 修改自己的密碼 | 已登入 |

登入回應不得回傳資料金鑰、salt、hash 或完整權限內部規則。

## 4. 標準資料外殼

單筆：

```json
{
  "data": {},
  "meta": {
    "request_id": "req_...",
    "server_time": "2026-07-22T12:00:00+08:00"
  }
}
```

清單：

```json
{
  "data": [],
  "page": {
    "limit": 50,
    "next_cursor": null,
    "has_more": false
  },
  "meta": {
    "request_id": "req_..."
  }
}
```

## 5. 標準錯誤

```json
{
  "error": {
    "code": "LCS_CONFLICT",
    "message": "資料已被其他裝置更新，請重新載入。",
    "request_id": "req_...",
    "details": {
      "entity": "ownership",
      "entity_id": 156,
      "expected_version": 8,
      "current_version": 9
    }
  }
}
```

| HTTP | 代碼 | 說明 |
|---:|---|---|
| 400 | `LCS_BAD_REQUEST` | 格式或規則錯誤 |
| 401 | `LCS_AUTH_REQUIRED`／`LCS_SESSION_EXPIRED` | 未登入或工作階段失效 |
| 403 | `LCS_PERMISSION_DENIED`／`LCS_SCOPE_DENIED` | 角色或資料範圍不足 |
| 404 | `LCS_NOT_FOUND` | 資源不存在或無權看見 |
| 409 | `LCS_CONFLICT`／`LCS_DUPLICATE` | 版本衝突或唯一條件衝突 |
| 413 | `LCS_FILE_TOO_LARGE` | 附件超過限制 |
| 422 | `LCS_VALIDATION_ERROR` | 欄位驗證失敗 |
| 429 | `LCS_RATE_LIMITED` | 登入或 API 節流 |
| 503 | `LCS_MAINTENANCE`／`LCS_DEPENDENCY_UNAVAILABLE` | 維護或必要服務失效 |
| 500 | `LCS_INTERNAL_ERROR` | 脫敏錯誤代碼；詳細內容只在主機日誌 |

## 6. 分頁、排序與查詢

- `limit` 預設 50，最大 500；LINE Bot 服務帳號可另設更低上限。
- `cursor` 是不透明字串，客戶端不可解析或自行產生。
- 排序只允許端點白名單，必須包含唯一 ID 作最後排序鍵。
- 搜尋字串、姓名、身分證與地址不得寫入 API 存取日誌。
- 全域搜尋回應只包含目前角色可見的類型與遮罩欄位。

### `GET /api/v2/search`

參數：`q`、`types=owner,land,project,attachment`、`limit`、`cursor`。
結果欄位：`type`、`id`、`title`、`subtitle`、`match_fields`、`updated_at`、`version`。

## 7. 核心資源端點

| 群組 | 主要端點 | 說明 |
|---|---|---|
| 地主 | `/owners`、`/owners/{id}` | 地主彙整、名下持分及遮罩 |
| 土地 | `/lands`、`/lands/{id}` | 地區／地段／地號與持分彙整 |
| 持分 | `/ownerships`、`/ownerships/{id}` | 正式平面資料的核心寫入單位 |
| 聯絡 | `/ownerships/{id}/contacts` | 聯絡／拜訪與下次追蹤 |
| 追蹤 | `/follow-ups` | 日期、狀態、負責人、來源 |
| 案件 | `/projects`、`/projects/{id}` | 案件、工作流、成員及土地持分 |
| 任務 | `/tasks`、`/tasks/{id}` | 案件任務、檢查清單與完成回條 |
| 通知 | `/notifications`、`/notification-receipts` | 產生、已讀、完成及跨端回條 |
| 附件 | `/attachments`、`/attachments/{id}` | 上傳、縮圖、下載、分類與完整性 |
| 批次 | `/batches`、`/batches/{id}` | 預覽、執行、狀態與復原 |
| 稽核 | `/audit-events`、`/audit-exports` | 管理員查詢及脫敏匯出 |
| 系統 | `/system/status`、`/system/jobs`、`/system/backups` | 健康、排程、備份與升級準備 |

v1 的 `records` 在 v2 對應為 `ownerships`。v1 路由仍可回傳既有欄位名稱，但 v2 不再把地主、土地與持分混成無版本平面資料。

## 8. 寫入與樂觀鎖

- 可修改資源必須回傳 `version`、`updated_at`、`updated_by`。
- `PUT`／`PATCH`／`DELETE` 必須提供 `If-Match: "<version>"`。
- 版本不一致回傳 409 `LCS_CONFLICT`；不可自動覆蓋。
- 批次操作每筆都核對版本；預設全有或全無。
- 伺服器在同一交易內寫入業務資料、版本、修改歷史與稽核摘要。

## 9. 附件契約

- 上傳前可呼叫預檢取得大小、類型及權限限制。
- 原檔、縮圖及下載均需 Bearer Token。
- 回應包含 `sha256`、`size_bytes`、`category`、`integrity_status`、`version`。
- 內容回應使用安全檔名、`Content-Disposition` 及 `X-Content-Type-Options: nosniff`。
- 外部連結永遠標成 `external`，不宣稱已納管或已備份。

## 10. 稽核與診斷契約

- 每個錯誤及寫入回應都有 Request ID。
- 稽核只保存 actor、動作、實體類型／ID、結果、耗時、錯誤代碼及時間。
- API 存取日誌不保存 request body、Authorization、Cookie、查詢文字或敏感欄位。
- 診斷匯出只回傳版本、健康摘要、計數與代碼。

## 11. 舊版相容

- v2 伺服器過渡期保留全部 `/api/v1` 路由。
- v1.8.2 桌面進入有限讀取過渡；正式 v2 寫入只允許桌面 v2.0 以上。
- 舊 PWA 由伺服器更新，不保留可離線寫入的舊資源。
- LINE Bot v0.30.0 只保留既有唯讀查詢；新案件／通知功能要求 LINE Bot v2.0。
