# 土地清單相同地號摺疊顯示完成報告

完成日期：2026-07-29

- 家中伺服器：v1.9.25
- 公司筆電客戶端：v1.9.2
- PostgreSQL schema：維持 v10，沒有 migration
- 功能範圍：Windows 土地清單與其必要 FastAPI 回傳欄位

## 修改的 View

- `customer_table_ui.py`
  - 將原本的平面 `QTableView` 改為 `LandTreeView(QTreeView)`。
  - 預設全部收合，箭頭只負責展開或收合。
  - 新增「全部展開」、「全部收合」、「上一頁」、「下一頁」。
  - 分開顯示土地總數、地主／所有權資料總數及本頁持分數。
  - 土地父節點與 ownership 子節點使用不同右鍵選單。
- `customer_land_details.py`
  - 新增土地父節點唯讀詳細視窗。
  - 顯示土地摘要及完整地主／持分子清單。

## 修改的 Model

- `customer_models.py`
  - `RecordTableModel` 改為 `QAbstractItemModel`。
  - 階層為 `Root -> LandNode -> OwnershipNode`。
  - 土地分組優先使用 `land_id`。
  - 無 `land_id` 時使用完整土地識別組合；完全沒有土地識別的舊資料以記錄 ID 隔離，避免錯誤合併。
  - 父節點保存 `land_id` 與所有實際 ownership ID。
  - 子節點保存 `land_id`、`owner_id`、`ownership_id`。
  - 父節點勾選代表勾選該土地全部 ownership，並支援三態顯示。
  - 每頁固定 100 筆土地，同一土地不拆頁。

## 修改的 Proxy Model

- `LandTreeProxyModel(QSortFilterProxyModel)`
  - 保留標準 source/proxy index 對應。
  - 階層搜尋及排序結果由背景資料處理器先建立，Proxy 不會再破壞父子順序。

## 修改的 Controller

- `customer_search_controller.py`
  - 所有查詢結果先按土地分組，再交給 View。
  - 大量資料的解密、搜尋、分組與排序沿用背景執行緒。
  - 啟動時先顯示一頁快速預覽，背景完成後替換為正式土地級分頁結果。
- `customer_record_workflows.py`
  - 雙擊土地開啟土地詳細資料。
  - 雙擊子節點載入既有地主／ownership 詳細資料。
  - 保存、恢復及清理目前執行期間的展開 `land_id`。
  - 單筆、全部展開／收合與土地級換頁。
- `customer_selection_workflows.py`
  - 父節點選取解析成該土地實際 ownership ID 集合。
  - 子節點選取只解析成該筆 ownership ID。
  - 狀態列分開顯示已選土地、已選持分及已勾選持分。
- `customer_export_controller.py`
  - 複製、Excel、Word、手機分享及既有批次工作改由節點實際 ID 取資料。
  - 不再以畫面 row number 推算資料 ID。

## API response 調整

`customer_api/postgres_source.py` 的既有記錄清單查詢新增：

- `ownership.id AS ownership_id`
- `land.id AS land_id`
- `owner.id AS owner_id`

既有土地、地主、ownership 與管理欄位仍原樣回傳。沒有建立群組資料表，也沒有將展開狀態寫入伺服器。

## 父節點欄位

- 完整地號
- 土地總面積（只取土地資料一次，不累加 ownership）
- 不重複地主數（以 `owner_id` 去重）
- ownership／持分筆數
- 地目／使用分區
- 狀態摘要
- 原有土地欄位

若電話、地目／使用分區或客戶狀態由既有自訂欄位保存，畫面會辨識常用欄位名稱後顯示；沒有資料時顯示空白或未設定，不新增資料庫欄位。

## 子節點欄位

- 地主姓名
- 持分
- 權利範圍面積
- 地主地址
- 電話
- 客戶狀態
- 備註摘要
- 原有案件、標籤、附件、聯絡與追蹤欄位

同一地主的不同 ownership 紀錄逐筆保留，不自行合併。

## 搜尋行為

- 搜尋地主或 ownership 欄位：只保留命中的子節點，但一定保留土地父節點。
- 搜尋土地欄位：保留符合土地的群組及其符合目前查詢的資料。
- 有搜尋或進階篩選時自動展開目前命中的土地。
- 清除搜尋後重新載入完整資料，不保留搜尋期間的自動展開狀態。
- 不同 `land_id` 即使地號文字相同也不合併。

## 排序行為

- 父節點支援地區、地段、地號、面積、地主數及持分筆數排序。
- 子節點支援姓名、持分相關數值、權利範圍面積與狀態等既有排序選項。
- 地號使用數值自然順序，`2、10、100` 不會排成 `10、100、2`。
- 子節點排序只在自己的土地父節點內進行。

## 分頁行為

- 每頁 100 筆土地。
- 同一土地的全部 ownership 留在同一頁。
- 統計分開顯示土地數與 ownership 數。
- 換頁後恢復該頁仍存在的展開土地。

## 展開狀態保存

- 使用 `land_id`；無 `land_id` 的舊資料使用完整土地識別 tuple。
- 本次程式執行期間保存。
- 重新整理、排序、資料更新及篩選後，恢復結果中仍存在的展開項目。
- 已刪除或篩除的土地 ID 會從展開集合清除。
- 不寫入 PostgreSQL。

## 新增測試

`tests/test_land_tree_grouping.py` 覆蓋：

- 相同 `land_id` 分成單一父節點。
- 不同 `land_id` 或不同地段的相同地號不合併。
- 地主數去重、ownership 筆數、土地面積不重複累加。
- 子節點必要欄位與權利範圍面積。
- 地主搜尋、土地搜尋及清除搜尋資料恢復。
- 地號自然排序及子節點階層排序。
- 土地級 100 筆分頁及群組不拆頁。
- 父子節點實際 ID 與批次選取。
- 單筆／全部展開收合、展開狀態恢復及無效 ID 清理。
- 父子節點雙擊分流。
- 父子節點不同右鍵選單。
- PostgreSQL API 查詢回傳三個關聯 ID。

## 回歸測試結果

- 完整命令：`python -m unittest discover -s tests -q`
- 原有與新增測試：全部通過。
- 涵蓋土地新增、修改、刪除、搜尋、匯入、匯出、批次工具、Viewer／Editor／Admin、FastAPI、PostgreSQL、外勤、附件、關係人及既有桌面流程。
- PostgreSQL schema 未修改，因此沒有 migration 或 rollback。

## v1.9.4 儲存後狀態修正

- 一般儲存或重新整理前會保存使用者實際展開的 `land_id`。
- 恢復時只套用仍存在於目前結果的展開 ID，收合群組保持收合。
- 搜尋命中自動展開使用獨立旗標，不會寫入一般展開狀態。
- 選取快照包含 `node_type`、`land_id`、`owner_id`、`ownership_id`。
- 同時盡量恢復水平與垂直捲動位置。
- 群組與 ownership 順序不變時使用 `dataChanged` 局部更新；結構改變才 reset Model。
- 一般刷新流程沒有呼叫 `expandAll()`。
- 完整自動化測試共 385 項通過。
