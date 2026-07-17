# 土地資料系統

目前正式版：`v1.7.0`（建置日期：2026-07-17）

正式共用資料儲存在自架 `PostgreSQL`；Windows 桌面程式與 iPhone 行動版都透過 `FastAPI` 讀寫同一份資料。舊 `customers.db` 只保留為歷史安全備份與單機相容資料，不再作為手機同步來源。

目前桌面 UI 已改為 `PySide6`，保留原本的登入、加密、匯入、刪除與表單流程，並用較順的表格元件取代原本的 Tkinter Treeview。

## 最新功能

- 公司筆電已接通通知中心、案件工作流程與任務看板、回收桶、批次復原及兩筆資料合併；操作全部由家中 PostgreSQL 交易處理
- 管理員可由公司筆電新增帳號、調整角色／啟用狀態與重設密碼；每位使用者也可修改自己的登入密碼，共用資料金鑰不會離開登入工作階段
- 公司筆電可查看家中備份狀態、立即建立 PostgreSQL＋附件 ZIP、設定保留期限／數量及清理舊備份
- 遠端整庫還原、異地備份目的地與既有資料重新加密仍限定在家中主機，避免公司端誤操作取代正式資料
- 公司筆電首次啟動時直接輸入家中伺服器 NetBird IP，驗證成功後自動保存；IP 改變時可由「設定 ＞ 伺服器連線設定」修改，不必編輯檔案或重新打包
- 公司筆電桌面程式補齊 PostgreSQL 遠端工作流程：修改歷史、自訂欄位、快速範本、注意名單、操作記錄、座標、重複資料忽略與納管附件完整性檢查都會寫回家中伺服器
- API 模式開放批次修改、批次自訂欄位、匯入設定檔、報表範本、智慧重複檢查、地圖、勾選刪除與全部刪除；公司筆電不再因功能灰色而必須回家操作
- 高風險伺服器維護仍只留在家中主機：整庫還原、異地目的地與既有資料重新加密不會從公司端遠端執行
- 正式架構固定為「家中主機唯一伺服器」：PostgreSQL、FastAPI、附件與備份只放家中
- 新增公司筆電完整 Windows 桌面客戶端包，透過 NetBird HTTPS 直接讀寫家中 API，不安裝 PostgreSQL、不啟動本機 Server
- 公司客戶端即使直接點 EXE 也會由封裝設定強制使用家中 API；只在 LocalAppData 保存不含地主資料的介面偏好
- iPhone 維持 Safari／主畫面瀏覽器版，不需要安裝桌面程式
- 新增 NetBird 私人 VPN 外出連線：iPhone 不必和筆電位於同一個 Wi-Fi，也不用在路由器開放連接埠
- NetBird 防火牆只允許官方 CGNAT 私人網段 `100.64.0.0/10` 連到 HTTPS 8732／公開憑證 8733；PostgreSQL 5432 仍只監聽本機
- 修正手機熱點區網連線：防火牆規則支援公用網路但僅限同一子網路，啟動時會列出目前所有可用 LAN IP，切換網路後會更新 HTTPS 憑證
- 家中主機伺服器包最外層只保留 `啟動家中伺服器.bat`，避免誤開舊版 API、手機或測試啟動檔
- 啟動前會盤點 NetBird、PostgreSQL Server 與 pg_dump；缺少時先列出原因，必須由使用者輸入 Y 確認才會透過 winget 安裝
- 新增可安裝到 iPhone 主畫面的「地主開發助手」，可登入、搜尋地主／土地、查看持分、新增聯絡紀錄與設定追蹤
- 新增零月費區網 HTTPS：自建本機 CA 與伺服器憑證，手機帳密及敏感資料不以明文在 Wi-Fi 傳輸
- 新增 iPhone 公開憑證安裝頁，只提供 `.cer`，不會暴露資料庫或私鑰
- 新增 PostgreSQL + 附件壓縮備份；每 24 小時啟動前自動建立，保留 90 天／最多 30 份／至少 3 份，並用 `pg_restore --list` 驗證
- API 正式版桌面登入只驗證 PostgreSQL 帳號，不再依賴舊 SQLite 使用者資料
- 右側土地資料摘要不再展開超長附件網址；外部連結改顯示網站名稱與附件數量，其他過長摘要也會安全省略
- 長表單視窗會自動限制在螢幕可用範圍內；進階搜尋與欄位顯示可垂直捲動，底部操作按鈕固定可見
- 進階搜尋同一欄可用 `、`、`，` 或 `,` 輸入多個值並以「任一符合」比對；不同欄位仍須全部符合
- 進階搜尋可連續輸入多個欄位；套用時排除舊快速搜尋干擾，且忽略既有資料內的半形／全形空白
- 新增自架 FastAPI：沿用現有帳號、權限與加密金鑰，提供手機登入、地主／土地查詢、聯絡紀錄與追蹤 API
- 保留 SQLite／PostgreSQL 資料來源介面；正式桌面與手機工作流程使用 PostgreSQL
- 新增正規化 PostgreSQL 結構與唯讀預檢／確認式遷移工具，避免直接改寫正式 SQLite
- 刪除資料會進入回收桶，能完整還原土地資料及案件、標籤、附件、聯絡與提醒關聯
- Excel 匯入、同地號新增、批次修改與合併資料都有可操作的批次復原紀錄
- 新增管理員、編輯者、唯讀人員帳號，所有帳號安全共用同一份加密資料
- 附件可複製到系統附件庫，支援 SHA-256 完整性檢查並隨完整備份保存；外部附件的 HTTP／HTTPS 網址可安全交由預設瀏覽器開啟
- 異地備份可同步到 USB、NAS 或 OneDrive 資料夾；完整備份以使用者指定的備份密碼加密成 `.lcsbak`，可在災難復原時驗證、還原
- 案件新增負責人、期限、優先度、下一步與封存，另有任務和檢查清單看板
- 通知中心集中顯示今日到期及逾期的追蹤、案件和任務
- Excel 匯入設定檔可保存自訂表頭對應並設為預設
- Word 報表範本可自訂欄位、標題、頁首與頁尾
- 智慧重複檢查會計算相似度，可預覽後合併或忽略建議
- 地圖與地號功能可保存座標、搜尋 OpenStreetMap 並產生離線分布 HTML
- 案件、標籤、附件、自訂欄位、最近聯絡與追蹤狀態會直接顯示在主表與右側摘要
- 上述管理欄位可搜尋、排序，並隨 Excel、Word 與手機分享匯出
- 標籤顏色會套用到表格，可批量加入、移除或完全取代標籤
- 標籤儲存格顏色會優先保留；即使資料含備註、逾期或注意名單列色也不會被覆蓋
- 可批量設定或清除自訂欄位，也可把選取資料從案件移除
- 聯絡紀錄填寫下次追蹤日後會自動同步追蹤提醒
- 唯讀模式仍可查看案件、標籤、附件、範本與聯絡紀錄
- 匯入 `.xlsx` 前先顯示預覽表
- 匯入時自動偵測可能重複資料，可選擇全部匯入或略過重複
- 匯入完成後顯示結果報表，並可把錯誤列單獨匯出成 Excel
- 可把目前表格資料匯出成 Excel
- 記住表格欄寬、欄位顯示狀態與欄位順序
- 新增進階搜尋，可同時用多個欄位條件查找
- 可儲存與載入常用搜尋條件
- 勾選多筆後可批次修改欄位，套用前會先顯示預覽
- 狀態列顯示資料庫與最近備份狀態
- 設定選單可查看備份明細、立即建立備份或管理壓縮與清理規則
- windowed EXE 發生未預期錯誤時會顯示提示，並寫入 `logs/application-error.log`
- 非敏感搜尋條件會先由 SQLite 篩選，再解密候選資料
- 登入期間使用記憶體解密快取，資料變更後會自動失效

## 正式啟動

家中主機只執行：

```text
啟動家中伺服器.bat
```

家中伺服器包最外層只有這一個 `.bat`。它會先盤點 NetBird、PostgreSQL Server 與 pg_dump；缺少時顯示清單與用途，只有使用者輸入 Y 才會安裝。之後依序確認 NetBird、PostgreSQL Windows 服務、`100.64.0.0/10` 私人網段防火牆、專案資料庫、HTTPS 憑證、公開 CA 安裝頁與每日備份。啟動後請保持視窗開啟。

iPhone 登入相同 NetBird 帳號後，第一次先開啟視窗顯示的 `http://100.x.x.x:8733/` 安裝公開 CA，再使用 `https://100.x.x.x:8732/mobile/`。完整步驟見 `伺服器使用說明.txt`。

公司筆電使用獨立的 `LandCustomerSystem-CompanyLaptopClient-v1.7.0-*.zip`。解壓縮後平常只需執行 `start_company_laptop_desktop.bat`；首次啟動直接輸入家中伺服器畫面顯示的 NetBird IP，程式會驗證 HTTPS、PostgreSQL API 與資料結構後自動保存。IP 改變時可由「設定 ＞ 伺服器連線設定」修改，不需編輯 `home_server_ip.txt`。完整步驟見 `公司筆電遠端使用說明.txt`。公司客戶端包不含 PostgreSQL、FastAPI Server、正式資料庫、帳密、備份或私鑰。

公司桌面版已開放完整遠端工作流，包含同地號批量新增、Excel 匯入／匯出、進階搜尋、資料品質、儀表板、案件、任務、通知、標籤、附件、聯絡紀錄、追蹤、回收桶、批次復原、合併、帳號密碼、重新加密、異地備份與伺服器還原。三項高風險維護都只操作家中主機，且需要管理員、還原前安全備份與二次確認；公司筆電不會建立第二份正式資料。

## PostgreSQL API 與手機同步

API 預設只監聽本機 `127.0.0.1:8732`，正式模式使用受 Windows DPAPI 保護的 PostgreSQL 連線設定。Windows 與 iPhone 每次都讀寫相同 PostgreSQL，不需要匯出 Excel 或手動同步。

安裝依賴並檢查正式資料：

```powershell
python -m pip install -r requirements-server.txt
python start_api_server.py --postgres --check
```

本機開發啟動：

```powershell
python start_api_server.py --postgres
```

瀏覽器可開啟 `http://127.0.0.1:8732/docs` 測試。可用功能包括：

- `POST /api/v1/auth/login`：使用桌面程式帳號登入
- `GET /api/v1/records`：查詢土地持分明細
- `POST /api/v1/records`：新增土地持分明細並自動計算坪數與總現值
- `PUT /api/v1/records/{id}`：完整修改土地持分明細
- `DELETE /api/v1/records/{id}`：移入回收筒後刪除土地持分明細
- `POST /api/v1/imports/records`：以單一 PostgreSQL 交易批量新增／更新 Excel 資料並建立匯入批次紀錄
- `GET /api/v1/owners`：依地主彙整土地、坪數與總現值
- `GET /api/v1/lands`：依地區、地段、地號彙整地主及持分
- `GET /api/v1/follow-ups`：查詢追蹤提醒
- `GET /api/v1/records/{id}/follow-up`：讀取單筆追蹤提醒
- `POST /api/v1/records/{id}/contact-logs`：新增聯絡／拜訪紀錄
- `DELETE /api/v1/records/{id}/contact-logs/{log_id}`：刪除指定聯絡紀錄
- `PUT /api/v1/records/{id}/follow-up`：更新下次追蹤
- `DELETE /api/v1/records/{id}/follow-up`：清除單筆追蹤提醒
- `GET／POST /api/v1/tags`：列出或建立標籤
- `PUT／DELETE /api/v1/tags/{tag_id}`：修改或刪除標籤
- `GET／PUT /api/v1/records/{id}/tags`：讀取或完整取代單筆資料標籤
- `PUT /api/v1/tags/assignments`：批量加入、移除或取代多筆資料標籤
- `GET／POST /api/v1/projects`：列出或建立案件
- `PUT／DELETE /api/v1/projects/{project_id}`：修改或刪除案件
- `PUT /api/v1/projects/{project_id}/records`：批量加入或移出案件資料
- `GET／POST /api/v1/records/{id}/attachments`：列出附件或新增外部檔案連結
- `POST /api/v1/records/{id}/attachments/upload`：上傳到系統附件庫，預設單檔上限 50 MB
- `GET /api/v1/records/{id}/attachments/{attachment_id}/content`：下載具權限的納管附件
- `DELETE /api/v1/records/{id}/attachments/{attachment_id}`：刪除附件資料及納管檔案

檢視者只能讀取資料且身分證會遮罩；管理員與編輯者才能新增、修改、刪除資料、新增聯絡紀錄或修改追蹤。登入工作階段只存在伺服器記憶體，重新啟動 API 後必須重新登入；連續登入失敗會暫時鎖定。

正式手機與公司筆電連線一律由 `啟動家中伺服器.bat` 啟動，並透過 NetBird 使用 HTTPS。未加密 LAN 參數只保留開發測試，不可用於正式帳密或地主資料。不要在路由器開放 API 或 PostgreSQL。

### PostgreSQL 初次設定

正規化結構位於 `postgres/schema.sql`。版本 3 除了 `owners`、`lands`、`ownerships`、`contact_logs`、`projects` 與 `users`，也完整建立案件成員、任務、標籤、自訂欄位、附件、位置、重複審查、異動紀錄、通知、範本、回收筒、復原、觀察名單、操作紀錄及家中伺服器異地備份目的地。敏感地主欄位仍使用現有 `enc:v1:` 加密格式，不會因換資料庫而改存明文。

Windows 首次安裝完成後，直接執行：

```powershell
啟動家中伺服器.bat
```

第一次需要時，流程會要求輸入安裝 PostgreSQL 時設定的管理密碼。工具會建立 `land_customer` 資料庫與最低範圍的 `land_customer_app` 應用程式帳號；管理密碼不會儲存，應用程式連線資料會由 Windows DPAPI 加密保存在目前 Windows 使用者的本機設定目錄。

本專案目前已完成資料庫設定，正式工作流程不再執行 SQLite／PostgreSQL 比對或重複遷移。健康檢查：

```powershell
python start_api_server.py --postgres --check
```

完整操作請看 `伺服器使用說明.txt`。

## 登入與加密

第一次啟動時會要求設定主要帳號 `admin` 的密碼。登入後可由「設定 → 使用者與權限」新增管理員、編輯者或唯讀人員。

新設定或修改的密碼至少需要 10 個字元；連續登入失敗 5 次會暫停登入 30 秒。

密碼不會明文儲存，會以 salted PBKDF2 hash 存在 PostgreSQL 的 `users` 資料表。

系統以登入密碼安全包裝共用資料金鑰，因此每位授權使用者可用自己的密碼解密同一份資料。以下欄位會加密儲存：

- 姓名
- 身分證
- 地址
- 備註
- 出訪記錄

新儲存與新匯入的資料會自動加密。既有明文資料可按 UI 上的「加密既有資料」按鈕轉成加密儲存。

注意：如果忘記登入密碼，已加密資料將無法解密。

在 `設定 -> 修改密碼` 可更新目前登入帳號的密碼，不會影響其他使用者。主要 admin 帳號不能停用或移除管理員權限。

## UI 欄位

地區、地段、序號、地號、面積/m2、公告現值、分子、分母、坪數、總現值/元、姓名、身分證、地址、原因、備註、出訪記錄、案件、標籤、附件數、附件內容、自訂欄位、最近聯絡、下次追蹤、追蹤狀態

## Excel 匯入

建議 Excel 第一個工作表直接使用下列表頭：

地區、地段、序號、地號、面積/m2、公告現值、分子、分母、坪數、總現值/元、姓名、身分證、地址、原因、備註、出訪記錄

匯入時仍支援舊表頭，例如：區、段、登記次序、所有權人、ID、登記原因、總計公告現值。

如果 Excel 沒有「坪數」，系統會用 `面積/m2 × 0.3025` 自動計算。

如果 Excel 沒有「總現值/元」，系統會用 `面積/m2 × 公告現值 × 分子 ÷ 分母` 自動計算。

匯入支援合併儲存格；如果同一個地區、地段、姓名、地址等欄位只在第一列填寫，下面列空白，系統會自動沿用上一筆值。

## 其他功能

- 匯入 `.xlsx`
- 匯入結果報表
- 匯入錯誤列匯出
- 勾選多筆後清除資料
- 勾選多筆後批次修改
- 全部清除資料，需連續 3 次確認
- 加密既有資料
- 啟動及每 6 小時檢查每日自動備份 `customers.db`
- 匯入、批次刪除、全部清除、加密既有資料、修改密碼前自動備份
- `設定` 內可管理 ZIP 壓縮、保留天數、最多份數、修改密碼、還原備份與開啟備份資料夾
- 上方工具列可用欄位篩選、排序、進階搜尋與常用條件

## PostgreSQL 備份位置

正式備份預設放在：

```text
%LOCALAPPDATA%\LandCustomerSystem\postgres-backups
```

`啟動家中伺服器.bat` 會在啟動前檢查最近 24 小時是否已有備份；沒有就自動建立。備份失敗時會明確警告並寫入診斷檔，不會把密碼或 DSN 寫進記錄。

每份 ZIP 包含經 `pg_restore --list` 驗證的 `database.dump`、`manifest.json` 與納管附件。預設保留 90 天、最多 30 份，且永遠至少保留最新 3 份。舊 SQLite 備份功能只供歷史相容版本使用，不是 PostgreSQL 正式版的還原來源。

## 開發與測試

### 程式模組

- `customer_ui_qt.py`：桌面應用程式組合根、登入流程、相容介面與啟動協調。
- `customer_window_ui.py`、`customer_table_ui.py`：主視窗、表單、表格及分組功能選單建構。
- `customer_desktop_state.py`、`customer_selection_workflows.py`：權限／健康狀態、視窗生命週期與表格選取狀態。
- `customer_record_workflows.py`：客戶資料新增、修改、批次操作、刪除及密碼更新流程。
- `customer_management_workflows.py`：案件、標籤、附件、自訂欄位、聯絡紀錄與資料合併流程。
- `customer_productivity_workflows.py`、`customer_settings_workflows.py`：品質檢查、追蹤、報表、備份與桌面偏好設定。
- `customer_desktop_data.py`：集中切換 SQLite 本機儲存與 PostgreSQL API 記錄儲存。
- `customer_health.py`、`customer_analytics.py`：不依賴 Qt 的健康檢查與儀表板彙總服務。
- `customer_dialogs.py`：搜尋、匯入、批次修改、設定與管理對話框。
- `customer_models.py`：客戶清單的 Qt 資料模型與分批載入。
- `customer_auth.py`：首次設定密碼與登入對話框。
- `customer_mobile_share.py`：手機 QR Code、區域網路臨時分享與安全標頭。
- `customer_api/app.py`：FastAPI 組合根，只負責設定、依賴、中介層、路由及手機靜態網站掛載。
- `customer_api/routes_*.py`：依記錄、聯絡、追蹤、專案、標籤、附件及彙總檢視拆分的 API 路由。
- `customer_api/schemas.py`、`customer_api/dependencies.py`：請求驗證模型與 Bearer 工作階段／角色權限依賴。
- `customer_api/middleware.py`、`customer_api/aggregates.py`：手機安全標頭與地主／土地讀取模型彙總。
- `customer_api/data_sources.py`、`customer_api/data_source_base.py`：穩定資料來源入口、共用協定與記錄轉換。
- `customer_api/sqlite_*.py`、`customer_api/postgres_*.py`：依記錄、協作、專案、標籤及附件拆分的後端實作。
- `customer_api/local_postgres.py`：使用 Windows DPAPI 保護本機 PostgreSQL 專案連線資料。
- `customer_mobile_web/`：可加入 iPhone 主畫面的地主開發助手。
- `setup_local_https.py`：建立私人本機 CA 與區網 HTTPS 憑證。
- `install_iphone_certificate_server.py`：只提供公開 CA 的 iPhone 安裝頁。
- `backup_postgresql.py`：PostgreSQL、manifest 與附件壓縮備份、驗證及保留清理。
- `start_api_server.py`：預設只監聽本機的安全 API 啟動器。
- `home_server_runtime.ps1`：唯一伺服器入口背後的 NetBird、PostgreSQL、HTTPS、備份與診斷協調流程。
- `migrate_sqlite_to_postgresql.py`：只保留給歷史資料一次性轉入使用；正式工作流程不再執行比對。
- `啟動家中伺服器.bat`：正式交付包唯一可執行的伺服器啟動檔。
- `postgres/schema.sql`：地主、土地、持分正規化的 PostgreSQL schema。
- `customer_search_controller.py`：分頁瀏覽、背景搜尋執行緒與搜尋結果套用流程。
- `customer_search_presets.py`：進階搜尋條件、常用搜尋的保存、載入及清除。
- `customer_ui_state.py`：欄寬、欄序、隱藏欄位及勾選／選取狀態持久化。
- `customer_excel.py`：Excel 欄位辨識、驗證、匯入匯出及背景工作執行器。
- `customer_export_controller.py`：表格複製、手機分享、可見欄位與 Excel 匯出流程。
- `customer_import_controller.py`：Excel 匯入、重複判定、注意名單與同地號批量新增。
- `customer_backup_status.py`：資料庫完整性、備份時間、空間統計、壓縮/清理設定與定時維護。
- `customer_domain.py`：土地持分、坪數、總現值、格式化及重複資料判定。
- `customer_migrations.py`：資料庫 schema 版本、逐版升級與遷移紀錄。
- `customer_database.py`：SQLite 連線、完整性檢查、ZIP 備份、保留策略與安全還原。
- `customer_repository.py`：設定、帳號、操作紀錄、觀察名單與資料庫遷移。
- `customer_productivity.py`：回收桶、多使用者、附件納管、異地備份、工作流、通知、報表、重複檢查與地圖。
- `customer_security.py`：密碼雜湊、金鑰衍生與客戶欄位加解密。
- `build_data_guard.py`：重新打包時保存及還原部署資料。

正式 UI 透過 FastAPI 存取 PostgreSQL；SQLite 僅保留裝置偏好與歷史相容用途。安全與權限邏輯集中在 API／資料層。

安裝固定版本的執行依賴：

```powershell
python -m pip install -r requirements.txt
```

執行自動測試：

```powershell
python -m unittest discover -s tests -v
```

目前共有 187 項自動測試，涵蓋 PostgreSQL 正式登入、API 權限與 CRUD、iPhone PWA、安全標頭、私人 CA／HTTPS、NetBird VPN IP 偵測與防火牆安全範圍、公司桌面包強制遠端 HTTPS、只建立介面偏好資料庫、桌面 HTTPS CA 驗證、PostgreSQL 壓縮備份、異地同步、交易式還原、既有資料加密、Excel 匯入、案件、標籤、附件、聯絡、追蹤，以及既有 SQLite 相容、回收桶、批次復原、工作流、通知、報表、地圖、小螢幕對話框與完整 UI 流程。

## 打包成 EXE

在 `outputs/customer_system` 資料夾執行：

```powershell
.\build_exe.bat
```

完成後會產生：

```text
dist\LandCustomerSystem\
```

打包後可在隔離的臨時資料夾執行正式版驗收，不會接觸正式資料：

```powershell
.\dist\LandCustomerSystem\LandCustomerSystem.exe --release-smoke-report .\release-acceptance-report.json
```

驗收涵蓋真實 Qt 視窗建構、首次啟動、登入、新增、批量新增、搜尋、Excel／Word 匯出、十項生產力功能、重開狀態、備份還原、損壞資料庫拒絕及重新打包資料保護。

重新打包時，腳本會先保存既有 `dist\LandCustomerSystem\customers.db`、`backups`、`attachments` 與 `logs`，打包成功後再自動放回。若打包中途失敗，資料會保留在專案內的 `.build-preserved-data`，不會隨 `dist` 清理而遺失。

這是 one-folder 版本。請把整個 `LandCustomerSystem` 資料夾一起複製到另一台 Windows 電腦，不要只拿單一 `.exe`。

程式在一般 Python 模式與 EXE 模式都會把資料庫放在程式所在資料夾的 `customers.db`。如果目標電腦沒有這個檔案，第一次啟動時會自動建立。

## 搬到另一台電腦的建議

1. 複製整個 `dist\LandCustomerSystem\` 資料夾。
2. 如果要帶既有資料，請一起複製 `customers.db` 與 `attachments`，或使用「異地完整備份」產生 `.lcsbak`。
3. 在新電腦直接執行 `LandCustomerSystem.exe`。
4. 建議設定 USB、NAS 或 OneDrive 同步資料夾作為異地備份目的地。
