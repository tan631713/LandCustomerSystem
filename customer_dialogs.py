"""Reusable PySide6 dialogs with application dependencies injected at startup."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QCompleter,
    QFileDialog, QFrame,
    QGridLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from qfluentwidgets import CheckBox as FluentCheckBox
from qfluentwidgets import ComboBox as FluentComboBox
from qfluentwidgets import LineEdit as FluentLineEdit
from customer_responsive_dialog import ResponsiveDialog as QDialog
from customer_ui_loader import (
    chain_tab_order,
    find_child,
    install_ui,
    put_in_slot,
    size_like_unparented,
)

from customer_domain import parse_shared_land_rows
from customer_theme import qcolor, token
from customer_urban_plan_dialogs import ImportPlanChoice, ImportPlanResultSection
from customer_quality import (
    QUALITY_RULE_OPTIONS,
    QUALITY_RULE_PRESETS,
    write_quality_issues,
    write_quality_summary,
)

APP_DIR = Path.cwd()
LAND_FIELDS = ()
FONT_SIZE_OPTIONS = ()
DEFAULT_FONT_SIZE_KEY = "medium"
ADVANCED_SEARCH_FIELDS = ()
BATCH_EDITABLE_FIELDS = ()
ROW_TEXT_COLOR = qcolor("ink")
get_operation_logs = lambda: []
get_watchlist_entries = lambda: []
replace_watchlist_entries = lambda entries: None
write_error_rows = lambda file_path, rows, fields: None


def configure_dialogs(**dependencies):
    globals().update(dependencies)


HELP_SECTIONS = [
    (
        "快速開始",
        """
        <h2>快速開始</h2>
        <ol>
          <li>第一次開啟時，請先設定 <b>admin</b> 密碼。</li>
          <li>新增資料時，右側表單填完後按「儲存」。</li>
          <li>左側表格可勾選多筆資料，關閉後再開啟會保留勾選與選取狀態。</li>
          <li>上方搜尋可查土地欄位，也可查案件、標籤、自訂欄位、聯絡與追蹤狀態。</li>
        </ol>
        <p><b>建議：</b>大量修改或刪除前，先到「設定 → 立即備份」建立備份。</p>
        """,
    ),
    (
        "批量新增",
        """
        <h2>同地號批量新增</h2>
        <p>適合一次新增同地區、同地段（可再加小段）、同地號的多位所有權人。</p>
        <h3>上方共同欄位</h3>
        <ul>
          <li>地區、地段、小段、地號、面積、公告現值可一起填入；小段沒有的話可以留空。</li>
          <li>序號/登記次序可以手動輸入在每一列。</li>
        </ul>
        <h3>每列資料順序</h3>
        <p><code>登記次序、姓名、身分證、地址、分子、分母、原因、備註、出訪記錄</code></p>
        <p>可用頓號 <code>、</code> 或逗號 <code>，</code> 分隔，也可從 Excel 複製貼上。</p>
        <h3>範例</h3>
        <p><code>15、王弘益、H100059743、桃園市桃園區大華九街34號、108、3360</code></p>
        <p><b>身分證可以空白：</b></p>
        <p><code>16、王小明、、桃園市桃園區中正路1號、1、2</code></p>
        <p>如果只有前 6 欄，原因、備註與出訪記錄會自動留空。</p>
        """,
    ),
    (
        "Excel 匯入匯出",
        """
        <h2>Excel 匯入匯出</h2>
        <ul>
          <li>可從「資料 → 匯入 .xlsx」匯入土地資料。</li>
          <li>匯入前會先預覽資料，並標示可能重複或格式異常的列。</li>
          <li>可從「資料 → 匯出選取資料」匯出勾選或目前選取的資料（一定要先勾選或選取，不能匯出全部）。</li>
        </ul>
        <p><b>提示：</b>匯出會尊重目前表格欄位順序與隱藏欄位設定。</p>
        """,
    ),
    (
        "備份與還原",
        """
        <h2>備份與還原</h2>
        <ul>
          <li>系統啟動時會檢查資料庫與備份狀態。</li>
          <li>可從「設定 → 備份狀態」查看完整性檢查與最近備份。</li>
          <li>可從「設定 → 備份管理」設定 ZIP 壓縮、保留天數與最多份數，或立即壓縮／清理。</li>
          <li>可從「設定 → 立即備份」手動建立備份。</li>
          <li>可從「設定 → 還原備份」選擇 `.zip` 或 `.db` 備份檔還原。</li>
          <li>「設定 → 異地完整備份」可把資料庫與納管附件用獨立備份密碼加密成 `.lcsbak`，同步到 USB／NAS／OneDrive 資料夾，並可驗證或還原。</li>
        </ul>
        <p><b>還原注意：</b>還原會覆蓋目前資料庫。系統會先替目前資料建立安全備份，還原後會關閉程式，請重新開啟後再登入。</p>
        <p><b>完整備份密碼：</b>請保存建立 `.lcsbak` 時輸入的密碼；遺失後無法解密完整備份。</p>
        """,
    ),
    (
        "搜尋與選取",
        """
        <h2>搜尋與選取狀態</h2>
        <ul>
          <li>搜尋會掃描全部資料，不只目前畫面載入的頁面。</li>
          <li>可用欄位下拉選單限定搜尋範圍。</li>
          <li>可用排序欄位與升降冪調整顯示順序。</li>
          <li>勾選資料、目前選取資料、欄位寬度與欄位順序會在關閉後保留。</li>
          <li>可使用「工具 → 常用搜尋條件」儲存與載入常用查詢。</li>
        </ul>
        """,
    ),
    (
        "案件與分類",
        """
        <h2>案件、標籤與管理資料</h2>
        <ul>
          <li><b>案件：</b>先建立案件，再勾選多筆資料批量加入；需要移除時使用「勾選與批量操作 → 從案件移除選取資料」。</li>
          <li><b>標籤：</b>可建立彩色標籤，對單筆或多筆資料加入、移除或完全取代。</li>
          <li><b>自訂欄位：</b>建立額外欄位後，可對單筆填寫，也可批量設定或清除。</li>
          <li><b>附件：</b>預設複製到系統附件庫並隨完整備份保存；也可取消勾選，只保留外部檔案連結。</li>
          <li><b>聯絡紀錄：</b>新增後會顯示最近聯絡；填寫下次追蹤日會同步建立追蹤提醒。</li>
        </ul>
        <p>上述資料會顯示在主表與右側摘要，也能搜尋、排序並隨 Excel、Word 或手機分享匯出。</p>
        """,
    ),
    (
        "安全與進階功能",
        """
        <h2>安全、工作流程與進階功能</h2>
        <ul>
          <li><b>回收桶：</b>刪除後可還原資料及其案件、標籤、附件、聯絡與提醒。</li>
          <li><b>批次復原：</b>可復原 Excel 匯入、同地號新增、批次修改及合併。</li>
          <li><b>使用者與權限：</b>管理員可新增管理員、編輯者、唯讀人員；每人使用自己的密碼。</li>
          <li><b>案件工作流程：</b>設定負責人、期限、優先度、下一步、任務與檢查清單。</li>
          <li><b>通知中心：</b>集中查看今日到期及逾期的追蹤、案件和任務。</li>
          <li><b>匯入設定與報表：</b>保存 Excel 表頭對應及 Word 報表版面。</li>
          <li><b>智慧重複：</b>以身分證、地號、姓名、地址和序號計算相似度。</li>
          <li><b>地圖：</b>保存座標、查詢地理位置，直接在視窗內顯示地圖（桃園市範圍內可離線顯示，執行 download_offline_map_tiles.bat 下載離線圖磚），也可產生土地分布網頁匯出。</li>
        </ul>
        """,
    ),
    (
        "常見狀況",
        """
        <h2>常見狀況</h2>
        <h3>登入失敗</h3>
        <p>第一次使用請登入 <b>admin</b>；新增其他帳號後可改用各自帳號。請確認帳號已啟用及密碼正確，連續失敗過多會暫時鎖定。</p>
        <h3>批量新增跳錯誤</h3>
        <p>請先確認每列至少包含：登記次序、姓名、身分證、地址、分子、分母。身分證可空白，但分隔符號仍要保留。</p>
        <h3>備份過久或尚無備份</h3>
        <p>到「設定 → 立即備份」建立新的備份。</p>
        <h3>資料庫異常</h3>
        <p>請先不要大量修改資料，先檢查備份狀態，必要時用最近備份還原。</p>
        """,
    ),
]


class HelpDialog(QDialog):
    # Layout: ui/dialogs/help_dialog.ui; one tab per HELP_SECTIONS entry is added here.
    ui_file = "dialogs/help_dialog.ui"
    ui_object_names = ("helpTabs", "closeButton")

    def __init__(self, parent=None):
        super().__init__(parent)
        # Deliberately non-modal -- see show_help() in customer_window_ui.py.
        content = install_ui(self, self.ui_file, self.ui_object_names)

        self.tabs = find_child(content, "helpTabs", QTabWidget)
        for title, html in HELP_SECTIONS:
            browser = QTextBrowser()
            browser.setOpenExternalLinks(False)
            browser.setHtml(html)
            self.tabs.addTab(browser, title)

        close_button = find_child(content, "closeButton", QPushButton)
        close_button.clicked.connect(self.accept)
        # The pages joined the Tab order after 關閉; move 關閉 back behind them.
        if self.tabs.count():
            QWidget.setTabOrder(self.tabs.widget(self.tabs.count() - 1), close_button)


class DataQualityRulesDialog(QDialog):
    # Layout: ui/dialogs/data_quality_rules_dialog.ui; one check box per
    # QUALITY_RULE_OPTIONS entry is added to ruleCheckBoxesContainer here.
    ui_file = "dialogs/data_quality_rules_dialog.ui"
    ui_object_names = (
        "presetCombo",
        "presetHintLabel",
        "ruleCheckBoxesContainer",
        "selectAllButton",
        "clearAllButton",
        "cancelButton",
        "startButton",
    )

    def __init__(self, selected_rules=None, parent=None):
        super().__init__(parent)
        self.setModal(True)
        selected = set(selected_rules or [key for key, _label in QUALITY_RULE_OPTIONS])
        self.rule_checkboxes = {}
        self.preset_rules = {
            preset_key: tuple(rule_keys)
            for preset_key, _label, rule_keys, _description in QUALITY_RULE_PRESETS
        }
        self.preset_descriptions = {
            preset_key: description
            for preset_key, _label, _rule_keys, description in QUALITY_RULE_PRESETS
        }
        self._updating_preset = False
        content = install_ui(self, self.ui_file, self.ui_object_names)

        self.preset_combo = find_child(content, "presetCombo", FluentComboBox)
        for preset_key, label, _rule_keys, _description in QUALITY_RULE_PRESETS:
            self.preset_combo.addItem(label, userData=preset_key)
        self.preset_combo.addItem("自訂", userData="custom")
        self.preset_combo.currentIndexChanged.connect(self.apply_selected_preset)

        self.preset_hint_label = find_child(content, "presetHintLabel", QLabel)

        rules_layout = find_child(content, "ruleCheckBoxesContainer", QWidget).layout()
        for rule_key, label in QUALITY_RULE_OPTIONS:
            checkbox = FluentCheckBox(label)
            checkbox.setChecked(rule_key in selected)
            checkbox.stateChanged.connect(self.update_preset_selection)
            self.rule_checkboxes[rule_key] = checkbox
            rules_layout.addWidget(checkbox)

        select_all_button = find_child(content, "selectAllButton", QPushButton)
        select_all_button.clicked.connect(self.select_all)
        clear_button = find_child(content, "clearAllButton", QPushButton)
        clear_button.clicked.connect(self.clear_all)
        cancel_button = find_child(content, "cancelButton", QPushButton)
        cancel_button.clicked.connect(self.reject)
        start_button = find_child(content, "startButton", QPushButton)
        start_button.clicked.connect(self.accept)
        chain_tab_order([
            self.preset_combo,
            *self.rule_checkboxes.values(),
            select_all_button,
            clear_button,
            cancel_button,
            start_button,
        ])
        self.update_preset_selection()

    def selected_rules(self):
        return [
            rule_key
            for rule_key, checkbox in self.rule_checkboxes.items()
            if checkbox.isChecked()
        ]

    def selected_preset_key(self):
        selected = set(self.selected_rules())
        for preset_key, rule_keys in self.preset_rules.items():
            if selected == set(rule_keys):
                return preset_key
        return "custom"

    def update_preset_selection(self, _state=None):
        if self._updating_preset:
            return
        preset_key = self.selected_preset_key()
        self._updating_preset = True
        index = self.preset_combo.findData(preset_key)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)
        self._updating_preset = False
        self.update_preset_hint()

    def update_preset_hint(self):
        preset_key = self.preset_combo.currentData()
        if preset_key == "custom":
            self.preset_hint_label.setText("目前是自訂組合；按「開始檢查」後會保存這組勾選。")
            return
        self.preset_hint_label.setText(self.preset_descriptions.get(preset_key, ""))

    def apply_selected_preset(self, _index=None):
        if self._updating_preset:
            return
        preset_key = self.preset_combo.currentData()
        rule_keys = self.preset_rules.get(preset_key)
        if rule_keys is None:
            self.update_preset_hint()
            return
        selected = set(rule_keys)
        self._updating_preset = True
        for rule_key, checkbox in self.rule_checkboxes.items():
            checkbox.setChecked(rule_key in selected)
        self._updating_preset = False
        self.update_preset_hint()

    def select_all(self):
        self._updating_preset = True
        for checkbox in self.rule_checkboxes.values():
            checkbox.setChecked(True)
        self._updating_preset = False
        self.update_preset_selection()

    def clear_all(self):
        self._updating_preset = True
        for checkbox in self.rule_checkboxes.values():
            checkbox.setChecked(False)
        self._updating_preset = False
        self.update_preset_selection()

    def accept(self):
        if not self.selected_rules():
            QMessageBox.information(self, "請至少選擇一項", "請至少勾選一個品質檢查項目。")
            return
        super().accept()


class DataQualityDialog(QDialog):
    # Layout: ui/dialogs/data_quality_dialog.ui.
    ui_file = "dialogs/data_quality_dialog.ui"
    ui_object_names = (
        "summaryLabel",
        "filterCombo",
        "categorySummaryTable",
        "issuesTable",
        "copySummaryButton",
        "exportSummaryButton",
        "copyIssuesButton",
        "exportIssuesButton",
        "clearIgnoredButton",
        "ignoreFilteredButton",
        "ignoreSameCategoryButton",
        "ignoreIssueButton",
        "gotoIssueButton",
        "closeButton",
    )

    def __init__(
        self,
        issues,
        total_records=0,
        parent=None,
        on_issue_activated=None,
        on_issue_ignored=None,
        ignored_count=0,
        on_clear_ignored=None,
    ):
        super().__init__(parent)
        self.issues = list(issues)
        self.filtered_issues = list(self.issues)
        self.total_records = int(total_records or 0)
        self.on_issue_activated = on_issue_activated
        self.on_issue_ignored = on_issue_ignored
        self.ignored_count = int(ignored_count or 0)
        self.on_clear_ignored = on_clear_ignored
        self.setModal(True)
        content = install_ui(self, self.ui_file, self.ui_object_names)

        important_count = sum(1 for issue in self.issues if issue.severity == "重要")
        reminder_count = len(self.issues) - important_count
        total_issue_count = len(self.issues) + self.ignored_count
        if self.issues:
            title_text = (
                f"已檢查 {self.total_records} 筆資料，發現 {total_issue_count} 個提醒"
                f"（重要 {important_count}、提醒 {reminder_count}）。"
            )
            if self.ignored_count:
                title_text += f" 目前已隱藏 {self.ignored_count} 個已確認問題。"
        elif self.ignored_count:
            title_text = (
                f"已檢查 {self.total_records} 筆資料，目前沒有未確認品質問題；"
                f"已隱藏 {self.ignored_count} 個已確認問題。"
            )
        else:
            title_text = f"已檢查 {self.total_records} 筆資料，目前沒有發現明顯品質問題。"
        self.summary_label = find_child(content, "summaryLabel", QLabel)
        self.summary_label.setText(title_text)

        self.filter_combo = find_child(content, "filterCombo", FluentComboBox)
        self.filter_combo.addItem("全部問題", userData="all")
        self.filter_combo.addItem("重要", userData="severity:重要")
        self.filter_combo.addItem("提醒", userData="severity:提醒")
        self.filter_combo.addItem("疑似重複", userData="category:疑似重複")
        self.filter_combo.addItem("格式異常", userData="format")
        self.filter_combo.addItem("姓名空白", userData="category:姓名空白")
        self.filter_combo.addItem("地號缺漏", userData="category:地號缺漏")
        self.filter_combo.addItem("分母為 0", userData="category:分母為 0")
        self.filter_combo.currentIndexChanged.connect(self.apply_filter)
        self.filter_combo.setEnabled(bool(self.issues))

        self.category_summary_table = find_child(content, "categorySummaryTable", QTableWidget)
        self.category_summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.category_summary_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.category_summary_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.category_summary_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.category_summary_table.itemClicked.connect(self.filter_by_summary_item)
        size_like_unparented(self.category_summary_table)
        self.load_category_summary()

        self.table = find_child(content, "issuesTable", QTableWidget)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.itemDoubleClicked.connect(self.activate_current_issue)
        size_like_unparented(self.table)
        self.load_issues()

        self.goto_button = find_child(content, "gotoIssueButton", QPushButton)
        self.goto_button.clicked.connect(self.activate_current_issue)
        self.ignore_button = find_child(content, "ignoreIssueButton", QPushButton)
        self.ignore_button.clicked.connect(self.ignore_current_issue)
        self.ignore_filtered_button = find_child(content, "ignoreFilteredButton", QPushButton)
        self.ignore_filtered_button.clicked.connect(self.ignore_filtered_issues)
        self.ignore_same_category_button = find_child(content, "ignoreSameCategoryButton", QPushButton)
        self.ignore_same_category_button.clicked.connect(self.ignore_same_category_issues)
        self.clear_ignored_button = find_child(content, "clearIgnoredButton", QPushButton)
        self.clear_ignored_button.clicked.connect(self.clear_ignored_issues)
        self.copy_summary_button = find_child(content, "copySummaryButton", QPushButton)
        self.copy_summary_button.clicked.connect(self.copy_summary)
        self.export_summary_button = find_child(content, "exportSummaryButton", QPushButton)
        self.export_summary_button.clicked.connect(self.export_summary)
        self.copy_button = find_child(content, "copyIssuesButton", QPushButton)
        self.copy_button.clicked.connect(self.copy_current_issues)
        self.export_button = find_child(content, "exportIssuesButton", QPushButton)
        self.export_button.clicked.connect(self.export_issues)
        find_child(content, "closeButton", QPushButton).clicked.connect(self.accept)
        self.update_action_buttons()

    def category_summary_counts(self):
        summary = {}
        for issue in self.issues:
            row = summary.setdefault(issue.category, {"重要": 0, "提醒": 0, "合計": 0})
            if issue.severity == "重要":
                row["重要"] += 1
            else:
                row["提醒"] += 1
            row["合計"] += 1
        return sorted(
            summary.items(),
            key=lambda item: (-item[1]["合計"], item[0]),
        )

    def summary_rows(self):
        rows = [
            {
                "category": category,
                "important": counts["重要"],
                "reminder": counts["提醒"],
                "total": counts["合計"],
            }
            for category, counts in self.category_summary_counts()
        ]
        if self.ignored_count:
            rows.append(
                {
                    "category": "已確認隱藏",
                    "important": "",
                    "reminder": "",
                    "total": self.ignored_count,
                }
            )
        return rows

    def load_category_summary(self):
        summary_rows = self.category_summary_counts()
        self.category_summary_table.setRowCount(len(summary_rows))
        for row_number, (category, counts) in enumerate(summary_rows):
            values = [
                category,
                str(counts["重要"]),
                str(counts["提醒"]),
                str(counts["合計"]),
            ]
            for column_number, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, category)
                if counts["重要"] > 0:
                    item.setBackground(qcolor("watch"))
                    item.setForeground(ROW_TEXT_COLOR)
                self.category_summary_table.setItem(row_number, column_number, item)
        self.category_summary_table.resizeRowsToContents()

    def select_category_filter(self, category):
        filter_value = f"category:{category}"
        index = self.filter_combo.findData(filter_value)
        if index < 0:
            self.filter_combo.addItem(category, userData=filter_value)
            index = self.filter_combo.findData(filter_value)
        self.filter_combo.setCurrentIndex(index)

    def filter_by_summary_item(self, item):
        if item is None:
            return
        category = item.data(Qt.UserRole)
        if category:
            self.select_category_filter(category)

    def load_issues(self):
        self.table.setRowCount(len(self.filtered_issues))
        for row_number, issue in enumerate(self.filtered_issues):
            values = [
                str(issue.record_id),
                issue.severity,
                issue.category,
                issue.summary,
                issue.suggestion,
            ]
            for column_number, value in enumerate(values):
                item = QTableWidgetItem(value)
                if issue.severity == "重要":
                    item.setBackground(qcolor("watch"))
                    item.setForeground(ROW_TEXT_COLOR)
                self.table.setItem(row_number, column_number, item)
        self.table.resizeRowsToContents()

    def issue_matches_filter(self, issue):
        filter_value = self.filter_combo.currentData()
        if filter_value in (None, "all"):
            return True
        if filter_value == "format":
            return issue.category.endswith("格式異常")
        if isinstance(filter_value, str) and filter_value.startswith("severity:"):
            return issue.severity == filter_value.split(":", 1)[1]
        if isinstance(filter_value, str) and filter_value.startswith("category:"):
            return issue.category == filter_value.split(":", 1)[1]
        return True

    def apply_filter(self):
        self.filtered_issues = [
            issue for issue in self.issues
            if self.issue_matches_filter(issue)
        ]
        self.load_issues()
        self.load_category_summary()
        self.update_summary_text()
        self.update_action_buttons()

    def update_summary_text(self):
        important_count = sum(1 for issue in self.issues if issue.severity == "重要")
        reminder_count = len(self.issues) - important_count
        total_issue_count = len(self.issues) + self.ignored_count
        ignored_text = f" 已隱藏 {self.ignored_count} 個已確認問題。" if self.ignored_count else ""
        if not self.issues:
            if self.ignored_count:
                self.summary_label.setText(
                    f"已檢查 {self.total_records} 筆資料，目前沒有未確認品質問題；"
                    f"已隱藏 {self.ignored_count} 個已確認問題。"
                )
                return
            self.summary_label.setText(
                f"已檢查 {self.total_records} 筆資料，目前沒有發現明顯品質問題。"
            )
            return
        filter_label = self.filter_combo.currentText()
        if self.filter_combo.currentData() in (None, "all"):
            self.summary_label.setText(
                f"已檢查 {self.total_records} 筆資料，發現 {total_issue_count} 個提醒；"
                f"目前顯示 {len(self.issues)} 個未確認提醒"
                f"（重要 {important_count}、提醒 {reminder_count}）。{ignored_text}"
            )
            return
        self.summary_label.setText(
            f"已檢查 {self.total_records} 筆資料，全部 {total_issue_count} 個提醒；"
            f"目前顯示「{filter_label}」{len(self.filtered_issues)} 筆未確認問題。{ignored_text}"
        )

    def update_action_buttons(self):
        has_visible_issues = bool(self.filtered_issues)
        has_summary = bool(self.summary_rows())
        self.goto_button.setEnabled(has_visible_issues)
        self.ignore_button.setEnabled(has_visible_issues)
        self.copy_button.setEnabled(has_visible_issues)
        self.export_button.setEnabled(has_visible_issues)
        self.ignore_filtered_button.setEnabled(has_visible_issues)
        self.ignore_same_category_button.setEnabled(has_visible_issues)
        self.copy_summary_button.setEnabled(has_summary)
        self.export_summary_button.setEnabled(has_summary)
        self.clear_ignored_button.setEnabled(self.ignored_count > 0)

    def summary_text(self):
        rows = ["類型\t重要\t提醒\t合計"]
        for row in self.summary_rows():
            rows.append(
                "\t".join(
                    [
                        str(row.get("category", "")),
                        str(row.get("important", "")),
                        str(row.get("reminder", "")),
                        str(row.get("total", "")),
                    ]
                )
            )
        return "\n".join(rows)

    def current_issues_text(self):
        rows = ["資料ID\t程度\t類型\t問題\t建議處理"]
        for issue in self.filtered_issues:
            rows.append(
                "\t".join(
                    [
                        str(issue.record_id),
                        issue.severity,
                        issue.category,
                        issue.summary,
                        issue.suggestion,
                    ]
                )
            )
        return "\n".join(rows)

    def current_issue(self):
        row_number = self.table.currentRow()
        if row_number < 0 or row_number >= len(self.filtered_issues):
            return None
        return self.filtered_issues[row_number]

    def activate_current_issue(self, *_args):
        issue = self.current_issue()
        if issue is None:
            return
        if self.on_issue_activated is not None:
            self.on_issue_activated(issue.record_id)
        self.accept()

    def ignore_current_issue(self):
        issue = self.current_issue()
        if issue is None:
            return
        if self.on_issue_ignored is not None:
            self.on_issue_ignored(issue)
        self.issues = [
            existing_issue for existing_issue in self.issues
            if existing_issue != issue
        ]
        self.ignored_count += 1
        self.apply_filter()
        QMessageBox.information(
            self,
            "已確認並隱藏",
            "此品質提醒已加入已確認清單；下次檢查相同問題時會自動隱藏。",
        )

    def ignore_issue_group(self, issues, title, message):
        unique_issues = []
        seen = set()
        for issue in issues:
            key = (issue.record_id, issue.category, issue.summary, issue.suggestion)
            if key in seen:
                continue
            seen.add(key)
            unique_issues.append(issue)
        if not unique_issues:
            return
        reply = QMessageBox.question(
            self,
            title,
            message.format(count=len(unique_issues)),
        )
        if reply != QMessageBox.Yes:
            return
        if self.on_issue_ignored is not None:
            for issue in unique_issues:
                self.on_issue_ignored(issue)
        ignored_set = set(unique_issues)
        self.issues = [issue for issue in self.issues if issue not in ignored_set]
        self.ignored_count += len(unique_issues)
        self.apply_filter()
        QMessageBox.information(
            self,
            "已批量確認",
            f"已確認並隱藏 {len(unique_issues)} 個品質提醒；下次檢查相同問題時會自動隱藏。",
        )

    def ignore_filtered_issues(self):
        self.ignore_issue_group(
            list(self.filtered_issues),
            "確認目前篩選",
            "確定要把目前篩選出的 {count} 個品質提醒全部標記為已確認嗎？",
        )

    def ignore_same_category_issues(self):
        issue = self.current_issue()
        if issue is None:
            return
        self.ignore_issue_group(
            [candidate for candidate in self.issues if candidate.category == issue.category],
            "確認同類型",
            f"確定要把「{issue.category}」同類型的 {{count}} 個品質提醒全部標記為已確認嗎？",
        )

    def clear_ignored_issues(self):
        if self.ignored_count <= 0:
            return
        cleared_count = self.ignored_count
        if self.on_clear_ignored is not None:
            self.on_clear_ignored()
        self.ignored_count = 0
        self.update_summary_text()
        self.update_action_buttons()
        QMessageBox.information(
            self,
            "已清除",
            f"已清除 {cleared_count} 個已確認品質提醒；下次執行檢查時會重新顯示。",
        )

    def copy_current_issues(self):
        if not self.filtered_issues:
            QMessageBox.information(self, "沒有可複製的資料", "目前篩選條件下沒有資料品質檢查結果。")
            return
        QApplication.clipboard().setText(self.current_issues_text())
        QMessageBox.information(
            self,
            "已複製",
            f"已複製 {len(self.filtered_issues)} 筆資料品質檢查結果，可直接貼到 Excel 或訊息中。",
        )

    def copy_summary(self):
        summary_rows = self.summary_rows()
        if not summary_rows:
            QMessageBox.information(self, "沒有可複製的摘要", "目前沒有資料品質檢查摘要。")
            return
        QApplication.clipboard().setText(self.summary_text())
        QMessageBox.information(
            self,
            "已複製摘要",
            f"已複製 {len(summary_rows)} 筆品質檢查摘要，可直接貼到 Excel 或訊息中。",
        )

    def export_summary(self):
        summary_rows = self.summary_rows()
        if not summary_rows:
            QMessageBox.information(self, "沒有可匯出的摘要", "目前沒有資料品質檢查摘要。")
            return
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "匯出資料品質檢查摘要",
            str(APP_DIR / f"data-quality-summary-{datetime.now().strftime('%Y%m%d-%H%M%S')}.xlsx"),
            "Excel 檔案 (*.xlsx)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"
        try:
            write_quality_summary(file_path, summary_rows)
        except Exception as exc:
            QMessageBox.critical(self, "無法匯出", str(exc))
            return
        QMessageBox.information(
            self,
            "匯出完成",
            f"已匯出 {len(summary_rows)} 筆資料品質檢查摘要。\n檔案位置：{file_path}",
        )

    def export_issues(self):
        if not self.filtered_issues:
            QMessageBox.information(self, "沒有可匯出的資料", "目前篩選條件下沒有資料品質檢查結果。")
            return
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "匯出資料品質檢查結果",
            str(APP_DIR / f"data-quality-{datetime.now().strftime('%Y%m%d-%H%M%S')}.xlsx"),
            "Excel 檔案 (*.xlsx)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"
        try:
            write_quality_issues(file_path, self.filtered_issues)
        except Exception as exc:
            QMessageBox.critical(self, "無法匯出", str(exc))
            return
        QMessageBox.information(
            self,
            "匯出完成",
            f"已匯出 {len(self.filtered_issues)} 筆資料品質檢查結果。\n檔案位置：{file_path}",
        )


class DashboardDialog(QDialog):
    # Layout: ui/dialogs/dashboard_dialog.ui; the rows are filled here.
    ui_file = "dialogs/dashboard_dialog.ui"
    ui_object_names = ("summaryLabel", "statsTable", "closeButton")

    def __init__(self, stats, parent=None):
        super().__init__(parent)
        self.stats = stats
        # Deliberately non-modal -- see show_dashboard() in
        # customer_productivity_workflows.py.
        content = install_ui(self, self.ui_file, self.ui_object_names)

        find_child(content, "summaryLabel", QLabel).setText(
            " / ".join(
                [
                    f"總筆數 {stats.get('total_records', 0)}",
                    f"總面積 {stats.get('total_area', '0')}",
                    f"總公告現值 {stats.get('total_declared_value', '0')}",
                    f"總現值 {stats.get('total_current_value', '0')}",
                    f"待追蹤 {stats.get('open_follow_ups', 0)}",
                    f"案件 {stats.get('case_count', 0)}",
                    f"標籤 {stats.get('tag_count', 0)}",
                ]
            )
        )

        self.table = find_child(content, "statsTable", QTableWidget)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.load_rows()

        find_child(content, "closeButton", QPushButton).clicked.connect(self.accept)

    def load_rows(self):
        rows = []
        for label, value in (
            ("有身分證", self.stats.get("with_external_id", 0)),
            ("無身分證", self.stats.get("without_external_id", 0)),
            ("有備註", self.stats.get("with_note", 0)),
            ("有出訪記錄", self.stats.get("with_visit_log", 0)),
            ("已加入案件", self.stats.get("with_case", 0)),
            ("已有標籤", self.stats.get("with_tags", 0)),
            ("已有附件", self.stats.get("with_attachments", 0)),
            ("已有自訂欄位", self.stats.get("with_custom_values", 0)),
            ("已有聯絡紀錄", self.stats.get("with_contact", 0)),
        ):
            rows.append(("資料完整度", label, value, ""))
        for district, count in self.stats.get("district_counts", []):
            rows.append(("地區", district or "(空白)", count, ""))
        for section, count in self.stats.get("section_counts", []):
            rows.append(("地段", section or "(空白)", count, ""))
        for status, count in self.stats.get("follow_up_status_counts", []):
            rows.append(("追蹤狀態", status or "(未設定)", count, ""))
        for case_name, count, status in self.stats.get("case_counts", []):
            rows.append(("案件", case_name, count, status))
        for tag_name, count in self.stats.get("tag_counts", []):
            rows.append(("標籤", tag_name, count, ""))

        self.table.setRowCount(len(rows))
        for row_number, row in enumerate(rows):
            for column_number, value in enumerate(row):
                self.table.setItem(row_number, column_number, QTableWidgetItem(str(value)))
        self.table.resizeRowsToContents()


class RecordHistoryDialog(QDialog):
    # Layout: ui/dialogs/record_history_dialog.ui.
    ui_file = "dialogs/record_history_dialog.ui"
    ui_object_names = ("titleLabel", "historyTable", "closeButton")

    def __init__(self, logs, record_label="", parent=None):
        super().__init__(parent)
        self.logs = list(logs)
        self.setModal(True)
        content = install_ui(self, self.ui_file, self.ui_object_names)

        if record_label:
            find_child(content, "titleLabel", QLabel).setText(record_label)

        self.table = find_child(content, "historyTable", QTableWidget)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.load_rows()

        find_child(content, "closeButton", QPushButton).clicked.connect(self.accept)

    def load_rows(self):
        self.table.setRowCount(len(self.logs))
        for row_number, log in enumerate(self.logs):
            values = [
                log.get("created_at", ""),
                log.get("action_type", ""),
                log.get("field_label", ""),
                log.get("old_value", ""),
                log.get("new_value", ""),
                log.get("customer_id", ""),
            ]
            for column_number, value in enumerate(values):
                self.table.setItem(row_number, column_number, QTableWidgetItem(str(value or "")))
        self.table.resizeRowsToContents()


class FollowUpReminderDialog(QDialog):
    STATUS_OPTIONS = ("未處理", "已聯絡", "待回覆", "完成")

    # Layout: ui/dialogs/follow_up_reminder_dialog.ui.
    ui_file = "dialogs/follow_up_reminder_dialog.ui"
    ui_object_names = (
        "titleLabel",
        "dueDateEdit",
        "statusCombo",
        "noteEdit",
        "clearReminderButton",
        "cancelButton",
        "saveButton",
    )

    def __init__(self, record_label="", reminder=None, parent=None):
        super().__init__(parent)
        self.reminder = reminder
        self.delete_requested = False
        self.setModal(True)
        content = install_ui(self, self.ui_file, self.ui_object_names)

        self.due_date_edit = find_child(content, "dueDateEdit", QLineEdit)
        self.due_date_edit.setText(str((reminder or {}).get("due_date") or ""))
        self.status_combo = find_child(content, "statusCombo", FluentComboBox)
        current_status = str((reminder or {}).get("status") or "未處理")
        for status in self.STATUS_OPTIONS:
            self.status_combo.addItem(status, userData=status)
        status_index = self.status_combo.findData(current_status)
        self.status_combo.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.note_edit = find_child(content, "noteEdit", QPlainTextEdit)
        self.note_edit.setPlainText(str((reminder or {}).get("note") or ""))

        if record_label:
            find_child(content, "titleLabel", QLabel).setText(record_label)

        clear_button = find_child(content, "clearReminderButton", QPushButton)
        clear_button.clicked.connect(self.request_delete)
        clear_button.setEnabled(reminder is not None)
        find_child(content, "cancelButton", QPushButton).clicked.connect(self.reject)
        find_child(content, "saveButton", QPushButton).clicked.connect(self.accept)

    def values(self):
        return {
            "due_date": self.due_date_edit.text().strip(),
            "status": self.status_combo.currentData() or "未處理",
            "note": self.note_edit.toPlainText().strip(),
        }

    def request_delete(self):
        self.delete_requested = True
        self.accept()

    def accept(self):
        if self.delete_requested:
            super().accept()
            return
        due_date = self.due_date_edit.text().strip()
        if due_date:
            try:
                datetime.strptime(due_date, "%Y-%m-%d")
            except ValueError:
                QMessageBox.warning(self, "日期格式錯誤", "下次追蹤日請使用 YYYY-MM-DD，例如 2026-07-20。")
                return
        super().accept()


class FollowUpListDialog(QDialog):
    # Layout: ui/dialogs/follow_up_list_dialog.ui.
    ui_file = "dialogs/follow_up_list_dialog.ui"
    ui_object_names = ("titleLabel", "remindersTable", "closeButton")

    def __init__(self, reminders, parent=None, on_record_activated=None):
        super().__init__(parent)
        self.reminders = list(reminders)
        self.on_record_activated = on_record_activated
        # Deliberately non-modal -- see show_follow_up_list() in
        # customer_productivity_workflows.py.
        content = install_ui(self, self.ui_file, self.ui_object_names)

        find_child(content, "titleLabel", QLabel).setText(
            f"共有 {len(self.reminders)} 筆追蹤提醒；雙擊資料列可載入該筆資料。"
        )

        self.table = find_child(content, "remindersTable", QTableWidget)
        self.table.itemDoubleClicked.connect(self.activate_current_record)
        for column in range(7):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.load_rows()

        find_child(content, "closeButton", QPushButton).clicked.connect(self.accept)

    def load_rows(self):
        self.table.setRowCount(len(self.reminders))
        for row_number, reminder in enumerate(self.reminders):
            values = [
                reminder.get("due_date", ""),
                reminder.get("status", ""),
                reminder.get("owner_name", ""),
                reminder.get("district", ""),
                reminder.get("section", ""),
                reminder.get("subsection", ""),
                reminder.get("land_number", ""),
                reminder.get("note", ""),
            ]
            for column_number, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if reminder.get("is_overdue") and reminder.get("status") != "完成":
                    item.setBackground(qcolor("watch"))
                    item.setForeground(ROW_TEXT_COLOR)
                self.table.setItem(row_number, column_number, item)
        self.table.resizeRowsToContents()

    def current_reminder(self):
        row_number = self.table.currentRow()
        if row_number < 0 or row_number >= len(self.reminders):
            return None
        return self.reminders[row_number]

    def activate_current_record(self, *_args):
        reminder = self.current_reminder()
        if reminder is None:
            return
        if self.on_record_activated is not None:
            self.on_record_activated(reminder.get("customer_id"))
        self.accept()


def calendar_status_styles():
    """Visit-status colours, resolved from the active theme each time they are used."""

    return {
        "scheduled": {"label": "已排定", "bg": qcolor("info_bg"), "text": qcolor("info_ink")},
        "overdue": {"label": "已逾期", "bg": qcolor("watch"), "text": qcolor("seal")},
        "completed": {"label": "已完成", "bg": qcolor("success_bg"), "text": qcolor("success_ink")},
        "skipped": {"label": "已略過", "bg": qcolor("muted_bg"), "text": qcolor("muted_ink")},
    }


class _CalendarDayCell(QFrame):
    """One clickable day box inside VisitCalendarDialog's month grid.

    A plain QFrame subclass rather than a monkey-patched mousePressEvent
    on a generic QWidget -- overriding the virtual method through proper
    subclassing is the reliable way to make a non-button widget clickable
    in Qt; assigning to the instance attribute directly is a common but
    fragile shortcut.
    """

    def __init__(self, date_value, on_click):
        super().__init__()
        self.date_value = date_value
        self._on_click = on_click

    def mousePressEvent(self, event):
        if self._on_click is not None:
            self._on_click(self.date_value)
        super().mousePressEvent(event)


class VisitCalendarDialog(QDialog):
    """行程月曆 -- replaces the old separate 每日外勤紀錄 and 未來排程 dialogs.

    The user wanted a more intuitive way to see which landowners had been
    added to a field-visit route than two side-by-side tables they had to
    cross-reference by date themselves: a month calendar where each day
    cell shows, at a glance, who is on it and how that item stands --
    scheduled, overdue, completed, or skipped -- color-coded, with a
    detail list below for the selected day. See
    load_visit_calendar_items()/list_visit_calendar_items() (server and
    repository side) for how the two old data sources (unresolved
    schedule items, daily contact logs) are merged into this single list
    without double-counting.

    Works outside api_mode too, unlike the old 未來排程 (which used to
    refuse to open at all without a server connection): local/SQLite mode
    has no field-visit-route data, but still has contact_logs, so the
    calendar just shows less there (see
    CustomerRepository.list_visit_calendar_items()'s docstring) instead of
    being unavailable outright.
    """

    # Layout: ui/dialogs/visit_calendar_dialog.ui; the day cells of calendarGrid
    # are built here for each month.  Legend colours: ui/theme.qss.
    ui_file = "dialogs/visit_calendar_dialog.ui"
    ui_object_names = (
        "previousMonthButton",
        "monthLabel",
        "nextMonthButton",
        "mineOnlyCheckBox",
        "refreshButton",
        "calendarGrid",
        "summaryLabel",
        "detailTable",
        "closeButton",
    )

    def __init__(self, window, parent=None, on_record_activated=None):
        super().__init__(parent)
        self.window = window
        self.on_record_activated = on_record_activated
        self.items_by_date = {}
        self.selected_date = QDate.currentDate()
        self.displayed_month = QDate(self.selected_date.year(), self.selected_date.month(), 1)
        # Deliberately non-modal -- see the matching comment that used to
        # be on DailyContactLogDialog/UpcomingFieldVisitsDialog and
        # show_visit_calendar() in customer_productivity_workflows.py.
        # The .ui opens it at 980 wide -- a narrow 7-column grid was cutting
        # owner names off inside each day cell (user report: "行程月曆沒辦法
        # 很好的看到地主名稱").
        content = install_ui(self, self.ui_file, self.ui_object_names)

        self.prev_button = find_child(content, "previousMonthButton", QPushButton)
        self.prev_button.clicked.connect(self.go_previous_month)
        self.month_label = find_child(content, "monthLabel", QLabel)
        self.next_button = find_child(content, "nextMonthButton", QPushButton)
        self.next_button.clicked.connect(self.go_next_month)
        # Defaults to unchecked (everyone's activity) -- same reasoning as
        # the two dialogs this replaces: a team-wide activity review, not
        # just a personal log.
        self.mine_only_checkbox = find_child(content, "mineOnlyCheckBox", QCheckBox)
        self.mine_only_checkbox.toggled.connect(self.refresh)
        find_child(content, "refreshButton", QPushButton).clicked.connect(self.refresh)

        self.grid_widget = find_child(content, "calendarGrid", QWidget)
        self.grid_layout = self.grid_widget.layout()

        self.summary_label = find_child(content, "summaryLabel", QLabel)

        self.table = find_child(content, "detailTable", QTableWidget)
        self.table.itemDoubleClicked.connect(self.activate_current_record)
        for column in range(5):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        size_like_unparented(self.table)

        find_child(content, "closeButton", QPushButton).clicked.connect(self.accept)

        self.refresh()

    def go_previous_month(self):
        self.displayed_month = self.displayed_month.addMonths(-1)
        self.refresh()

    def go_next_month(self):
        self.displayed_month = self.displayed_month.addMonths(1)
        self.refresh()

    def refresh(self, *_args):
        mine_only = self.mine_only_checkbox.isChecked()
        year = self.displayed_month.year()
        month = self.displayed_month.month()
        start_date = QDate(year, month, 1)
        end_date = QDate(year, month, start_date.daysInMonth())
        try:
            items = self.window.load_visit_calendar_items(
                start_date.toString("yyyy-MM-dd"),
                end_date.toString("yyyy-MM-dd"),
                mine_only=mine_only,
            )
        except Exception as exc:
            QMessageBox.warning(self, "讀取失敗", str(exc))
            items = []
        self.items_by_date = {}
        for item in items:
            date_key = str(item.get("date") or "")
            self.items_by_date.setdefault(date_key, []).append(item)
        self.month_label.setText(start_date.toString("yyyy年M月"))
        if self.selected_date.year() != year or self.selected_date.month() != month:
            today = QDate.currentDate()
            self.selected_date = today if (today.year() == year and today.month() == month) else start_date
        total_count = len(items)
        self.summary_label.setText(
            f"{start_date.toString('yyyy年M月')} 共有 {total_count} 筆行程／紀錄；"
            "點選日期可展開當天清單，雙擊清單列可載入該筆資料。"
        )
        self._rebuild_grid(start_date, end_date)
        self._update_detail()

    def _rebuild_grid(self, start_date, end_date):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                # setParent(None) detaches it from the screen immediately;
                # takeAt() alone only unmanages it from the layout, and
                # deleteLater() alone leaves it sitting at its old
                # geometry, visible and overlapping the freshly-built
                # cells, until the next event-loop pass actually runs the
                # deferred delete. Both together avoid the ghost-widget
                # overlap a plain deleteLater() produced when refresh()
                # ran twice in close succession (e.g. navigating months
                # quickly).
                widget.setParent(None)
                widget.deleteLater()

        for column, label_text in enumerate(["日", "一", "二", "三", "四", "五", "六"]):
            header_label = QLabel(label_text)
            header_label.setAlignment(Qt.AlignCenter)
            header_label.setStyleSheet(f"color: {token('ink2')}; font-size: 11px;")
            self.grid_layout.addWidget(header_label, 0, column)

        today = QDate.currentDate()
        cursor = QDate(start_date)
        row = 1
        column = cursor.dayOfWeek() % 7
        while cursor <= end_date:
            cell = self._make_day_cell(QDate(cursor), today)
            self.grid_layout.addWidget(cell, row, column)
            column += 1
            if column > 6:
                column = 0
                row += 1
            cursor = cursor.addDays(1)

    def _make_day_cell(self, date_value, today):
        date_key = date_value.toString("yyyy-MM-dd")
        items = self.items_by_date.get(date_key, [])

        cell = _CalendarDayCell(date_value, self._select_day)
        # Just tall enough for the date number plus two single-line name
        # pills -- a cell that wraps a long name just grows taller for
        # that one row on its own (QGridLayout sizes each row to its
        # tallest cell), it doesn't need every row reserving room for it.
        # Kept low deliberately: the calendar grid has no stretch factor
        # (see the layout.addWidget(self.grid_widget) call below), so its
        # total height is exactly this times 6 rows -- shrinking it is
        # what actually gives the detail list below more room, not a
        # stretch-factor change (grid_widget already yields all leftover
        # space to self.table's stretch=1; the grid's minimum footprint
        # was simply too tall to leave much of that space over).
        cell.setMinimumHeight(48)
        cell.setFrameShape(QFrame.StyledPanel)
        is_selected = date_value == self.selected_date
        is_today = date_value == today
        # The chosen day is shown by its background; today gets a green
        # outline and a day with overdue visits an amber one.
        background = token("green_tint") if is_selected else token("field")
        has_overdue = any(item.get("calendar_status") == "overdue" for item in items)
        if is_today:
            border = f"2px solid {token('green')}"
        elif has_overdue:
            border = f"2px solid {token('amber_ink')}"
        else:
            border = f"1px solid {token('rule')}"
        cell.setStyleSheet(
            f"QFrame {{ background: {background}; border: {border}; border-radius: 4px; }}"
        )

        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(3, 2, 3, 2)
        cell_layout.setSpacing(1)

        date_label = QLabel(str(date_value.day()))
        date_font = "font-weight: bold;" if date_value == today else ""
        date_color = token("green") if date_value == today else token("ink")
        date_label.setStyleSheet(f"color: {date_color}; font-size: 11px; {date_font}")
        cell_layout.addWidget(date_label)

        for item in items[:2]:
            status_styles = calendar_status_styles()
            style = status_styles.get(
                item.get("calendar_status"), status_styles["scheduled"]
            )
            owner_name = str(item.get("owner_name") or "")
            pill = QLabel(owner_name)
            # Wrap instead of letting the grid column clip long names --
            # a narrow 7-column-wide cell was cutting names off with no
            # way to see the rest without clicking through to the detail
            # list below. The tooltip is a second fallback for names that
            # still don't fully fit even after wrapping and widening the
            # dialog.
            pill.setWordWrap(True)
            pill.setToolTip(owner_name)
            pill.setStyleSheet(
                f"background: {style['bg'].name()}; color: {style['text'].name()};"
                " border-radius: 3px; padding: 0px 4px; font-size: 12px;"
            )
            cell_layout.addWidget(pill)

        if len(items) > 2:
            more_label = QLabel(f"+{len(items) - 2} 筆")
            more_label.setStyleSheet(f"color: {token('ink2')}; font-size: 10px;")
            cell_layout.addWidget(more_label)

        cell_layout.addStretch(1)
        return cell

    def _select_day(self, date_value):
        self.selected_date = date_value
        start_date = QDate(self.displayed_month.year(), self.displayed_month.month(), 1)
        end_date = QDate(
            self.displayed_month.year(), self.displayed_month.month(), start_date.daysInMonth()
        )
        self._rebuild_grid(start_date, end_date)
        self._update_detail()

    def _update_detail(self):
        date_key = self.selected_date.toString("yyyy-MM-dd")
        self.rows = self.items_by_date.get(date_key, [])
        self.table.setRowCount(len(self.rows))
        for row_number, item in enumerate(self.rows):
            status_styles = calendar_status_styles()
            style = status_styles.get(
                item.get("calendar_status"), status_styles["scheduled"]
            )
            values = [
                item.get("owner_name", ""),
                item.get("district", ""),
                item.get("section", ""),
                item.get("subsection", ""),
                item.get("land_number", ""),
                style["label"],
            ]
            for column_number, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                if column_number == 5:
                    cell.setForeground(style["text"])
                self.table.setItem(row_number, column_number, cell)
        self.table.resizeRowsToContents()

    def current_item(self):
        row_number = self.table.currentRow()
        if row_number < 0 or row_number >= len(self.rows):
            return None
        return self.rows[row_number]

    def activate_current_record(self, *_args):
        item = self.current_item()
        if item is None:
            # Diagnostic breadcrumb for a user report ("在行程月曆下我沒辦法
            # 雙擊讀取資料") that could not be reproduced through the normal
            # code paths -- if this ever fires for real, it pins the failure
            # down to the double-click not resolving to a valid table row at
            # all, rather than anything downstream in
            # open_quality_issue_record(). See application-error.log.
            from customer_error_handler import log_diagnostic_event

            log_diagnostic_event(
                "VisitCalendarDialog.activate_current_record",
                f"current_item() returned None -- table.currentRow()="
                f"{self.table.currentRow()}, len(self.rows)={len(self.rows)}",
            )
            return
        if self.on_record_activated is not None:
            self.on_record_activated(item.get("customer_id"))
        self.accept()


class ChangePasswordDialog(QDialog):
    # Layout: ui/dialogs/change_password_dialog.ui.
    ui_file = "dialogs/change_password_dialog.ui"
    ui_object_names = (
        "currentPasswordEdit",
        "newPasswordEdit",
        "confirmPasswordEdit",
        "saveButton",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.create_layout()

    def create_layout(self):
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.current_password_edit = find_child(content, "currentPasswordEdit", QLineEdit)
        self.new_password_edit = find_child(content, "newPasswordEdit", QLineEdit)
        self.confirm_password_edit = find_child(content, "confirmPasswordEdit", QLineEdit)

        find_child(content, "saveButton", QPushButton).clicked.connect(self.accept)

        self.confirm_password_edit.returnPressed.connect(self.accept)
        self.current_password_edit.setFocus()

    def values(self):
        return (
            self.current_password_edit.text(),
            self.new_password_edit.text(),
            self.confirm_password_edit.text(),
        )


class FontSizeDialog(QDialog):
    # Layout: ui/dialogs/font_size_dialog.ui.
    ui_file = "dialogs/font_size_dialog.ui"
    ui_object_names = ("fontSizeCombo", "applyButton")

    def __init__(self, current_key, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.current_key = current_key
        self.create_layout()

    def create_layout(self):
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.font_size_combo = find_child(content, "fontSizeCombo", FluentComboBox)
        current_index = 0
        for index, (key, label, _point_size) in enumerate(FONT_SIZE_OPTIONS):
            self.font_size_combo.addItem(label, userData=key)
            if key == self.current_key:
                current_index = index
        self.font_size_combo.setCurrentIndex(current_index)

        find_child(content, "applyButton", QPushButton).clicked.connect(self.accept)

    def selected_font_size_key(self):
        return self.font_size_combo.currentData() or DEFAULT_FONT_SIZE_KEY


class ColumnVisibilityDialog(QDialog):
    # Layout: ui/dialogs/column_visibility_dialog.ui; one check box per column
    # is added to columnVisibilityContent here.
    ui_file = "dialogs/column_visibility_dialog.ui"
    ui_object_names = (
        "columnVisibilityScrollArea",
        "columnVisibilityContent",
        "selectAllButton",
        "saveButton",
    )

    def __init__(self, columns, hidden_keys, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.checkboxes = {}
        content = install_ui(self, self.ui_file, self.ui_object_names)

        checkbox_layout = find_child(content, "columnVisibilityContent", QWidget).layout()
        for key, label in columns:
            checkbox = FluentCheckBox(label)
            checkbox.setChecked(key not in hidden_keys)
            self.checkboxes[key] = checkbox
            checkbox_layout.addWidget(checkbox)
        checkbox_layout.addStretch(1)
        self.scroll_area = find_child(content, "columnVisibilityScrollArea", QScrollArea)

        select_all_button = find_child(content, "selectAllButton", QPushButton)
        select_all_button.clicked.connect(self.select_all)
        save_button = find_child(content, "saveButton", QPushButton)
        save_button.clicked.connect(self.accept)
        chain_tab_order([*self.checkboxes.values(), select_all_button, save_button])

    def select_all(self):
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)

    def hidden_keys(self):
        return [key for key, checkbox in self.checkboxes.items() if not checkbox.isChecked()]


class AdvancedSearchDialog(QDialog):
    # Reserved criteria key for the exclude-keyword field -- deliberately
    # not a real ADVANCED_SEARCH_FIELDS entry (those are all per-field
    # "must contain" filters); this one field applies across every
    # searchable column and means the opposite ("must NOT contain").
    # CustomerRecordProcessor pops this key out of advanced_criteria before
    # its normal per-field matching loop -- see its docstring.
    EXCLUDE_KEYWORD_KEY = "_exclude_keyword"

    # Layout: ui/dialogs/advanced_search_dialog.ui; one row per
    # ADVANCED_SEARCH_FIELDS entry is added to advancedSearchContent here.
    ui_file = "dialogs/advanced_search_dialog.ui"
    ui_object_names = (
        "advancedSearchScrollArea",
        "advancedSearchContent",
        "excludeInput",
        "clearButton",
        "applyButton",
    )

    def __init__(self, criteria, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.inputs = {}
        content = install_ui(self, self.ui_file, self.ui_object_names)

        layout = find_child(content, "advancedSearchContent", QWidget).layout()
        for row_index, (key, label) in enumerate(ADVANCED_SEARCH_FIELDS):
            layout.addWidget(QLabel(label), row_index, 0)
            edit = FluentLineEdit()
            edit.setPlaceholderText("多個值可用「、」或「，」分隔")
            edit.setText(str(criteria.get(key, "") or ""))
            self.inputs[key] = edit
            layout.addWidget(edit, row_index, 1)

        self.input_order = list(self.inputs.values())
        for index, edit in enumerate(self.input_order):
            edit.returnPressed.connect(
                lambda current_index=index: self.focus_next_input(current_index)
            )
        self.scroll_area = find_child(content, "advancedSearchScrollArea", QScrollArea)

        self.exclude_input = find_child(content, "excludeInput", QLineEdit)
        self.exclude_input.setText(str(criteria.get(self.EXCLUDE_KEYWORD_KEY, "") or ""))
        self.inputs[self.EXCLUDE_KEYWORD_KEY] = self.exclude_input

        clear_button = find_child(content, "clearButton", QPushButton)
        clear_button.clicked.connect(self.clear_inputs)
        save_button = find_child(content, "applyButton", QPushButton)
        save_button.clicked.connect(self.accept)
        chain_tab_order([*self.input_order, self.exclude_input, clear_button, save_button])

    def focus_next_input(self, current_index):
        next_index = int(current_index) + 1
        if next_index < len(self.input_order):
            self.input_order[next_index].setFocus()
            self.scroll_area.ensureWidgetVisible(self.input_order[next_index])
            return
        self.accept()

    def clear_inputs(self):
        for edit in self.inputs.values():
            edit.clear()

    def criteria(self):
        return {
            key: edit.text().strip()
            for key, edit in self.inputs.items()
            if edit.text().strip()
        }


class ImportPreviewDialog(QDialog):
    # Layout: ui/dialogs/import_preview_dialog.ui.  The table's columns follow
    # the imported Excel columns; the 都市計畫 choice, when offered, takes the
    # place of planChoiceSlot.
    ui_file = "dialogs/import_preview_dialog.ui"
    ui_object_names = (
        "summaryLabel",
        "planChoiceSlot",
        "previewTable",
        "importAllButton",
        "skipDuplicatesButton",
        "updateDuplicatesButton",
        "cancelButton",
    )

    def __init__(
        self,
        records,
        column_map,
        duplicate_indexes,
        parent=None,
        *,
        plans=None,
        default_plan_id=0,
    ):
        super().__init__(parent)
        self.records = records
        self.column_map = column_map
        self.duplicate_indexes = set(duplicate_indexes)
        self.import_mode = "all"
        # `plans` is None unless the home server has 都市計畫; then the user
        # says which plan this batch belongs to.
        self.plan_choice = None

        self.setModal(True)
        content = install_ui(self, self.ui_file, self.ui_object_names)

        imported_labels = "、".join(label for _key, label in self.column_map)
        summary_lines = [
            f"共 {len(records)} 筆",
            f"對應欄位：{imported_labels}",
        ]
        matched = [record for record in records if record.get("_matched_by_record_id")]
        if matched:
            changed = sum(1 for record in matched if record.get("_has_changes"))
            warned = sum(1 for record in matched if record.get("_import_warnings"))
            unmatched = sum(1 for record in records if record.get("_unmatched_record_id"))
            summary_lines.append(
                f"依系統ID對到原資料 {len(matched)} 筆：將更新 {changed} 筆、"
                f"無變更 {len(matched) - changed} 筆"
                + (f"、有警告 {warned} 筆" if warned else "")
            )
            if unmatched:
                summary_lines.append(f"系統ID不存在或重複 {unmatched} 筆：不會匯入")
            summary_lines.append(
                "有系統ID的資料一律更新原本那一筆，不會重複新增；空白欄位保留原值。"
                "請先看「變更內容」欄確認。"
            )
        elif self.duplicate_indexes:
            summary_lines.append(f"偵測到 {len(self.duplicate_indexes)} 筆可能重複資料")
        else:
            summary_lines.append("未偵測到重複資料")
        find_child(content, "summaryLabel", QLabel).setText("\n".join(summary_lines))
        plan_slot = find_child(content, "planChoiceSlot", QWidget)
        if plans is not None:
            self.plan_choice = put_in_slot(
                plan_slot, ImportPlanChoice(plans, default_plan_id, self)
            )
            # Built after the .ui table, but it still gets the first focus.
            self.plan_choice.combo.setFocus()
        else:
            plan_slot.hide()

        self.table = find_child(content, "previewTable", QTableWidget)
        headers = ["狀態", *[label for _key, label in self.column_map]]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        for index in range(len(headers)):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeToContents)

        self.load_preview_rows()

        find_child(content, "importAllButton", QPushButton).clicked.connect(self.import_all)
        skip_button = find_child(content, "skipDuplicatesButton", QPushButton)
        update_button = find_child(content, "updateDuplicatesButton", QPushButton)
        if self.duplicate_indexes:
            skip_button.clicked.connect(self.import_skip_duplicates)
            update_button.clicked.connect(self.import_update_duplicates)
        else:
            skip_button.hide()
            update_button.hide()
        find_child(content, "cancelButton", QPushButton).clicked.connect(self.reject)

    def load_preview_rows(self):
        # Every row, not the first 200: a corrected export of ~1000 records
        # is reviewed here row by row before anything is written.
        preview_records = self.records
        self.table.setRowCount(len(preview_records))
        field_keys = [key for key, _label in self.column_map]
        for row_index, record in enumerate(preview_records):
            is_duplicate = row_index in self.duplicate_indexes
            status_text = record.get("_duplicate_reason") or "將匯入"
            is_flagged = status_text != "將匯入"
            if record.get("_matched_by_record_id"):
                status_text = "系統ID相符：" + (
                    "將更新" if record.get("_has_changes") else "無變更"
                )
                is_flagged = bool(record.get("_import_warnings"))
            status_item = QTableWidgetItem(status_text)
            if is_flagged:
                status_item.setBackground(qcolor("overdue"))
                status_item.setForeground(ROW_TEXT_COLOR)
            self.table.setItem(row_index, 0, status_item)
            for column_offset, field_key in enumerate(field_keys, start=1):
                item = QTableWidgetItem(str(record.get(field_key) or ""))
                if is_flagged:
                    item.setBackground(qcolor("overdue"))
                    item.setForeground(ROW_TEXT_COLOR)
                self.table.setItem(row_index, column_offset, item)

    def plan_id(self):
        """The chosen 都市計畫 id, 0 for none (or when plans are not offered)."""

        return 0 if self.plan_choice is None else self.plan_choice.plan_id()

    def import_all(self):
        self.import_mode = "all"
        self.accept()

    def import_skip_duplicates(self):
        self.import_mode = "skip_duplicates"
        self.accept()

    def import_update_duplicates(self):
        self.import_mode = "update_duplicates"
        self.accept()


class ImportResultDialog(QDialog):
    # Layout: ui/dialogs/import_result_dialog.ui; the 都市計畫 section, when
    # there is one, takes the place of planSectionSlot.
    ui_file = "dialogs/import_result_dialog.ui"
    ui_object_names = (
        "summaryLabel",
        "planSectionSlot",
        "detailsEdit",
        "exportErrorsButton",
        "closeButton",
    )
    PLAN_DIALOG_SIZE = (640, 640)

    def __init__(
        self,
        summary_lines,
        detail_lines=None,
        error_rows=None,
        parent=None,
        *,
        plan_summary=None,
    ):
        super().__init__(parent)
        self.setModal(True)
        self.error_rows = error_rows or []
        self.plan_section = None
        content = install_ui(self, self.ui_file, self.ui_object_names)

        find_child(content, "summaryLabel", QLabel).setText("\n".join(summary_lines))
        plan_slot = find_child(content, "planSectionSlot", QWidget)
        if plan_summary:
            self.plan_section = put_in_slot(
                plan_slot, ImportPlanResultSection(plan_summary, self)
            )
            self.resize(*self.PLAN_DIALOG_SIZE)
        else:
            plan_slot.hide()

        find_child(content, "detailsEdit", QPlainTextEdit).setPlainText(
            "\n".join(detail_lines or ["本次沒有其他明細。"])
        )

        export_button = find_child(content, "exportErrorsButton", QPushButton)
        if self.error_rows:
            export_button.clicked.connect(self.export_error_rows)
        else:
            export_button.hide()
        find_child(content, "closeButton", QPushButton).clicked.connect(self.accept)

    def export_error_rows(self):
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "匯出錯誤列",
            str(APP_DIR / f"import-errors-{datetime.now().strftime('%Y%m%d-%H%M%S')}.xlsx"),
            "Excel 檔案 (*.xlsx)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"
        try:
            write_error_rows(file_path, self.error_rows, LAND_FIELDS)
        except Exception as exc:
            QMessageBox.critical(self, "無法匯出", str(exc))
            return
        QMessageBox.information(self, "匯出完成", f"已匯出 {len(self.error_rows)} 筆錯誤列。\n檔案位置：{file_path}")


class BatchEditDialog(QDialog):
    # Layout: ui/dialogs/batch_edit_dialog.ui.
    ui_file = "dialogs/batch_edit_dialog.ui"
    ui_object_names = (
        "checkedCountLabel",
        "fieldCombo",
        "valueEdit",
        "clearValueButton",
        "applyButton",
    )

    def __init__(self, checked_count, parent=None):
        super().__init__(parent)
        self.setModal(True)
        content = install_ui(self, self.ui_file, self.ui_object_names)

        self.field_combo = find_child(content, "fieldCombo", FluentComboBox)
        for key, label in BATCH_EDITABLE_FIELDS:
            self.field_combo.addItem(label, userData=key)
        self.value_edit = find_child(content, "valueEdit", QPlainTextEdit)

        find_child(content, "checkedCountLabel", QLabel).setText(
            f"已勾選 {checked_count} 筆資料"
        )
        find_child(content, "clearValueButton", QPushButton).clicked.connect(
            self.value_edit.clear
        )
        find_child(content, "applyButton", QPushButton).clicked.connect(self.accept)

    def values(self):
        return (
            self.field_combo.currentData(),
            self.value_edit.toPlainText().strip(),
        )


class BatchEditPreviewDialog(QDialog):
    # Layout: ui/dialogs/batch_edit_preview_dialog.ui.
    ui_file = "dialogs/batch_edit_preview_dialog.ui"
    ui_object_names = ("summaryLabel", "detailsEdit", "cancelButton", "applyButton")

    def __init__(self, field_label, new_value, preview_lines, parent=None):
        super().__init__(parent)
        self.setModal(True)
        content = install_ui(self, self.ui_file, self.ui_object_names)

        find_child(content, "summaryLabel", QLabel).setText(
            f"欄位：{field_label}\n"
            f"新內容：{new_value or '(清空)'}\n"
            f"預覽筆數：{len(preview_lines)}"
        )
        find_child(content, "detailsEdit", QPlainTextEdit).setPlainText(
            "\n".join(preview_lines)
        )
        find_child(content, "cancelButton", QPushButton).clicked.connect(self.reject)
        find_child(content, "applyButton", QPushButton).clicked.connect(self.accept)


class SharedLandBatchDialog(QDialog):
    REQUIRED_SHARED_FIELDS = ("district", "section", "land_number")

    # Layout: ui/dialogs/shared_land_batch_dialog.ui (the 共用欄位 and 快速新增
    # boxes included); the status line's colour follows the parse result here.
    ui_file = "dialogs/shared_land_batch_dialog.ui"
    SHARED_FIELD_KEYS = ("district", "section", "subsection", "land_number", "area", "declared_value")
    QUICK_FIELD_KEYS = (
        "owner_name",
        "external_id",
        "address",
        "numerator",
        "denominator",
        "registration_reason",
    )
    ui_object_names = (
        *(f"sharedEdit_{key}" for key in SHARED_FIELD_KEYS),
        *(f"quickEdit_{key}" for key in QUICK_FIELD_KEYS),
        "quickAddButton",
        "pasteButton",
        "rowsEdit",
        "rowStatusLabel",
        "cancelButton",
        "previewButton",
    )

    def __init__(
        self,
        initial_values=None,
        parent=None,
        *,
        district_options=None,
        section_options=None,
        subsection_options=None,
    ):
        super().__init__(parent)
        initial_values = initial_values or {}
        self.setModal(True)
        content = install_ui(self, self.ui_file, self.ui_object_names)

        self.shared_inputs = {}
        completer_options = {
            "district": district_options,
            "section": section_options,
            "subsection": subsection_options,
        }
        for key in self.SHARED_FIELD_KEYS:
            edit = find_child(content, f"sharedEdit_{key}", QLineEdit)
            edit.setText(str(initial_values.get(key) or ""))
            options = completer_options.get(key)
            if options:
                completer = QCompleter(sorted(set(options)), edit)
                completer.setCaseSensitivity(Qt.CaseInsensitive)
                completer.setFilterMode(Qt.MatchContains)
                edit.setCompleter(completer)
            self.shared_inputs[key] = edit

        self.quick_inputs = {
            key: find_child(content, f"quickEdit_{key}", QLineEdit) for key in self.QUICK_FIELD_KEYS
        }
        find_child(content, "quickAddButton", QPushButton).clicked.connect(self.add_quick_row)
        find_child(content, "pasteButton", QPushButton).clicked.connect(self.paste_from_clipboard)

        self.rows_edit = find_child(content, "rowsEdit", QPlainTextEdit)
        self.rows_edit.textChanged.connect(self.update_row_status)
        self.row_status_label = find_child(content, "rowStatusLabel", QLabel)

        find_child(content, "cancelButton", QPushButton).clicked.connect(self.reject)
        find_child(content, "previewButton", QPushButton).clicked.connect(self.accept)

    def add_quick_row(self):
        name = self.quick_inputs["owner_name"].text().strip()
        if not name:
            self.quick_inputs["owner_name"].setFocus()
            return
        line = "\t".join(
            self.quick_inputs[key].text().strip()
            for key in (
                "owner_name",
                "external_id",
                "address",
                "numerator",
                "denominator",
                "registration_reason",
            )
        )
        existing = self.rows_edit.toPlainText()
        self.rows_edit.setPlainText(f"{existing}\n{line}" if existing.strip() else line)
        self.rows_edit.moveCursor(QTextCursor.End)
        for edit in self.quick_inputs.values():
            edit.clear()
        self.quick_inputs["owner_name"].setFocus()

    def paste_from_clipboard(self):
        text = QApplication.clipboard().text()
        if text:
            self.rows_edit.setPlainText(text)
            self.rows_edit.moveCursor(QTextCursor.End)

    def update_row_status(self):
        text = self.rows_edit.toPlainText()
        if not text.strip():
            self.row_status_label.setText("尚未輸入任何資料。")
            self.row_status_label.setStyleSheet("")
            return
        parsed_rows, errors = parse_shared_land_rows(text)
        if errors:
            extra = f"（另有 {len(errors) - 1} 項錯誤）" if len(errors) > 1 else ""
            self.row_status_label.setText(
                f"⚠ 已辨識 {len(parsed_rows)} 筆，{errors[0]}{extra}"
            )
            self.row_status_label.setStyleSheet(f"color: {token('amber_ink')};")
        else:
            self.row_status_label.setText(f"✓ 已辨識 {len(parsed_rows)} 筆，格式正確。")
            self.row_status_label.setStyleSheet(f"color: {token('success_ink')};")

    def values(self):
        return (
            {key: edit.text().strip() for key, edit in self.shared_inputs.items()},
            self.rows_edit.toPlainText(),
        )


class SavedSearchDialog(QDialog):
    # Layout: ui/dialogs/saved_search_dialog.ui.
    ui_file = "dialogs/saved_search_dialog.ui"
    ui_object_names = ("searchesTable", "loadButton", "deleteButton", "closeButton")

    def __init__(self, saved_searches, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.saved_searches = list(saved_searches)
        self.selected_criteria = None
        content = install_ui(self, self.ui_file, self.ui_object_names)

        self.table = find_child(content, "searchesTable", QTableWidget)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        find_child(content, "loadButton", QPushButton).clicked.connect(self.load_selected)
        find_child(content, "deleteButton", QPushButton).clicked.connect(self.delete_selected)
        find_child(content, "closeButton", QPushButton).clicked.connect(self.reject)

        self.reload_rows()

    def describe_criteria(self, criteria):
        parts = []
        keyword = str(criteria.get("keyword") or "").strip()
        if keyword:
            parts.append(f"關鍵字:{keyword}")
        advanced = criteria.get("advanced") if isinstance(criteria.get("advanced"), dict) else {}
        if advanced:
            parts.append(f"進階:{len(advanced)} 項")
        filter_field = criteria.get("filter_field")
        if filter_field and filter_field != "all":
            parts.append("指定欄位")
        sort_field = criteria.get("sort_field")
        if sort_field:
            parts.append("排序")
        return " / ".join(parts) if parts else "無條件"

    def reload_rows(self):
        self.table.setRowCount(0)
        for item in self.saved_searches:
            row_number = self.table.rowCount()
            self.table.insertRow(row_number)
            self.table.setItem(row_number, 0, QTableWidgetItem(item["name"]))
            self.table.setItem(row_number, 1, QTableWidgetItem(self.describe_criteria(item["criteria"])))

    def selected_index(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        return selected_rows[0].row()

    def load_selected(self):
        index = self.selected_index()
        if index is None:
            return
        self.selected_criteria = self.saved_searches[index]["criteria"]
        self.accept()

    def delete_selected(self):
        index = self.selected_index()
        if index is None:
            return
        del self.saved_searches[index]
        self.reload_rows()


class OperationLogDialog(QDialog):
    # Layout: ui/dialogs/operation_log_dialog.ui.
    ui_file = "dialogs/operation_log_dialog.ui"
    ui_object_names = ("logsTable", "closeButton")

    def __init__(self, parent=None, rows=None):
        super().__init__(parent)
        self.rows = rows
        self.setModal(True)
        content = install_ui(self, self.ui_file, self.ui_object_names)

        self.table = find_child(content, "logsTable", QTableWidget)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        find_child(content, "closeButton", QPushButton).clicked.connect(self.accept)

        self.load_logs()

    def load_logs(self):
        rows = self.rows if self.rows is not None else get_operation_logs()
        self.table.setRowCount(0)
        for row in rows:
            row_number = self.table.rowCount()
            self.table.insertRow(row_number)
            self.table.setItem(row_number, 0, QTableWidgetItem(row["created_at"]))
            self.table.setItem(row_number, 1, QTableWidgetItem(row["action_type"]))
            self.table.setItem(row_number, 2, QTableWidgetItem(row["summary"]))
            self.table.setItem(row_number, 3, QTableWidgetItem(row["detail"] or ""))


class WatchlistDialog(QDialog):
    # Layout: ui/dialogs/watchlist_dialog.ui.
    ui_file = "dialogs/watchlist_dialog.ui"
    ui_object_names = ("watchlistTable", "addButton", "deleteButton", "saveButton")

    def __init__(self, parent=None, repository=None):
        super().__init__(parent)
        self.repository = repository
        self.setModal(True)

        self.create_layout()
        self.load_entries()

    def create_layout(self):
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.table = find_child(content, "watchlistTable", QTableWidget)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        find_child(content, "addButton", QPushButton).clicked.connect(self.add_row)
        find_child(content, "deleteButton", QPushButton).clicked.connect(self.delete_selected_row)
        find_child(content, "saveButton", QPushButton).clicked.connect(self.save_entries)

    def load_entries(self):
        rows = (
            self.repository.get_watchlist_entries()
            if self.repository is not None
            else get_watchlist_entries()
        )
        self.table.setRowCount(0)
        for row in rows:
            self.add_row(row["name"], row["note"] or "")

    def add_row(self, name="", note=""):
        row_number = self.table.rowCount()
        self.table.insertRow(row_number)
        self.table.setItem(row_number, 0, QTableWidgetItem(name))
        self.table.setItem(row_number, 1, QTableWidgetItem(note))
        self.table.setCurrentCell(row_number, 0)

    def delete_selected_row(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        self.table.removeRow(selected_rows[0].row())

    def collect_entries(self):
        entries = []
        for row_number in range(self.table.rowCount()):
            name_item = self.table.item(row_number, 0)
            note_item = self.table.item(row_number, 1)
            name = name_item.text().strip() if name_item is not None else ""
            note = note_item.text().strip() if note_item is not None else ""
            if name:
                entries.append({"name": name, "note": note})
        return entries

    def save_entries(self):
        entries = self.collect_entries()
        if self.repository is not None:
            self.repository.replace_watchlist_entries(entries)
        else:
            replace_watchlist_entries(entries)
        self.accept()
