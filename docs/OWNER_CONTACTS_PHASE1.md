# 地主關係人管理 Phase 1 強化版

正式版本：

- 家中伺服器：v1.9.24
- 公司筆電客戶端：v1.9.1
- PostgreSQL：schema 10

## 使用流程

1. 更新並啟動家中伺服器 v1.9.24。
2. 使用公司筆電客戶端 v1.9.1 登入。
3. 選取地主資料，切換至「關係人」分頁。
4. 查看姓名、關係、電話、戶籍地址、聯絡地址、身分補充與狀態。
5. 使用「新增」建立全新關係人，或搜尋並連結既有人員。
6. 雙擊資料列查看完整資料；Editor／Admin 可再進入編輯。
7. 使用「複製電話」或「複製地址」取得外出聯絡所需資料。
8. 勾選「顯示已停用」可查看及重新啟用舊關係。

姓名、電話、三種地址、身分補充與人員備註是跨地主共用資料；關係
類型、關係補充、主要狀態、排序及關係備註只影響目前地主。

## 權限

- Viewer：查看、顯示停用資料、複製電話與地址。
- Editor：Viewer 功能，加上新增、連結、編輯、停用、重新啟用與主要關係人設定。
- Admin：Phase 1 與 Editor 相同。

## 搜尋與重複提示

- 搜尋支援姓名、手機、市話、戶籍地址及聯絡地址，最多 50 筆。
- 電話搜尋忽略空白、括號與連字號。
- 手機相同、市話相同、姓名加聯絡地址相同或姓名加戶籍地址相同會顯示高度疑似重複。
- 只有姓名相同時只顯示較弱提示，不會阻止建立。
- 系統不會自動合併資料。

## 升級

伺服器啟動時以同一個 PostgreSQL transaction 套用 schema 10：

- 將舊 `address` 資料保留到 `registered_address`
- 新增 `registered_address`、`contact_address`、`work_address`
- 新增 `identity_note`
- 新增 `deactivated_at`、`deactivated_by`
- 新增地址及正規化電話索引

正式升級前應先使用既有伺服器完整備份功能保存 PostgreSQL 與附件。

## Rollback

只回復強化欄位：

`postgres/migrations/010_owner_contacts_enhancement_rollback.sql`

移除整個 Phase 1：

`postgres/migrations/009_owner_contacts_rollback.sql`

執行任何 rollback 前都必須停止伺服器並完成備份。移除整個 Phase 1 會
永久刪除所有關係人資料。

## 範圍限制

本階段沒有聯絡歷程、提醒、自動撥號、導航、手機外勤、LINE Bot、家族樹、
照片、永久刪除、自動合併、Excel 匯入匯出或全域關係人管理中心。
