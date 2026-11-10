# 桌面客戶端介面改 Qt Designer（.ui）盤點

盤點日期：2026-11-02　版本：客戶端 v1.9.89 開始、v1.9.90 發行

範圍：桌面客戶端（`customer_ui.py` → `customer_ui_qt.LandApp`）用到的所有 `QMainWindow / QDialog / QWidget` 子類別，以及建介面的函式。
伺服器主控台（`server_console/`）是另一個程式，不在這次範圍。

判定方式是逐一掃過程式碼（看有沒有表格、樹狀、依資料決定數量的元件、自己畫的元件），每一批動工前還會再細看一次。

## 判定標準

| 標記 | 意思 |
|---|---|
| **可改** | 版面固定，整個畫面都能放進 .ui；表格、清單本身也放進 .ui，**列的內容**（資料）照舊由程式填。 |
| **部分可改** | 外框、按鈕、固定欄位可放 .ui，但有一塊是**依資料決定數量**的元件（例如自訂欄位、每個欄位一個勾選框），這塊在 .ui 放一個空的容器，由程式塞進去。 |
| **不可改** | 自己畫的元件（paintEvent／delegate）、樹狀或圖形檢視本身、版面類別、背景工作，這些不是「版面」，沒有可以用 Designer 拉的東西。 |

## 已完成

| 畫面 | 檔案:行 | 狀態 |
|---|---|---|
| 主視窗骨架：工具列（搜尋／篩選／排序／資料／工具／設定／新增）、主分割器、右側詳細面板、基本資料表單 20 個固定欄位、管理摘要、刪除／清空／儲存列 | `customer_window_ui.py` `create_layout`、`create_form` → `ui/main_window.ui` | ✅ 已改成 .ui |
| 整體樣式（淺色／深色） | `customer_theme.py` `_STYLESHEET` → `ui/theme.qss` | ✅ 已抽成檔案 |
| 基本資料表格格線樣式 | `customer_window_ui.py` → `ui/detail_form.qss` | ✅ 已抽成檔案 |
| 主視窗剩下的小顏色（排序字、分隔線、標題字、欄位標籤、自動計算、管理摘要底色、儲存狀態） | `customer_window_ui.py` → `ui/theme.qss`、`ui/detail_form.qss` | ✅ 第 2 批搬完 |
| 第 2 批 20 個小型對話框 | `ui/dialogs/*.ui`（對照表見 `docs/用Designer調整介面說明.md` 第 10 節） | ✅ 已改成 .ui |
| 第 3 批 24 個表格加按鈕的對話框 | `ui/dialogs/*.ui`（對照表見同文件第 11 節） | ✅ 已改成 .ui |
| 第 4 批主視窗元件：檢視列、批量列、圖例與分頁列、土地標題、關係人分頁 | `ui/main/*.ui`（見同文件第 12 節） | ✅ 已改成 .ui（批量列的排列仍由程式的 FlowLayout 負責；持分條、關係人樹狀圖仍由程式畫） |
| 第 5 批 16 個大型對話框 | `ui/dialogs/*.ui`、`ui/main/owner_*_group.ui`、`ui/main/import_plan_*.ui`（見同文件第 13 節） | ✅ 已改成 .ui（依資料產生的部分放在空容器，由程式填入；關係人編輯視窗的外框仍由程式組合） |
| 對話框裡的主題顏色（備份管理提示字、手機分享網址、刪除都市計畫按鈕、都市計畫摘要與說明、土地詳細資料摘要） | 各對話框 → `ui/theme.qss` | ✅ 第 3 批搬完 |

主視窗裡仍由程式建的動態部分（放在 .ui 的空容器 `listFrame` 裡，或程式最後補上）：

| 部分 | 檔案:行 | 判定 | 原因 |
|---|---|---|---|
| 土地清單（樹狀表格 `LandTreeView`＋都市計畫樹，`QStackedWidget`） | `customer_table_ui.py:292` `_build_record_table`、`customer_urban_plan_workflows.py:137` | 不可改 | 樹的欄位、內容、展開狀態都是資料；欄寬來自使用者設定 |
| 清單上方「檢視／輸入到／全部展開／全部收合」列 | `customer_urban_plan_workflows.py:88` | 可改（下批） | 固定的兩個下拉＋兩個按鈕 |
| 勾選後出現的批量操作列 | `customer_table_ui.py:437` | 部分可改 | 按鈕由 `BATCH_BAR_BUTTONS` 清單產生、接到現有 QAction |
| 清單下方顏色圖例＋分頁 | `customer_table_ui.py:369-393` | 可改（下批） | 固定 4 個圖例＋上一頁／下一頁 |
| 右上角土地標題 `LandHeaderWidget` | `customer_land_header.py:279` | 部分可改 | 文字固定，但地主持分條 `ShareBarWidget` 自己畫 |
| 「關係人」分頁 `OwnerContactsWidget` | `customer_owner_contacts.py:1147`（578 行） | 部分可改 | 有表格、堆疊頁、依角色切換 |
| 狀態列（連線、登入、遮罩、版本、備份、通知按鈕） | `customer_window_ui.py` `create_status_bar_content`、`customer_backup_status.py` | 不可改 | QStatusBar 不能用 .ui 放進 QMainWindow 的中央元件；內容依單機／連線模式不同 |
| 資料／工具／設定 下拉選單、右鍵選單 | `customer_table_ui.py` `_build_*_menu` | 不可改（建議） | 是 QAction 清單、依權限和連線模式開關，不是版面 |

## 對話框與其他元件

### 可改（版面固定）— 共 44 個

| 類別 | 檔案:行（行數） | 備註 |
|---|---|---|
| AuthDialog 登入 | customer_auth.py:74（93） | |
| BackupStatusDialog | customer_backup_status.py:105（42） | 幾行狀態文字 |
| BackupManagementDialog | customer_backup_status.py:149（60） | 表單 |
| ServerBackupTargetsDialog | customer_backup_status.py:211（154） | 表格＋表單 |
| ServerBackupRestoreDialog | customer_backup_status.py:367（62） | 表格 |
| HelpDialog 說明 | customer_dialogs.py:167（29） | 分頁＋文字 |
| DashboardDialog | customer_dialogs.py:834（78） | 表格 |
| RecordHistoryDialog | customer_dialogs.py:914（51） | 表格 |
| FollowUpReminderDialog | customer_dialogs.py:967（78） | |
| FollowUpListDialog | customer_dialogs.py:1047（80） | 表格 |
| ChangePasswordDialog | customer_dialogs.py:1478（44） | |
| FontSizeDialog | customer_dialogs.py:1524（32） | |
| ImportPreviewDialog | customer_dialogs.py:1707（135） | 表格欄位由匯入檔決定（只影響內容） |
| ImportResultDialog | customer_dialogs.py:1844（62） | |
| BatchEditDialog | customer_dialogs.py:1908（40） | |
| BatchEditPreviewDialog | customer_dialogs.py:1950（32） | |
| SavedSearchDialog | customer_dialogs.py:2168（80） | 表格 |
| OperationLogDialog | customer_dialogs.py:2250（40） | 表格 |
| WatchlistDialog | customer_dialogs.py:2292（82） | 表格 |
| PreviousExportDuplicatesDialog | customer_export_controller.py:35（78） | 清單 |
| CaseSelectDialog | customer_extra_dialogs.py:49（36） | |
| FieldVisitScheduleDialog | customer_extra_dialogs.py:87（47） | |
| TagManagementDialog | customer_extra_dialogs.py:136（164） | 表格 |
| CustomerTagsDialog | customer_extra_dialogs.py:302（43） | 清單 |
| BatchCustomerTagsDialog | customer_extra_dialogs.py:347（57） | 清單 |
| AttachmentDialog | customer_extra_dialogs.py:406（141） | 表格 |
| CustomFieldManagementDialog | customer_extra_dialogs.py:549（91） | 表格 |
| ApplyTemplateDialog | customer_extra_dialogs.py:836（43） | |
| ContactLogDialog | customer_extra_dialogs.py:881（126） | 表格 |
| MergeRecordsDialog | customer_extra_dialogs.py:1009（26） | |
| HealthCheckDialog | customer_extra_dialogs.py:1037（38） | 表格 |
| LandDetailsDialog | customer_land_details.py:16（72） | 表格 |
| MobileShareDialog | customer_mobile_share.py:116（61） | QR 圖由程式產生 |
| ExistingContactPickerDialog | customer_owner_contacts.py:132（32） | 內含 ContactChoiceTable（自訂類別，需在 Designer 用「提升」） |
| DeactivateRelationDialog | customer_owner_contacts.py:166（33） | |
| RecycleBinDialog | customer_productivity.py:687（46） | 表格 |
| UndoOperationsDialog | customer_productivity.py:735（30） | 表格 |
| NotificationCenterDialog | customer_productivity.py:1217（21） | 表格 |
| ImportProfilesDialog / ReportTemplatesDialog / DuplicateFinderDialog | customer_productivity.py:1240 / 1284 / 1329 | 表格＋表單；算 3 個 |
| UrbanPlanManagementDialog | customer_urban_plan_dialogs.py:39（191） | 表格 |
| DeleteUrbanPlanDialog | customer_urban_plan_dialogs.py:362（46） | |
| SetUrbanPlanDialog | customer_urban_plan_dialogs.py:410（110） | |

（ImportProfiles／ReportTemplates／DuplicateFinder 合在同一列，算 3 個。）

### 部分可改（有一塊依資料產生）— 共 18 個

| 類別 | 檔案:行（行數） | 依資料產生的部分 |
|---|---|---|
| DataQualityRulesDialog | customer_dialogs.py:198（140） | 每條規則一列勾選／數值 |
| DataQualityDialog | customer_dialogs.py:340（492） | 大型；檢查結果表格＋多個依結果出現的區塊 |
| VisitCalendarDialog | customer_dialogs.py:1161（315） | 月曆格子 `_CalendarDayCell` 每天一個 |
| ColumnVisibilityDialog | customer_dialogs.py:1558（47） | 每個表格欄位一個勾選框 |
| AdvancedSearchDialog | customer_dialogs.py:1607（98） | 每個可搜尋欄位一列 |
| SharedLandBatchDialog | customer_dialogs.py:1984（182） | 每位地主一列 |
| CustomerCustomValuesDialog | customer_extra_dialogs.py:642（34） | 自訂欄位數量由資料庫決定 |
| BatchCustomerCustomValuesDialog | customer_extra_dialogs.py:678（47） | 同上 |
| TextTemplateDialog | customer_extra_dialogs.py:727（107） | 變數按鈕由欄位清單產生 |
| OwnerContactDialog | customer_owner_contacts.py:201（619） | 大型；聯絡方式列可增減 |
| OwnerContactsWidget | customer_owner_contacts.py:1147（578） | 依角色／資料切換頁面 |
| UserManagementDialog | customer_productivity.py:767（116） | 角色選項 |
| BackupTargetsDialog | customer_productivity.py:885（152） | 備份目的地清單 |
| WorkflowDialog | customer_productivity.py:1039（176） | 每個階段一組元件 |
| MapLocationsDialog | customer_productivity.py:1582（378） | 地圖網頁＋地理編碼進度 |
| LandHeaderWidget | customer_land_header.py:279（83） | 持分條自繪 |
| ImportPlanChoice / ImportPlanResultSection | customer_urban_plan_dialogs.py:232 / 258 | 匯入結果依資料產生（算 2 個） |

### 不可改 — 共 15 個

| 類別 | 檔案:行 | 原因 |
|---|---|---|
| LandTreeView | customer_table_ui.py:65 | 樹狀表格本身（內容是資料） |
| TagPillDelegate、ShareBarDelegate | customer_table_ui.py:106、203 | 自己畫儲存格 |
| ShareBarWidget | customer_land_header.py:68 | 自己畫持分條 |
| UrbanPlanTreeView、PlanTreeItem、PlanRowDelegate | customer_urban_plan_view.py:107、62、70 | 都市計畫樹與自繪列 |
| OwnerContactTreeView | customer_owner_contacts.py:822 | QGraphicsView 關係圖 |
| ContactChoiceTable | customer_owner_contacts.py:80 | 表格子類別（可在 Designer 用「提升」放進對話框） |
| _CalendarDayCell | customer_dialogs.py:1140 | 月曆的一格，數量依月份 |
| ResponsiveDialog | customer_responsive_dialog.py:9 | 對話框共用行為（尺寸），不是版面 |
| FlowLayout | customer_flow_layout.py:9 | 自訂版面類別 |
| OffsiteBackupWorker、BatchGeocodeWorker | customer_productivity.py:668、1519 | 背景工作，沒有畫面 |
| _FocusStateFilter | customer_window_ui.py | 事件過濾器 |

QMessageBox、QInputDialog、QFileDialog 是 Qt 內建的對話框，不需要也不能改 .ui。

## 摘要

- 畫面總數（主視窗＋對話框＋可放進 .ui 的子元件）：**63 個**
  - 已完成：主視窗骨架 1 個
  - 可改：44 個
  - 部分可改：18 個（含土地標題、關係人分頁）
  - 另有主視窗清單區 3 列固定列（檢視列、分頁列可改；批量列部分可改）
- 不可改：15 個元件類別（自繪、樹狀、背景工作等，不是版面），以及狀態列、選單

## 建議後續分批

| 批次 | 內容 | 數量 | 備註 |
|---|---|---|---|
| 第 2 批（✅ 已完成） | 小型固定對話框：登入、改密碼、字體大小、批次修改＋預覽、選案件、外勤排程、合併、套用範本、追蹤提醒、匯入結果、手機分享、都市計畫刪除／設定、備份管理、選既有聯絡人、停用關係、說明、土地明細、前次匯出重複 | 20 | 風險最低，先熟悉流程 |
| 第 3 批（✅ 已完成） | 表格＋按鈕型管理對話框：紀錄歷史、追蹤清單、儀表板、儲存的搜尋、操作紀錄、注意名單、標籤管理、客戶標籤（2）、附件、自訂欄位管理、聯絡紀錄、健康檢查、回收桶、復原、通知中心、匯入設定檔、報表範本、重複資料、匯入預覽、備份狀態、伺服器備份（2）、都市計畫管理 | 24 | 表格放 .ui，資料照舊由程式填 |
| 第 4 批（✅ 已完成） | 主視窗剩下的固定列（檢視列、分頁列、批量列外框）、土地標題、關係人分頁外框 | 5 | 動到主畫面，需再做截圖比對 |
| 第 5 批（✅ 已完成） | 部分可改的大型對話框：資料品質（2）、拜訪月曆、進階搜尋、欄位顯示、共有土地批次、自訂欄位值（2）、文字範本、關係人編輯、使用者管理、備份目的地、工作流程、地圖、都市計畫匯入結果（2） | 16 | 每個都要留空容器給動態部分，逐一做 |

每批都照這一輪的做法：先備份、改完跑全部測試、截圖前後比對、更新本文件。

## 完成狀態（2026-11-02）

五批全部完成：主視窗骨架 1 個、主視窗元件 5 個、對話框 57 個、對話框內的元件 4 個（關係人編輯的兩個區塊、都市計畫匯入的選單與結果區），共 67 個 .ui 檔；所有寫死的介面顏色都在 `ui/theme.qss`、`ui/detail_form.qss`。

仍由程式處理、沒有改成 .ui 的部分（原因見上方「不可改」表）：
- 自己畫的元件：持分條、表格裡的標籤／持分條儲存格、都市計畫樹、關係人樹狀圖
- 依資料產生的內容：月曆的日期格子、資料品質的勾選框、自訂欄位列、進階搜尋欄位列、欄位顯示勾選框（都放在 .ui 的空容器裡）
- 狀態列、資料／工具／設定與右鍵選單（QAction 清單，依權限與連線模式開關）
- 關係人編輯視窗的外框（新增與編輯兩種模式的排法不同）
- 批量列的自動換行排列（自訂的 FlowLayout）

下一步：打包新版客戶端，打包後實際開一次 exe 確認 QtUiTools 與 `ui` 資料夾都在（見《用Designer調整介面說明》第 14 節）。
