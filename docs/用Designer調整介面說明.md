# 用 Qt Designer 調整桌面客戶端介面

適用：客戶端 v1.9.90 之後。目前改成 .ui 的是**主視窗**（工具列、左右分割、右側基本資料表單與按鈕）、**20 個小型對話框**（第 2 批，見第 10 節）、**24 個表格加按鈕的對話框**（第 3 批，見第 11 節）、**主視窗的清單列、土地標題、關係人分頁**（第 4 批，見第 12 節）和 **16 個大型對話框**（第 5 批，見第 13 節）。五批已全部完成，盤點與無法改成 .ui 的部分見 `docs\UI改造盤點.md`。

## 1. 檔案在哪裡

專案資料夾：`C:\Users\Laptop\Documents\Codex\2026-06-24\new-chat\outputs\customer_system`

| 檔案 | 內容 | 用什麼改 |
|---|---|---|
| `ui\main_window.ui` | 主視窗版面 | Qt Designer |
| `ui\dialogs\*.ui` | 57 個對話框的版面（對照表見第 10、11、13 節） | Qt Designer |
| `ui\main\*.ui` | 主視窗的清單列、分頁列、批量列、土地標題、關係人分頁（第 12 節），以及關係人編輯的兩個區塊、都市計畫匯入的選單與結果區（第 13 節） | Qt Designer |
| `ui\theme.qss` | 整個程式的顏色、邊框、按鈕樣式（淺色／深色共用） | 記事本或 VS Code |
| `ui\detail_form.qss` | 右側「基本資料」謄本格線的樣式 | 記事本或 VS Code |
| `ui\fluent_theme.json` | Fluent 元件的主色（淺色／深色）與字型（第 15 節） | 記事本或 VS Code |
| `ui\fluent_widgets.qss` | 個別 Fluent 元件的外觀微調（搜尋框、表單格子、刪除鈕的紅色…） | 記事本或 VS Code |
| `customer_theme.py` 的 `LIGHT` / `DARK` | 淺色、深色兩套色碼表 | 交給 Claude 改 |
| `customer_fields.py` 的 `LAND_FIELDS` | 欄位名稱（地區、地段、姓名…） | 交給 Claude 改（Excel 匯出入也用同一份名稱） |

程式執行時才讀這些檔案，**改完存檔、重開程式就生效**，不用重新產生任何 Python 程式碼。

## 2. 打開 Qt Designer

在專案資料夾開 PowerShell，執行：

```bash
tools\open_designer.bat ui\main_window.ui
```

`open_designer.bat` 會先載入 Fluent 元件外掛再開 Designer，元件盒裡多出「Fluent 按鈕／Fluent 輸入／Fluent 文字／Fluent 顯示／Fluent 容器」幾組，畫面上也會畫成程式裡的樣子（第 15 節）。直接執行 `pyside6-designer` 也能開、也能存，只是 Fluent 元件會顯示成一般的 Qt 元件。

（`pyside6-designer.exe` 在 `C:\Users\Laptop\AppData\Local\Programs\Python\Python314\Scripts\`。）

**改之前先備份一份**：把 `ui\main_window.ui` 複製到 `backup_ui_20261102\` 資料夾，檔名加日期，例如 `main_window.ui.bak-20261105`。不要把備份留在 `ui\` 資料夾裡（打包時整個 `ui\` 都會被包進去）。

## 3. 可以放心改的

- 元件的大小（最小／最大尺寸）、邊距（layout 的 Margin）、間距（Spacing）、伸縮比例（stretch）。
- 按鈕文字、提示文字（toolTip）、輸入框的灰色提示字（placeholderText）、輸入長度上限。
- 基本資料表格裡**格子的位置**：可以把 `fieldCell_xxx` 拖到別列、改跨幾欄（columnSpan）。外框粗線會依格子實際位置自動算，不用改程式。
  - 土地標示部的格子要放在 `ownerSectionHeaderRow`（土地所有權部標題）**上面**，地主的格子放在它**下面**；程式靠這個分辨格子屬於哪一部。
  - 舊的自動測試 `test_basic_data_form_uses_grouped_responsive_reference_layout` 會檢查目前格子的排法；搬動格子後這個測試會失敗，打包時跟 Claude 說一聲「格子位置是我故意改的」，Claude 會一起更新測試。
- 加裝飾用的標籤、分隔線、空白（spacer）。
- 按鈕樣式：在屬性編輯器裡的動態屬性 `variant`，可填 `primary`（綠底主要按鈕）、`ghost`（無框）、`danger-text`（紅字）、或留空（一般按鈕）。
- Tab 鍵順序：選單「Edit → Edit Tab Order」。左側清單區是程式建的，Tab 順序會自動排在「新增資料」按鈕後面、右側表單前面。

## 4. 不能改名、不能刪除的元件

程式靠 objectName 找元件。下列名稱**不能改、不能刪、類型不能換**；少了任何一個，程式開啟時會跳出訊息，列出是哪個檔案少了哪些名稱。

**主視窗骨架**

| objectName | 類型 | 說明 |
|---|---|---|
| `appGround` | QWidget | 最外層 |
| `toolbarFrame` | QFrame | 上方工具列 |
| `searchGroup`、`searchFilterCombo`、`searchDivider`、`searchDivider_2`、`searchInput`、`searchButton` | | 搜尋框那一組 |
| `toolbarSortLabel`、`sortFieldCombo`、`sortOrderCombo`、`clearSearchButton` | | 排序與清除 |
| `dataButton`、`toolsButton`、`settingsButton`、`newRecordButton` | QPushButton | 資料／工具／設定／新增資料 |
| `contentGround` | QWidget | 下方內容區（程式會改名成 appGround 以套用底色） |
| `mainSplitter` | QSplitter | 左右分割 |
| `listFrame`＋`listLayout` | QFrame＋QVBoxLayout | 左側清單區，**裡面要保持空的**，程式會塞進清單 |
| `formFrame`＋`formLayout` | QFrame＋QVBoxLayout | 右側面板 |
| `landHeaderSlot` | QWidget | 空的佔位元件，程式會換成右上角的土地標題 |
| `detailTabs`、`basicPage` | QTabWidget、QWidget | 「基本資料」分頁（「關係人」分頁由程式加上） |
| `basicDataScrollArea`、`basicDataForm`、`basicDataFormLayout` | QScrollArea、QWidget、QGridLayout | 基本資料表格 |
| `landSectionHeaderRow`、`landSectionHeader`、`landSectionNote` | | 「土地標示部」標題列 |
| `ownerSectionHeaderRow`、`ownerSectionHeader`、`ownerSectionNote` | | 「土地所有權部」標題列 |
| `autoCalculationBadge`、`autoCalculationBadge_age` | QLabel | 「自動計算」小字 |
| `managementSummaryHeader`、`managementSummaryLabel` | QLabel | 管理摘要 |
| `deleteRecordButton`、`saveStateLabel`、`clearFormButton`、`saveRecordButton` | | 刪除／儲存狀態／清空／儲存 |

**每個欄位三個元件**：`fieldCell_<key>`（格子 QWidget）、`fieldLabel_<key>`（標籤 QLabel）、`field_<key>`（輸入框）。

| key | 欄位 | 輸入框類型 |
|---|---|---|
| `urban_plan` | 都市計畫 | QComboBox |
| `district`、`section`、`subsection`、`land_number` | 地區、地段、小段、地號 | QLineEdit |
| `registration_order`、`numerator`、`denominator` | 序號、分子、分母 | QLineEdit |
| `area`、`declared_value`、`ping`、`total_declared_value` | 面積、公告現值、坪數、總現值 | QLineEdit |
| `owner_name`、`external_id`、`birth_year`、`age` | 姓名、身分證、出生西元年、年齡 | QLineEdit |
| `address`、`registration_reason`、`visit_log` | 地址、原因、出訪記錄 | QLineEdit |
| `note` | 備註 | QPlainTextEdit |

格子上的動態屬性 `formField`（true）與 `autoCell`（總現值、年齡為 true）也要保留，格線樣式靠它們。

## 5. 在 Designer 改了但會被程式蓋掉的

這些由程式在開啟時設定，Designer 裡改了不會生效：

- 下拉選單的選項（篩選欄位、排序欄位、新到舊／舊到新、都市計畫清單）。
- 按鈕圖示（放大鏡、加號、垃圾桶、箭頭）。
- 欄位標籤文字：以 `customer_fields.py` 為準（Excel 標題也用同一份）。
- 標題字（土地標示部、土地所有權部、管理摘要）的**字型**：程式設定，因為 QSS 不能設字距。它們的**顏色**已經搬到 qss，可以改。
- 左右分割的寬度：預設 760／480；使用者拖動過後會記住上次的寬度。右側最小寬 460、左側最小寬 540 寫在 .ui，改了會生效，但程式恢復記住的寬度時仍以 540／460 為下限。

## 6. 改顏色

打開 `ui\theme.qss`（整體；檔案最後兩段是主視窗的「排序」字、搜尋框分隔線、管理摘要底色、儲存狀態，以及對話框裡的備份管理提示字、手機分享網址、刪除都市計畫的紅色按鈕、都市計畫摘要與說明、土地詳細資料的摘要底色）或 `ui\detail_form.qss`（基本資料格線、欄位標籤、標題字、「自動計算」小字），顏色用「錢字號＋名稱」寫，例如 `$green`、`$paper`、`$rule`，程式會依淺色／深色主題換成對應色碼。可用的名稱就是 `customer_theme.py` 裡 `LIGHT` 表格的那些（`ground`、`paper`、`field`、`ink`、`ink2`、`rule`、`rule_strong`、`green`、`green_ink`、`green_tint`、`sel`、`seal`、`auto`…）。也可以直接寫 `#336699` 這種色碼，但那樣淺色、深色會一樣。

如果打錯名稱或檔案壞掉，程式**不會打不開**，會改用內建的預設樣式（畫面會回到原本的樣子），錯誤寫在記錄檔裡。

## 7. 預覽

1. **Designer 內預覽**：`Ctrl+R`。只看版面，看不到程式的顏色與資料。
2. **套上真正顏色預覽（建議）**：用空白測試資料開主視窗，不用登入、不碰正式資料：

   ```bash
   python tools\preview_main_window.py
   ```

   深色主題：

   ```bash
   python tools\preview_main_window.py dark
   ```

   加 `--sample` 會放三筆範例地主、選一塊土地、勾兩筆，用來看土地標題、持分條和勾選後的批量列：

   ```bash
   python tools\preview_main_window.py --sample
   ```

3. **開完整程式**：`python customer_ui.py`（真正的啟動入口；會用專案資料夾裡的本機資料庫，請小心不要誤改資料）。

4. **對話框預覽**：不用登入、不用資料庫，每個對話框都帶固定的範例資料。先列出全部名稱：

   ```bash
   python tools\preview_dialog.py --list
   ```

   再開某一個（後面加 `dark` 看深色）：

   ```bash
   python tools\preview_dialog.py AuthDialog
   ```

改完後跑一次檢查（確認必要元件都還在、.ui 能載入、容器沒被 Designer 刪掉）：

```bash
python -m unittest discover -s tests -p "test_*_ui.py"
```

## 8. 改壞了怎麼還原

- 開程式時跳出「介面檔 main_window.ui 少了程式需要的元件」：照訊息把元件名稱改回來，或用備份檔覆蓋。
- 從自己的備份還原：把 `backup_ui_20261102\main_window.ui.bak-日期` 複製回 `ui\main_window.ui`。
- 回到改造完成時的原始版本：`backup_ui_20261102\ui_original\` 裡有 `main_window.ui`、`theme.qss`、`detail_form.qss`，以及 `dialogs\` 底下 57 個對話框、`main\` 底下 9 個元件的 .ui，複製回 `ui\` 對應位置即可。
- 改造前的 Python 程式：第 1 批（主視窗）之前的在 `backup_ui_20261102\`，第 2 批（小型對話框）之前的在 `backup_ui_20261102\batch2\`，第 3 批（表格對話框）之前的在 `backup_ui_20261102\batch3\`，第 4 批（主視窗元件）之前的在 `backup_ui_20261102\batch4\`，第 5 批（大型對話框）之前的在 `backup_ui_20261102\batch5\`。

## 9. 交給 Claude 打包

改好、預覽沒問題後，跟 Claude 說「ui 已調整好，請打包客戶端」，並說明改了哪些地方。Claude 會：

1. 跑全部測試（`python -m unittest discover -s tests`）。
2. 用 `build_exe.bat` 打包（已設定 `--add-data "ui;ui"`，`ui\` 資料夾會整個包進程式裡）。
3. 依慣例整理成 `releases\` 裡的發行檔。

打包前請確認 `ui\` 資料夾裡只有正式的 `.ui` / `.qss` 檔，沒有備份檔或暫存檔。

## 10. 對話框（第 2 批）

每個對話框的 .ui 最外層是一個 QWidget（名稱是 `xxxContent`），程式把它整個放進對話框裡。最外層的這幾個屬性會套用到對話框本身：

| 最外層屬性 | 作用 |
|---|---|
| `windowTitle` | 視窗標題（下表註明程式會改寫的除外） |
| `minimumSize`／`maximumSize` | 對話框的最小／最大尺寸；兩個設成一樣就是固定大小 |
| 動態屬性 `dialogSize`（Size） | 對話框打開時的大小；沒有這個屬性的對話框依內容自動決定大小 |

`xxxSlot` 是空的佔位元件，程式會換成真正的元件（例如關係人表格），**不要刪、不要放東西進去**。各對話框的必要元件名稱寫在程式裡每個類別的 `ui_object_names`，不能改名或刪除；少了任何一個，打開那個對話框時會跳出訊息說明缺哪些名稱。按鈕盒（`buttonBox`）裡的按鈕文字由程式設定，Designer 只能選要哪些標準按鈕。

| .ui 檔（在 `ui\dialogs\`） | 畫面 | 預覽名稱 | 程式會改寫的部分（在 .ui 改無效） |
|---|---|---|---|
| `auth_dialog.ui` | 登入／第一次設定密碼 | `AuthDialog`、`AuthDialog-setup` | 設定模式時：標題、上方說明、按鈕文字、帳號預填 admin、顯示「確認密碼」列、高度多 30 |
| `change_password_dialog.ui` | 修改密碼 | `ChangePasswordDialog` | （無） |
| `font_size_dialog.ui` | 字體大小 | `FontSizeDialog` | 下拉選項 |
| `batch_edit_dialog.ui` | 批次修改 | `BatchEditDialog` | 「已勾選 N 筆資料」、欄位選項 |
| `batch_edit_preview_dialog.ui` | 批次修改預覽 | `BatchEditPreviewDialog` | 摘要文字、預覽內容 |
| `case_select_dialog.ui` | 加入／移出案件 | `CaseSelectDialog` | 標題、說明文字、確定按鈕文字、案件選項 |
| `field_visit_schedule_dialog.ui` | 加入今日行程 | `FieldVisitScheduleDialog` | 說明文字、日期（今天） |
| `merge_records_dialog.ui` | 合併兩筆資料 | `MergeRecordsDialog` | 「保留：」「合併後刪除：」兩行、預覽內容 |
| `apply_template_dialog.ui` | 套用快速範本 | `ApplyTemplateDialog` | 兩個下拉選項 |
| `follow_up_reminder_dialog.ui` | 追蹤提醒 | `FollowUpReminderDialog` | 上方標題（有選資料時）、日期、狀態選項、備註、「清除提醒」能不能按 |
| `import_result_dialog.ui` | 匯入結果報表 | `ImportResultDialog` | 摘要、明細；「匯出錯誤列」只在有錯誤時出現；有都市計畫結果時 `planSectionSlot` 換成結果區、大小變 640×640 |
| `mobile_share_dialog.ui` | 傳送到手機 | `MobileShareDialog` | 筆數、QR 圖、網址文字（顏色在 theme.qss） |
| `delete_urban_plan_dialog.ui` | 刪除都市計畫確認 | `DeleteUrbanPlanDialog` | 標題、說明文字（「刪除」按鈕的紅色在 theme.qss） |
| `set_urban_plan_dialog.ui` | 設定都市計畫 | `SetUrbanPlanDialog` | 筆數說明、計畫選項、下方摘要文字（灰色在 theme.qss）、「套用」能不能按 |
| `backup_management_dialog.ui` | 備份管理 | `BackupManagementDialog` | 三個設定值、「儲存並執行」文字、另外兩顆「立即壓縮／立即清理」按鈕（提示字灰色在 theme.qss） |
| `existing_contact_picker_dialog.ui` | 選擇既有關係人 | `ExistingContactPickerDialog` | `contactTableSlot` 換成關係人表格、按鈕文字 |
| `deactivate_relation_dialog.ui` | 確認停用關係 | `DeactivateRelationDialog` | 說明文字（含姓名）、按鈕文字 |
| `help_dialog.ui` | 使用說明 | `HelpDialog` | 每個分頁的內容（來自程式裡的說明文字） |
| `land_details_dialog.ui` | 土地詳細資料 | `LandDetailsDialog` | 上方摘要文字（底色在 theme.qss）、表格欄位和內容 |
| `previous_export_duplicates_dialog.ui` | 偵測到已匯出過的地主 | `PreviousExportDuplicatesDialog` | 標題（寄信等情況）、說明文字、清單內容、「繼續匯出」文字 |

## 11. 表格加按鈕的對話框（第 3 批）

做法同第 10 節。表格（QTableWidget）的**欄位標題寫在 .ui 裡**，可以在 Designer 雙擊表格改標題文字；**每一列的資料、欄寬的伸縮方式（哪一欄自動撐滿）由程式設定**。不要在 Designer 裡增刪表格欄位：程式是照欄位順序放資料的，欄數不對資料會錯位（匯入預覽例外，它的欄位由匯入的 Excel 決定）。

| .ui 檔（在 `ui\dialogs\`） | 畫面 | 預覽名稱 | 程式會改寫的部分（在 .ui 改無效） |
|---|---|---|---|
| `dashboard_dialog.ui` | 資料統計儀表板 | `DashboardDialog` | 上方統計摘要、表格內容 |
| `record_history_dialog.ui` | 單筆修改歷史 | `RecordHistoryDialog` | 上方標題（有選資料時）、表格內容 |
| `follow_up_list_dialog.ui` | 追蹤提醒清單 | `FollowUpListDialog` | 「共有 N 筆」標題、表格內容與逾期底色 |
| `import_preview_dialog.ui` | 匯入預覽 | `ImportPreviewDialog`、`ImportPreviewDialog-plans` | 摘要、表格欄位與內容；「略過重複／更新既有」只在有重複時出現；有都市計畫時 `planChoiceSlot` 換成「這批資料屬於」選單 |
| `saved_search_dialog.ui` | 常用搜尋條件 | `SavedSearchDialog` | 表格內容 |
| `operation_log_dialog.ui` | 操作記錄 | `OperationLogDialog` | 表格內容 |
| `watchlist_dialog.ui` | 注意名單管理 | `WatchlistDialog` | 表格內容 |
| `tag_management_dialog.ui` | 標籤管理 | `TagManagementDialog` | 表格內容與標籤顏色、右下按鈕文字（新增標籤／儲存修改） |
| `customer_tags_dialog.ui` | 設定資料標籤 | `CustomerTagsDialog` | 說明文字（有選資料時）、標籤清單 |
| `batch_customer_tags_dialog.ui` | 批量設定標籤 | `BatchCustomerTagsDialog` | 筆數說明、處理方式選項、標籤清單 |
| `attachment_dialog.ui` | 附件管理 | `AttachmentDialog` | 說明文字（有選資料時）、表格內容 |
| `custom_field_management_dialog.ui` | 自訂欄位管理 | `CustomFieldManagementDialog` | 表格內容 |
| `contact_log_dialog.ui` | 聯絡紀錄 | `ContactLogDialog` | 說明文字（有選資料時）、表格內容 |
| `health_check_dialog.ui` | 系統健康檢查 | `HealthCheckDialog` | 表格內容 |
| `recycle_bin_dialog.ui` | 回收桶 | `RecycleBinDialog` | 表格內容 |
| `undo_operations_dialog.ui` | 批次操作復原 | `UndoOperationsDialog` | 表格內容、「復原選取操作」按鈕 |
| `notification_center_dialog.ui` | 通知中心 | `NotificationCenterDialog` | 表格內容 |
| `import_profiles_dialog.ui` | Excel 匯入設定檔 | `ImportProfilesDialog` | 上方說明裡的「可用代碼」清單、表格內容 |
| `report_templates_dialog.ui` | 報表與列印範本 | `ReportTemplatesDialog` | 表格內容、右側欄位勾選清單 |
| `duplicate_finder_dialog.ui` | 智慧重複資料檢查 | `DuplicateFinderDialog` | 表格內容 |
| `backup_status_dialog.ui` | 備份狀態 | `BackupStatusDialog` | 右欄每一個 `xxxValue` 的內容（左欄項目名稱可以改） |
| `server_backup_targets_dialog.ui` | 家中伺服器異地備份 | `ServerBackupTargetsDialog` | 表格內容 |
| `server_backup_restore_dialog.ui` | 還原家中伺服器備份 | `ServerBackupRestoreDialog` | 表格內容、確認欄的灰色提示字、「開始還原」文字與能不能按 |
| `urban_plan_management_dialog.ui` | 都市計畫管理 | `UrbanPlanManagementDialog`、`UrbanPlanManagementDialog-readonly` | 表格內容、各欄寬度、按鈕能不能按、唯讀帳號的提示字（說明文字灰色在 theme.qss） |

預覽：`python tools\preview_dialog.py --list` 會列出全部 47 個預覽名稱（第 2、3 批，部分對話框有兩種狀態）。

## 12. 主視窗的清單列、土地標題、關係人分頁（第 4 批）

這 5 個是主視窗裡的元件，各自一個 .ui 檔（在 `ui\main\`），程式開啟主視窗時載入、放到原本的位置。預覽用 `python tools\preview_main_window.py --sample`。

| .ui 檔（在 `ui\main\`） | 位置 | 不能改名或刪除的元件 | 程式會改寫的部分（在 .ui 改無效） |
|---|---|---|---|
| `plan_view_bar.ui` | 左側清單上方「檢視／輸入到／全部展開／全部收合」 | `planViewBar`（最外層）、`planViewLabel`、`planViewCombo`、`planInputLabel`、`planInputCombo`、`expandAllButton`、`collapseAllButton`、`planHintLabel` | 兩個下拉的選項；沒有連家中主機或沒有都市計畫時，「檢視」「輸入到」兩組會被隱藏；右邊提示字 |
| `batch_bar.ui` | 勾選資料後出現在清單上方的藍色列 | `batchBar`（最外層）、`batchBarCount`、`batchBar_field_visit_action`、`batchBar_assign_case_action`、`batchBar_batch_tags_action`、`batchBar_batch_edit_action`、`batchBar_export_selected_action`、`batchBar_clear_checked_action` | 「已勾選 N 筆」、按鈕能不能按、整列顯示或隱藏；**排列方式由程式決定**（太窄時自動換行），所以這個檔沒有版面，在 Designer 只能改按鈕文字與屬性 |
| `list_footer.ui` | 左側清單下方的顏色圖例與分頁 | `listFooter`（最外層）、`legendChecked`、`legendWatchlist`、`legendOverdue`、`legendNote`、`landCountLabel`、`previousPageButton`、`landPageLabel`、`nextPageButton` | 「土地 N 筆｜地主…」、「第 N / N 頁」、上一頁／下一頁能不能按（圖例色塊的顏色在 theme.qss） |
| `land_header.ui` | 右上角土地標題（地區、地號、面積、公告現值、都市計畫、持分條） | `landHeaderLocation`、`landHeaderNumber`、`landHeaderMetric_area/value/plan`、`landHeaderValue_area/value/plan`、`shareBarSlot` | 所有文字；地號的大標題字型；沒有都市計畫時隱藏「都市計畫」欄；`shareBarSlot` 換成程式畫的持分條 |
| `owner_contacts.ui` | 右側「關係人」分頁 | `ownerContactsOwnerLabel`、七個按鈕（`addButton` … `refreshButton`）、`showInactiveCheckBox`、`listViewButton`、`treeViewButton`、三個縮放按鈕、`viewStack`、`ownerContactsTable`、`ownerContactsStatusLabel` | 「目前地主：…」、狀態說明、表格內容、按鈕能不能按、「編輯／查看」文字（唯讀帳號顯示「查看」）；樹狀圖由程式畫，放在 `viewStack` 第二頁 |

顏色（批量列底色、圖例色塊、土地標題灰字、關係人姓名粗體…）都在 `ui\theme.qss` 最後一段「主視窗清單區」「右上角土地標題、關係人分頁」。

## 13. 大型對話框（第 5 批）

這批對話框裡有些部分是**依資料產生的**（例如每個自訂欄位一列、每個月的日期格子、每個檢查項目一個勾選框）。這些在 .ui 裡是一個**空的容器**，程式開啟時把內容放進去：容器本身（位置、間距）可以在 Designer 調整，但不要在裡面放元件，也不要刪掉或改名。

| .ui 檔 | 畫面 | 預覽名稱 | 空容器（程式放內容） | 程式會改寫的部分（在 .ui 改無效） |
|---|---|---|---|---|
| `dialogs\data_quality_rules_dialog.ui` | 選擇資料品質檢查項目 | `DataQualityRulesDialog` | `ruleCheckBoxesContainer`：每個檢查項目一個勾選框 | 快速模式選項、模式說明文字 |
| `dialogs\data_quality_dialog.ui` | 資料品質檢查結果 | `DataQualityDialog` | — | 上方摘要、篩選選項、兩個表格的內容、按鈕能不能按 |
| `dialogs\visit_calendar_dialog.ui` | 行程月曆 | `VisitCalendarDialog` | `calendarGrid`：星期列與每天的日期格子（格子的顏色依行程狀態由程式決定） | 月份標題、摘要、當天清單（圖例顏色在 theme.qss） |
| `dialogs\column_visibility_dialog.ui` | 欄位顯示 | `ColumnVisibilityDialog` | `columnVisibilityContent`：每個表格欄位一個勾選框 | — |
| `dialogs\advanced_search_dialog.ui` | 進階搜尋 | `AdvancedSearchDialog` | `advancedSearchContent`：每個可搜尋欄位一列 | 輸入框裡帶入的條件 |
| `dialogs\shared_land_batch_dialog.ui` | 同地號批量新增 | `SharedLandBatchDialog` | — | 帶入的地區／地段、自動完成清單、下方狀態列的文字與顏色 |
| `dialogs\customer_custom_values_dialog.ui` | 設定自訂欄位 | `CustomerCustomValuesDialog` | `customFieldsContainer`：每個自訂欄位一列（欄位由資料庫決定） | 上方說明文字（有選資料時） |
| `dialogs\batch_customer_custom_values_dialog.ui` | 批量設定自訂欄位 | `BatchCustomerCustomValuesDialog` | `customFieldsContainer`：每個自訂欄位一個勾選框加輸入框 | 「將處理 N 筆」說明 |
| `dialogs\text_template_dialog.ui` | 快速範本管理 | `TextTemplateDialog` | — | 表格內容、用途選項 |
| `main\owner_contact_group.ui` | 關係人編輯：「關係人共用資料」區塊 | `OwnerContactDialog-new`、`-edit`、`-view` | `matchTableSlot`：新增時的「可能相符的既有關係人」表格 | 新增以外的模式會隱藏搜尋／連結那幾列；「👁 顯示／隱藏」文字；唯讀時全部停用；「戶籍地址同地主」能不能按 |
| `main\owner_relation_group.ui` | 關係人編輯：「與目前地主的關係」區塊 | 同上 | — | 關係類型選項、「關係補充」的提示字 |
| `dialogs\user_management_dialog.ui` | 使用者與權限管理 | `UserManagementDialog` | — | 表格內容、角色選項 |
| `dialogs\backup_targets_dialog.ui` | 異地備份（單機版） | `BackupTargetsDialog` | — | 表格內容 |
| `dialogs\workflow_dialog.ui` | 案件規劃（案件、任務兩個分頁） | `WorkflowDialog` | — | 表格內容、任務的「案件」選項、日期欄的「未設定」、勾選資料的說明文字 |
| `dialogs\map_locations_dialog.ui` | 地圖與地號視覺化 | `MapLocationsDialog` | `mapViewSlot`：右側地圖（網頁元件） | 表格內容、查座標服務說明、資料ID |
| `main\import_plan_choice.ui` | 匯入預覽裡的「這批資料屬於」 | `ImportPreviewDialog-plans` | — | 都市計畫選項（說明文字灰色在 theme.qss） |
| `main\import_plan_result_section.ui` | 匯入結果裡的都市計畫區塊 | `ImportResultDialog-plan` | — | 所有文字；沒有「沒變更歸屬」的土地時，下面的說明、表格、匯出按鈕會隱藏 |

關係人編輯視窗本身（新增時的捲動頁、編輯時上方的「此區資料由多位地主共用」提示）仍由程式組合，因為新增和編輯兩種模式的排法不同；兩個區塊和提示的顏色都已經在 theme.qss（`ownerContactSharedNotice`、`ownerContactOwnerCount`、`ownerContactRelationNotice`、`matchHint`、`linkBanner`）。

預覽：`python tools\preview_dialog.py --list` 現在列出 64 個預覽名稱。地圖預覽需要網頁元件，開啟會比較慢。

## 14. 全部完成之後：打包新版客戶端

五批都完成後，請 Claude 打包新版客戶端。打包後**一定要實際開一次 exe**，確認：

1. 程式開得起來、主畫面外觀正常（這代表 PySide6 的 QtUiTools 和 `ui\` 資料夾都有被包進去）。
2. 打開幾個對話框（例如登入、標籤管理、資料品質檢查、行程月曆、地圖）都正常。
3. 如果開啟時跳出「找不到介面檔」，表示 `ui\` 資料夾沒有被包進去，請把訊息截圖給 Claude。

**不要直接改安裝好的程式裡的 .ui**：打包後 .ui 檔會放在程式資料夾的 `LandCustomerSystem\_internal\ui\`。那裡的檔案雖然看得到，但只是打包時的複本；直接改它會讓這台電腦的畫面和原始碼不一致，下次更新也會被蓋掉。要調整介面一律改**專案資料夾裡的 `ui\`**（原始碼），預覽確認後交給 Claude 重新打包。

## 15. Fluent 元件（Windows 11 風格，F1 起）

從 Fluent 第 1 批起，主視窗工具列、右側基本資料表單，以及第 10 節那 20 個對話框裡的按鈕、輸入框、下拉選單、勾選框、數字框，換成 PySide6-Fluent-Widgets 的 Fluent 元件。Fluent 第 2 批再把第 11 節那 24 個表格加按鈕的對話框換掉，連同表格（TableWidget）和勾選清單（ListWidget）。Fluent 第 3 批換第 12 節的主視窗元件（檢視列、批量列、清單下方的分頁鈕、關係人分頁），以及關係人編輯的兩個區塊、都市計畫匯入的選單與結果區，還有狀態列的「備份」「通知」按鈕。Fluent 第 4 批（最後一批）換第 13 節的大型對話框、各處的確定／取消列（DialogButtonBox），以及程式建立的勾選框、輸入框；到此全部完成。分批計畫與對應表見 `docs\Fluent改造計畫.md`。

**在 Designer 裡怎麼用**

- 用 `tools\open_designer.bat` 開 Designer。新增元件時從元件盒的「Fluent …」群組拖進表單，存檔即可，程式會自動認得（不用改程式碼）。
- 已經放好的一般元件要換成 Fluent：在元件上按右鍵 →「提升為…」（Promote to），「提升的類別名稱」填 Fluent 類別（例如 `PrimaryPushButton`），「標頭檔」填 `qfluentwidgets`，按「加入」再「提升」。基礎類別要選對：

| Fluent 類別 | 基礎類別（從什麼元件提升） | 用途 |
|---|---|---|
| `PushButton` | QPushButton | 一般按鈕 |
| `PrimaryPushButton` | QPushButton | 主要動作（儲存、套用、確定），綠底 |
| `TransparentPushButton` | QPushButton | 工具列文字按鈕、無框按鈕 |
| `LineEdit` | QLineEdit | 輸入框 |
| `PasswordLineEdit` | QLineEdit | 密碼框（自己遮字、右邊有顯示密碼鈕） |
| `ComboBox` | **QPushButton** | 下拉選單（Fluent 的下拉不是 QComboBox，要從按鈕提升） |
| `PlainTextEdit` | QPlainTextEdit | 多行文字 |
| `CheckBox` | QCheckBox | 勾選框 |
| `SpinBox` | QSpinBox | 數字框 |
| `TableWidget` | QTableWidget | 表格（F2 起；欄位標題照樣在 Designer 雙擊修改） |
| `ListWidget` | QListWidget | 清單、勾選清單 |
| `ToggleButton` | QPushButton | 可按下／彈起的切換鈕（關係人的「列表／樹狀圖」）；類別名稱要寫 `ToggleButton`，不要寫 `TogglePushButton` |
| `DialogButtonBox` | QDialogButtonBox | 確定／取消列；**標頭檔填 `customer_fluent`**（不是 qfluentwidgets）。在 Designer 裡看起來是一般按鈕，程式執行時換成 Fluent 按鈕 |

- **把下拉選單從 QComboBox 換成 ComboBox、或反過來，程式也要跟著改**（取得選項的寫法不同）；這種請交給 Claude。按鈕、輸入框、勾選框互換 Fluent／一般版本則不用改程式。
- objectName、版面、容器的規則和前面各節一樣（容器保持一般 QWidget，不要提升）。

**改主色、字型**：打開 `ui\fluent_theme.json`。

- `primaryColor`：淺色主題的主色（預設 `#2F6B4F`，和原本的綠一樣）。
- `darkPrimaryColor`：深色主題的主色（預設 `#6DBE93`，原本深色主題的綠）。
- `fontFamilies`：字型清單，由前往後找電腦裡有的第一個（預設「Microsoft JhengHei UI」）。
- 字體**大小**不在這裡：Fluent 元件跟著程式的「設定 → 字體大小」一起變。
- 寫錯（色碼打錯、少逗號）程式照樣開，會改用預設值，錯誤寫在記錄檔。改完重開程式生效。

**改個別 Fluent 元件的樣子**：Fluent 元件自己帶樣式，而且會蓋過 `theme.qss`，所以要寫在 `ui\fluent_widgets.qss`（選擇器用 Fluent 類別名稱，例如 `QFrame#searchGroup LineEdit`、`TransparentPushButton#deleteRecordButton`）。`theme.qss` 裡前面有一點的規則（`.QPushButton`、`.QLineEdit`…）只套在一般 Qt 元件上，那個點不要拿掉。

**哪些不是 Fluent（維持原樣）**

- 文字標籤（QLabel）：顏色、字級由 theme.qss 控制。
- 分頁（QTabWidget）、捲動區、分割線、各種容器。
- 土地清單樹、都市計畫樹、持分條、關係人樹狀圖、月曆格子、選單。
- 日期框（外勤排程、案件規劃）。
- 案件規劃的狀態／優先順序選項現在由程式加入（customer_productivity.py），在 Designer 裡改無效；要改請交給 Claude。
- 關係人分頁的分組框（QGroupBox）、切換列表／樹狀圖的頁面容器（QStackedWidget）。

**Fluent 表格的樣子（F2）**：沒有格線、列比較高、隔列淡底色，選取的列左邊有一條綠色，滑過時整列淡淡變色。程式設定的儲存格底色（追蹤逾期、注意名單、標籤顏色）現在會照實顯示。欄位多的表格（例如標籤管理的「顏色」欄）字比較寬，可能會出現「…」，把對話框拉寬即可。

**和原本不同的操作**：Fluent 的下拉選單不能用鍵盤上下鍵直接換選項（要按空白鍵或滑鼠打開選單再選）；密碼框右邊多一個眼睛按鈕可以暫時顯示密碼。Tab 鍵的順序和原本一樣（眼睛、數字框箭頭不佔 Tab）。

**移除 Fluent**：見 `docs\Fluent改造計畫.md` 最後一節。

