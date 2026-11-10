# Fluent 改造計畫（PySide6-Fluent-Widgets）

目標：把桌面客戶端的按鈕、輸入框、下拉選單、勾選框等換成 Windows 11 風格的 Fluent 元件，
做法沿用 .ui 檔：在 Qt Designer 裡把元件「提升」成 Fluent 類別（header 填 `qfluentwidgets`），
程式載入 .ui 時自動認得。容器（QWidget／QFrame）、版面、objectName、Tab 順序、訊號都不變。

- 套件：PySide6-Fluent-Widgets 1.11.3（GPLv3 版；使用者 2026-11-02 確認自用不需商業授權），
  連帶 PySideSix-Frameless-Window 0.8.2、darkdetect 0.8.0。PySide6 維持 6.11.1。
- 主色、字型：`ui\fluent_theme.json`；Fluent 元件的局部外觀：`ui\fluent_widgets.qss`。
- 每批流程：備份 → 改 .ui 與程式 → 全部測試 → 新舊截圖（淺／深）→ 使用者驗收 → 下一批。

## 分批

| 批次 | 內容 | 數量 | 狀態 |
|---|---|---|---|
| F1 | 基礎（套件、載入器註冊、主題設定檔、theme.qss 不蓋 Fluent、Designer 外掛）＋主視窗工具列、基本資料表單＋原第 2 批 20 個小對話框 | 1＋20 | ✅ 已完成（2026-11-03 驗收） |
| F2 | 原第 3 批表格型管理對話框（紀錄歷史、追蹤清單、儀表板、儲存的搜尋、操作紀錄、注意名單、標籤管理、客戶標籤 2、附件、自訂欄位管理、聯絡紀錄、健康檢查、回收桶、復原、通知中心、匯入設定檔、報表範本、重複資料、匯入預覽、備份狀態、伺服器備份 2、都市計畫管理） | 24 | ✅ 已完成（2026-11-05 驗收） |
| F3 | 主視窗其他元件：檢視列、分頁列、批量列、土地標題、關係人分頁（ui\main\*.ui）、狀態列按鈕 | 9 | ✅ 已完成（2026-11-05 驗收） |
| F4 | 原第 5 批大型對話框（資料品質 2、拜訪月曆、進階搜尋、欄位顯示、共有土地批次、自訂欄位值 2、文字範本、關係人編輯、使用者管理、備份目的地、工作流程、地圖、都市計畫匯入結果 2）及程式動態產生的列；各處標準確定／取消列；自繪元件配色；整理 theme.qss | 16 | ✅ 已完成，待驗收 |

F2 起表格（QTableWidget）換成 Fluent 的 TableWidget、清單（QListWidget）換成 ListWidget；樹狀（QTreeWidget）與自繪的土地清單、都市計畫樹不換。

## 元件對應表

| 原本 | 換成（Fluent） | Designer 提升時的「基礎類別」 | 程式要注意 |
|---|---|---|---|
| QPushButton（一般） | PushButton | QPushButton | 無 |
| QPushButton（主要動作：儲存、套用、確定、登入…） | PrimaryPushButton | QPushButton | 原本的 `variant="primary"` 屬性拿掉 |
| QPushButton（工具列文字鈕、刪除） | TransparentPushButton | QPushButton | 原本的 `variant="ghost"`／`"danger-text"` 拿掉；刪除的紅字寫在 fluent_widgets.qss |
| QLineEdit | LineEdit | QLineEdit | 無 |
| QLineEdit（密碼） | PasswordLineEdit | QLineEdit | 拿掉 echoMode（元件自己遮字、右側有顯示密碼鈕） |
| QComboBox | ComboBox | **QPushButton** | Fluent 的下拉不是 QComboBox：`find_child(..., QComboBox)` 要改成 Fluent 的 ComboBox；`addItem(文字, 資料)` 要寫成 `addItem(文字, userData=資料)`（第二個位置參數在 Fluent 是圖示）；沒有鍵盤上下鍵換選項、沒有 `setCurrentIndex(-1)` |
| QPlainTextEdit | PlainTextEdit | QPlainTextEdit | 無 |
| QCheckBox | CheckBox | QCheckBox | 無 |
| QPushButton（可切換：關係人「列表／樹狀圖」） | ToggleButton | QPushButton | 注意類別名稱是 `ToggleButton`（套件裡的 `TogglePushButton` 只是別名，寫在 .ui 裡程式認不得） |
| QSpinBox | SpinBox | QSpinBox | 上下箭頭不進 Tab 順序（程式處理） |
| QDateEdit | **不換** | — | Fluent 的 DateEdit 和月曆彈出的箭頭疊在一起；外勤排程、案件規劃的日期框都保留原生 |
| QDialogButtonBox（確定／取消列） | DialogButtonBox | QDialogButtonBox（標頭檔填 `customer_fluent`） | 程式自己的類別：載入後把標準按鈕換成 Fluent 按鈕（確定／儲存為綠色主要按鈕），文字、角色、Enter／Esc 不變；`button(QDialogButtonBox.Ok)` 拿到的是 Fluent 按鈕；`addButton("文字", 角色)` 也會建立 Fluent 按鈕 |
| QLabel | **不換** | — | 文字顏色、字級大量由 theme.qss 的 objectName 規則控制，換成 BodyLabel 會被 Fluent 蓋掉 |
| QTabWidget、QScrollArea、QSplitter、QFrame、QWidget 容器 | **不換** | — | Fluent 沒有對應的容器；容器維持 native="true" |
| QTableWidget | TableWidget | QTableWidget | 資料、欄寬、排序、選取都照舊由程式設定。外觀差異：沒有格線、列高 38、隔列淡底色、選取列左側一條主色、選取與滑過為圓角底色；程式設定的儲存格底色（逾期、注意名單、標籤顏色）會照實顯示（舊版被 theme.qss 蓋掉看不到） |
| QListWidget | ListWidget | QListWidget | 勾選框由 Fluent 畫，點勾選框切換，和原本一樣 |
| QTreeWidget／QTreeView | **不換** | — | 都市計畫樹、土地清單樹是自繪，Fluent 沒有對應的樹狀表格 |

## 不換的自繪元件（F4 只調配色）

- 土地清單樹狀表格 LandTreeView 與儲存格繪製（標籤膠囊、持分條）
- 土地標題的持分條 ShareBarWidget
- 都市計畫樹 UrbanPlanTreeView 與自繪列
- 關係人樹狀圖 OwnerContactTreeView（QGraphicsView）
- 拜訪月曆的日期格子 _CalendarDayCell
- 選單（資料／工具／設定、右鍵選單）：仍是 QMenu，樣式照 theme.qss
- Qt 內建對話框：QMessageBox、QInputDialog、QFileDialog
- 地圖 QWebEngineView

## 技術重點（F1 建立，之後各批沿用）

- `customer_ui_loader.load_ui` 自動 `registerCustomWidget` qfluentwidgets 匯出的所有元件類別，並把
  `ui\fluent_widgets.qss` 加到每個 Fluent 元件上；密碼眼睛、數字箭頭不進 Tab 順序。
- `customer_fluent.py`：讀 `ui\fluent_theme.json`（讀失敗用預設，程式照常開）、套用主題／主色／字型；
  深色主色用設定檔的 darkPrimaryColor（Fluent 原本會把深色主色調成薄荷綠）；Fluent 的字級跟著「字體大小」設定。
- `ui\theme.qss` 的按鈕／輸入框／下拉／選單規則改成 `.QPushButton` 這種「只套一般 Qt 元件」的寫法，
  不再蓋到 Fluent 元件（Qt 的 `QPushButton` 選擇器會連子類別一起套）。
- Designer 外掛：`tools\designer_plugins\register_fluent_widgets.py`，用 `tools\open_designer.bat` 開。
- （F2）Fluent 表格／清單只在滑鼠或鍵盤操作後才更新「選取列」的畫面；載入時自動接上選取與資料變動訊號，程式選取的列也會正確亮起。
- （F2）Fluent 表格儲存格的字原本比內文小一號（13 px），改成和內文同大小，並跟著「字體大小」設定。
- （F3）狀態列的「備份狀態」「通知」按鈕由程式建立，改成 Fluent PushButton；文字顏色用 `set_custom_style` 加在 Fluent 樣式之後（直接 setStyleSheet 會把 Fluent 樣式整個蓋掉）。
- （F3）批量列按鈕的藍字寫在 `ui\fluent_widgets.qss`；批量列的自動換行（FlowLayout）照舊。持分條、土地清單樹、都市計畫樹、關係人樹狀圖沒有動（F4 再調配色）。
- （F3）關係人編輯視窗唯讀時，程式會停用所有欄位；清單裡補上 Fluent 的下拉選單，唯讀時一樣不能改。
- （F4）程式建立的元件也換成 Fluent：資料品質規則與欄位顯示的勾選框、進階搜尋與自訂欄位值的輸入框、關係人編輯視窗下方的按鈕列、選既有聯絡人的表格（ContactChoiceTable 改繼承 Fluent TableWidget）。
- （F4）案件規劃的狀態／優先順序選項原本寫在 .ui 裡；Fluent 下拉不讀 .ui 的選項，改由程式加入（customer_productivity.py 的 CASE_STATUS_OPTIONS、TASK_STATUS_OPTIONS、PRIORITY_OPTIONS），選項文字不變。
- （F4）土地清單樹、都市計畫樹的列分隔線改用較淡的新色 `row_rule`（淺 #E5EAE6／深 #29312D），和 Fluent 表格的淡分隔一致；持分條、關係人樹狀圖、月曆格子原本就用主題色（主色和 Fluent 主色相同），不需改。
- （F4）theme.qss 移除只給已換成 Fluent 的元件用的規則（搜尋框內的下拉／輸入／按鈕、按鈕 variant 樣式、批量列按鈕、刪除都市計畫紅鈕、狀態列按鈕）；一般 Qt 元件仍會用到的規則（訊息框、輸入框對話框、檔案對話框、日期框、選單、樹狀表格、分頁）保留。

- （F4）`ui\fluent_widgets.qss` 只把「選擇器真的對得上」的規則加到該元件上（原本每個 Fluent 元件都附整份檔案；Qt 會替每個元件各自解析，元件多時吃光記憶體，造成完整測試隨機當掉）。字體大小即時更新也只處理 Fluent 自己登記的元件。改完後畫面逐點相同，完整測試時間由約 12 分鐘降到約 6 分鐘。

## 全部完成後仍不是 Fluent 的部分

- 文字標籤（QLabel）、分組框（QGroupBox）、分頁（QTabWidget）、捲動區、分割線、頁面切換容器（QStackedWidget）
- 日期框（QDateEdit）：外勤排程、案件規劃
- 選單：資料／工具／設定與右鍵選單（QMenu）
- Qt 內建對話框：QMessageBox、QInputDialog（例如「外觀主題」的選擇）、QFileDialog
- 自繪元件：土地清單樹、都市計畫樹、持分條、關係人樹狀圖、月曆格子（只調配色）
- 地圖的網頁區（QWebEngineView）
- 標準按鈕列中 Qt 內建的英文文字（例如 Close、Cancel）：和改造前一樣，沒有中文翻譯檔

## 回滾

- 單批回滾：把 `backup_fluent_20261103\<批次>\` 內的檔案複製回專案資料夾。
- 整個移除 Fluent：還原 F1 備份後執行
  `python -m pip uninstall PySide6-Fluent-Widgets PySideSix-Frameless-Window`
  （darkdetect 是原本就有的套件，保留），並把 requirements.txt 末三行刪掉。
