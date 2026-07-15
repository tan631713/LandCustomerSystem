"""Reusable PySide6 dialogs with application dependencies injected at startup."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from customer_responsive_dialog import ResponsiveDialog as QDialog

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
ROW_TEXT_COLOR = QColor("#f8fafc")
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
        <p>適合一次新增同地區、同地段、同地號的多位所有權人。</p>
        <h3>上方共同欄位</h3>
        <ul>
          <li>地區、地段、地號、面積、公告現值可一起填入。</li>
          <li>序號/登記次序可以手動輸入在每一列。</li>
        </ul>
        <h3>每列資料順序</h3>
        <p><code>登記次序、姓名、身分證、地址、分子、分母、備註、出訪記錄</code></p>
        <p>可用頓號 <code>、</code> 或逗號 <code>，</code> 分隔，也可從 Excel 複製貼上。</p>
        <h3>範例</h3>
        <p><code>15、王弘益、H100059743、桃園市桃園區大華九街34號、108、3360</code></p>
        <p><b>身分證可以空白：</b></p>
        <p><code>16、王小明、、桃園市桃園區中正路1號、1、2</code></p>
        <p>如果只有前 6 欄，備註與出訪記錄會自動留空。</p>
        """,
    ),
    (
        "Excel 匯入匯出",
        """
        <h2>Excel 匯入匯出</h2>
        <ul>
          <li>可從「資料 → 匯入 .xlsx」匯入土地資料。</li>
          <li>匯入前會先預覽資料，並標示可能重複或格式異常的列。</li>
          <li>可從「資料 → 匯出 Excel」匯出目前資料。</li>
          <li>可從「資料 → 匯出勾選資料」只匯出勾選或目前選取的資料。</li>
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
          <li><b>地圖：</b>保存座標、搜尋 OpenStreetMap，並產生離線土地分布網頁。</li>
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("使用說明")
        self.setModal(True)
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        intro = QLabel("土地資料系統快速上手")
        intro.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(intro)

        self.tabs = QTabWidget()
        for title, html in HELP_SECTIONS:
            browser = QTextBrowser()
            browser.setOpenExternalLinks(False)
            browser.setHtml(html)
            self.tabs.addTab(browser, title)
        layout.addWidget(self.tabs, 1)

        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)


class DataQualityRulesDialog(QDialog):
    def __init__(self, selected_rules=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("選擇資料品質檢查項目")
        self.setModal(True)
        self.setFixedSize(500, 430)
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("請勾選這次要檢查的資料品質規則：")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(title)

        preset_row = QGridLayout()
        preset_row.setHorizontalSpacing(8)
        preset_row.addWidget(QLabel("快速模式"), 0, 0)
        self.preset_combo = QComboBox()
        for preset_key, label, _rule_keys, _description in QUALITY_RULE_PRESETS:
            self.preset_combo.addItem(label, preset_key)
        self.preset_combo.addItem("自訂", "custom")
        self.preset_combo.currentIndexChanged.connect(self.apply_selected_preset)
        preset_row.addWidget(self.preset_combo, 0, 1)
        layout.addLayout(preset_row)

        self.preset_hint_label = QLabel("")
        self.preset_hint_label.setWordWrap(True)
        layout.addWidget(self.preset_hint_label)

        for rule_key, label in QUALITY_RULE_OPTIONS:
            checkbox = QCheckBox(label)
            checkbox.setChecked(rule_key in selected)
            checkbox.stateChanged.connect(self.update_preset_selection)
            self.rule_checkboxes[rule_key] = checkbox
            layout.addWidget(checkbox)

        quick_row = QHBoxLayout()
        select_all_button = QPushButton("全選")
        select_all_button.clicked.connect(self.select_all)
        clear_button = QPushButton("全不選")
        clear_button.clicked.connect(self.clear_all)
        quick_row.addWidget(select_all_button)
        quick_row.addWidget(clear_button)
        quick_row.addStretch(1)
        layout.addLayout(quick_row)

        hint = QLabel("選擇會保存；下次執行資料品質檢查時會沿用。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        start_button = QPushButton("開始檢查")
        start_button.clicked.connect(self.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(start_button)
        layout.addLayout(button_row)
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
        self.setWindowTitle("資料品質檢查")
        self.setModal(True)
        self.resize(900, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

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
        self.summary_label = QLabel(title_text)
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(self.summary_label)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("顯示"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("全部問題", "all")
        self.filter_combo.addItem("重要", "severity:重要")
        self.filter_combo.addItem("提醒", "severity:提醒")
        self.filter_combo.addItem("疑似重複", "category:疑似重複")
        self.filter_combo.addItem("格式異常", "format")
        self.filter_combo.addItem("姓名空白", "category:姓名空白")
        self.filter_combo.addItem("地號缺漏", "category:地號缺漏")
        self.filter_combo.addItem("分母為 0", "category:分母為 0")
        self.filter_combo.currentIndexChanged.connect(self.apply_filter)
        self.filter_combo.setEnabled(bool(self.issues))
        filter_row.addWidget(self.filter_combo)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.category_summary_table = QTableWidget(0, 4)
        self.category_summary_table.setHorizontalHeaderLabels(["類型", "重要", "提醒", "合計"])
        self.category_summary_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.category_summary_table.setSelectionMode(QTableWidget.SingleSelection)
        self.category_summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.category_summary_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.category_summary_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.category_summary_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.category_summary_table.verticalHeader().setVisible(False)
        self.category_summary_table.setMaximumHeight(140)
        self.category_summary_table.itemClicked.connect(self.filter_by_summary_item)
        self.load_category_summary()
        layout.addWidget(self.category_summary_table)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["資料ID", "程度", "類型", "問題", "建議處理"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setWordWrap(True)
        self.table.itemDoubleClicked.connect(self.activate_current_issue)
        self.load_issues()
        layout.addWidget(self.table, 1)

        hint = QLabel("提示：雙擊問題列，或選取後按「前往選取資料」，可直接載入該筆資料進行修正。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.goto_button = QPushButton("前往選取資料")
        self.goto_button.clicked.connect(self.activate_current_issue)
        self.goto_button.setEnabled(bool(self.filtered_issues))
        self.ignore_button = QPushButton("確認忽略此問題")
        self.ignore_button.clicked.connect(self.ignore_current_issue)
        self.ignore_button.setEnabled(bool(self.filtered_issues))
        self.ignore_filtered_button = QPushButton("確認目前篩選")
        self.ignore_filtered_button.clicked.connect(self.ignore_filtered_issues)
        self.ignore_filtered_button.setEnabled(bool(self.filtered_issues))
        self.ignore_same_category_button = QPushButton("確認同類型")
        self.ignore_same_category_button.clicked.connect(self.ignore_same_category_issues)
        self.ignore_same_category_button.setEnabled(bool(self.filtered_issues))
        self.clear_ignored_button = QPushButton("清除已忽略")
        self.clear_ignored_button.clicked.connect(self.clear_ignored_issues)
        self.clear_ignored_button.setEnabled(self.ignored_count > 0)
        self.copy_summary_button = QPushButton("複製摘要")
        self.copy_summary_button.clicked.connect(self.copy_summary)
        self.copy_summary_button.setEnabled(bool(self.issues) or self.ignored_count > 0)
        self.export_summary_button = QPushButton("匯出摘要 Excel")
        self.export_summary_button.clicked.connect(self.export_summary)
        self.export_summary_button.setEnabled(bool(self.issues) or self.ignored_count > 0)
        self.copy_button = QPushButton("複製目前清單")
        self.copy_button.clicked.connect(self.copy_current_issues)
        self.copy_button.setEnabled(bool(self.filtered_issues))
        self.export_button = QPushButton("匯出目前清單 Excel")
        self.export_button.clicked.connect(self.export_issues)
        self.export_button.setEnabled(bool(self.filtered_issues))
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.accept)
        button_row = QHBoxLayout()
        button_row.addWidget(self.copy_summary_button)
        button_row.addWidget(self.export_summary_button)
        button_row.addWidget(self.copy_button)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.clear_ignored_button)
        button_row.addStretch(1)
        button_row.addWidget(self.ignore_filtered_button)
        button_row.addWidget(self.ignore_same_category_button)
        button_row.addWidget(self.ignore_button)
        button_row.addWidget(self.goto_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)
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
                    item.setBackground(QColor("#5b2230"))
                    item.setForeground(ROW_TEXT_COLOR)
                self.category_summary_table.setItem(row_number, column_number, item)
        self.category_summary_table.resizeRowsToContents()

    def select_category_filter(self, category):
        filter_value = f"category:{category}"
        index = self.filter_combo.findData(filter_value)
        if index < 0:
            self.filter_combo.addItem(category, filter_value)
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
                    item.setBackground(QColor("#5b2230"))
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
    def __init__(self, stats, parent=None):
        super().__init__(parent)
        self.stats = stats
        self.setWindowTitle("資料統計儀表板")
        self.setModal(True)
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        summary = QLabel(
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
        summary.setWordWrap(True)
        summary.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(summary)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["分類", "項目", "筆數", "補充"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.load_rows()

        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

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
    def __init__(self, logs, record_label="", parent=None):
        super().__init__(parent)
        self.logs = list(logs)
        self.setWindowTitle("單筆修改歷史")
        self.setModal(True)
        self.resize(860, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(record_label or "目前選取資料的修改歷史")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(title)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["時間", "動作", "欄位", "修改前", "修改後", "資料ID"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.load_rows()

        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

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

    def __init__(self, record_label="", reminder=None, parent=None):
        super().__init__(parent)
        self.reminder = reminder
        self.delete_requested = False
        self.setWindowTitle("追蹤提醒")
        self.setModal(True)
        self.resize(460, 320)

        self.due_date_edit = QLineEdit()
        self.due_date_edit.setPlaceholderText("YYYY-MM-DD，例如 2026-07-20")
        self.due_date_edit.setText(str((reminder or {}).get("due_date") or ""))
        self.status_combo = QComboBox()
        current_status = str((reminder or {}).get("status") or "未處理")
        for status in self.STATUS_OPTIONS:
            self.status_combo.addItem(status, status)
        status_index = self.status_combo.findData(current_status)
        self.status_combo.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setPlainText(str((reminder or {}).get("note") or ""))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(record_label or "設定目前選取資料的追蹤提醒")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(title)

        form = QGridLayout()
        form.addWidget(QLabel("下次追蹤日"), 0, 0)
        form.addWidget(self.due_date_edit, 0, 1)
        form.addWidget(QLabel("處理狀態"), 1, 0)
        form.addWidget(self.status_combo, 1, 1)
        form.addWidget(QLabel("備註"), 2, 0)
        form.addWidget(self.note_edit, 2, 1)
        layout.addLayout(form, 1)

        button_row = QHBoxLayout()
        clear_button = QPushButton("清除提醒")
        clear_button.clicked.connect(self.request_delete)
        clear_button.setEnabled(reminder is not None)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("儲存")
        save_button.clicked.connect(self.accept)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

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
    def __init__(self, reminders, parent=None, on_record_activated=None):
        super().__init__(parent)
        self.reminders = list(reminders)
        self.on_record_activated = on_record_activated
        self.setWindowTitle("追蹤提醒清單")
        self.setModal(True)
        self.resize(860, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(f"共有 {len(self.reminders)} 筆追蹤提醒；雙擊資料列可載入該筆資料。")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(title)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["追蹤日", "狀態", "姓名", "地區", "地段", "地號", "備註"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.activate_current_record)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        self.load_rows()

        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def load_rows(self):
        self.table.setRowCount(len(self.reminders))
        for row_number, reminder in enumerate(self.reminders):
            values = [
                reminder.get("due_date", ""),
                reminder.get("status", ""),
                reminder.get("owner_name", ""),
                reminder.get("district", ""),
                reminder.get("section", ""),
                reminder.get("land_number", ""),
                reminder.get("note", ""),
            ]
            for column_number, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if reminder.get("is_overdue") and reminder.get("status") != "完成":
                    item.setBackground(QColor("#5b2230"))
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


class ChangePasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("修改密碼")
        self.setModal(True)
        self.setFixedSize(380, 220)

        self.current_password_edit = QLineEdit()
        self.current_password_edit.setEchoMode(QLineEdit.Password)
        self.new_password_edit = QLineEdit()
        self.new_password_edit.setEchoMode(QLineEdit.Password)
        self.confirm_password_edit = QLineEdit()
        self.confirm_password_edit.setEchoMode(QLineEdit.Password)

        self.create_layout()

    def create_layout(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        layout.addWidget(QLabel("目前密碼"), 0, 0)
        layout.addWidget(self.current_password_edit, 0, 1)

        layout.addWidget(QLabel("新密碼"), 1, 0)
        layout.addWidget(self.new_password_edit, 1, 1)

        layout.addWidget(QLabel("確認新密碼"), 2, 0)
        layout.addWidget(self.confirm_password_edit, 2, 1)

        save_button = QPushButton("更新密碼")
        save_button.clicked.connect(self.accept)
        layout.addWidget(save_button, 3, 1, alignment=Qt.AlignRight)

        self.confirm_password_edit.returnPressed.connect(self.accept)
        self.current_password_edit.setFocus()

    def values(self):
        return (
            self.current_password_edit.text(),
            self.new_password_edit.text(),
            self.confirm_password_edit.text(),
        )


class FontSizeDialog(QDialog):
    def __init__(self, current_key, parent=None):
        super().__init__(parent)
        self.setWindowTitle("字體大小")
        self.setModal(True)
        self.setFixedSize(320, 150)

        self.font_size_combo = QComboBox()
        current_index = 0
        for index, (key, label, _point_size) in enumerate(FONT_SIZE_OPTIONS):
            self.font_size_combo.addItem(label, key)
            if key == current_key:
                current_index = index
        self.font_size_combo.setCurrentIndex(current_index)

        self.create_layout()

    def create_layout(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        layout.addWidget(QLabel("字體大小"), 0, 0)
        layout.addWidget(self.font_size_combo, 0, 1)

        save_button = QPushButton("套用")
        save_button.clicked.connect(self.accept)
        layout.addWidget(save_button, 1, 1, alignment=Qt.AlignRight)

    def selected_font_size_key(self):
        return self.font_size_combo.currentData() or DEFAULT_FONT_SIZE_KEY


class ColumnVisibilityDialog(QDialog):
    def __init__(self, columns, hidden_keys, parent=None):
        super().__init__(parent)
        self.setWindowTitle("欄位顯示")
        self.setModal(True)
        self.resize(340, 420)
        self.checkboxes = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        scroll_content = QWidget()
        checkbox_layout = QVBoxLayout(scroll_content)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setSpacing(8)

        for key, label in columns:
            checkbox = QCheckBox(label)
            checkbox.setChecked(key not in hidden_keys)
            self.checkboxes[key] = checkbox
            checkbox_layout.addWidget(checkbox)

        checkbox_layout.addStretch(1)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("columnVisibilityScrollArea")
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(scroll_content)
        layout.addWidget(self.scroll_area, 1)

        button_row = QHBoxLayout()
        select_all_button = QPushButton("全部顯示")
        select_all_button.clicked.connect(self.select_all)
        button_row.addWidget(select_all_button)

        save_button = QPushButton("儲存")
        save_button.clicked.connect(self.accept)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def select_all(self):
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)

    def hidden_keys(self):
        return [key for key, checkbox in self.checkboxes.items() if not checkbox.isChecked()]


class AdvancedSearchDialog(QDialog):
    def __init__(self, criteria, parent=None):
        super().__init__(parent)
        self.setWindowTitle("進階搜尋")
        self.setModal(True)
        self.resize(420, 460)
        self.inputs = {}

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(18, 18, 18, 18)
        outer_layout.setSpacing(8)

        hint = QLabel(
            "同一欄可用「、」或「，」分隔多個值（任一符合）；"
            "不同欄位之間必須全部符合。按 Enter 可移到下一欄。"
        )
        hint.setWordWrap(True)
        outer_layout.addWidget(hint)

        scroll_content = QWidget()
        layout = QGridLayout(scroll_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        for row_index, (key, label) in enumerate(ADVANCED_SEARCH_FIELDS):
            layout.addWidget(QLabel(label), row_index, 0)
            edit = QLineEdit()
            edit.setPlaceholderText("多個值可用「、」或「，」分隔")
            edit.setText(str(criteria.get(key, "") or ""))
            self.inputs[key] = edit
            layout.addWidget(edit, row_index, 1)

        self.input_order = list(self.inputs.values())
        for index, edit in enumerate(self.input_order):
            edit.returnPressed.connect(
                lambda current_index=index: self.focus_next_input(current_index)
            )

        layout.setColumnStretch(1, 1)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("advancedSearchScrollArea")
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(scroll_content)
        outer_layout.addWidget(self.scroll_area, 1)

        button_row = QHBoxLayout()
        clear_button = QPushButton("清除條件")
        clear_button.setAutoDefault(False)
        clear_button.clicked.connect(self.clear_inputs)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)

        save_button = QPushButton("套用")
        save_button.setAutoDefault(False)
        save_button.clicked.connect(self.accept)
        button_row.addWidget(save_button)
        outer_layout.addLayout(button_row)

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
    def __init__(self, records, column_map, duplicate_indexes, parent=None):
        super().__init__(parent)
        self.records = records
        self.column_map = column_map
        self.duplicate_indexes = set(duplicate_indexes)
        self.import_mode = "all"

        self.setWindowTitle("匯入預覽")
        self.setModal(True)
        self.resize(1180, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        imported_labels = "、".join(label for _key, label in self.column_map)
        summary_lines = [
            f"共 {len(records)} 筆",
            f"對應欄位：{imported_labels}",
        ]
        if self.duplicate_indexes:
            summary_lines.append(f"偵測到 {len(self.duplicate_indexes)} 筆可能重複資料")
        else:
            summary_lines.append("未偵測到重複資料")
        layout.addWidget(QLabel("\n".join(summary_lines)))

        self.table = QTableWidget(0, len(self.column_map) + 1)
        headers = ["狀態", *[label for _key, label in self.column_map]]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for index in range(1, len(headers)):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.load_preview_rows()

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        import_all_button = QPushButton("全部匯入")
        import_all_button.clicked.connect(self.import_all)
        button_row.addWidget(import_all_button)

        if self.duplicate_indexes:
            skip_button = QPushButton("略過重複後匯入")
            skip_button.clicked.connect(self.import_skip_duplicates)
            button_row.addWidget(skip_button)
            update_button = QPushButton("更新既有並匯入")
            update_button.clicked.connect(self.import_update_duplicates)
            button_row.addWidget(update_button)

        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

    def load_preview_rows(self):
        preview_records = self.records[:200]
        self.table.setRowCount(len(preview_records))
        field_keys = [key for key, _label in self.column_map]
        for row_index, record in enumerate(preview_records):
            is_duplicate = row_index in self.duplicate_indexes
            status_text = record.get("_duplicate_reason") or "將匯入"
            is_flagged = status_text != "將匯入"
            status_item = QTableWidgetItem(status_text)
            if is_flagged:
                status_item.setBackground(QColor("#fde68a"))
                status_item.setForeground(ROW_TEXT_COLOR)
            self.table.setItem(row_index, 0, status_item)
            for column_offset, field_key in enumerate(field_keys, start=1):
                item = QTableWidgetItem(str(record.get(field_key) or ""))
                if is_flagged:
                    item.setBackground(QColor("#fef3c7"))
                    item.setForeground(ROW_TEXT_COLOR)
                self.table.setItem(row_index, column_offset, item)

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
    def __init__(self, summary_lines, detail_lines=None, error_rows=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("匯入結果報表")
        self.setModal(True)
        self.resize(520, 460)
        self.error_rows = error_rows or []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        summary = QLabel("\n".join(summary_lines))
        summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(summary)

        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText("\n".join(detail_lines or ["本次沒有其他明細。"]))
        layout.addWidget(details, 1)

        button_row = QHBoxLayout()
        if self.error_rows:
            export_button = QPushButton("匯出錯誤列")
            export_button.clicked.connect(self.export_error_rows)
            button_row.addWidget(export_button)
        button_row.addStretch(1)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

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
    def __init__(self, checked_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批次修改")
        self.setModal(True)
        self.resize(420, 260)

        self.field_combo = QComboBox()
        for key, label in BATCH_EDITABLE_FIELDS:
            self.field_combo.addItem(label, key)
        self.value_edit = QPlainTextEdit()
        self.value_edit.setFixedHeight(100)

        layout = QGridLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        layout.addWidget(QLabel(f"已勾選 {checked_count} 筆資料"), 0, 0, 1, 2)
        layout.addWidget(QLabel("要修改的欄位"), 1, 0)
        layout.addWidget(self.field_combo, 1, 1)
        layout.addWidget(QLabel("新內容"), 2, 0)
        layout.addWidget(self.value_edit, 2, 1)

        button_row = QHBoxLayout()
        clear_button = QPushButton("清空內容")
        clear_button.clicked.connect(self.value_edit.clear)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)

        apply_button = QPushButton("套用")
        apply_button.clicked.connect(self.accept)
        button_row.addWidget(apply_button)
        layout.addLayout(button_row, 3, 0, 1, 2)

    def values(self):
        return (
            self.field_combo.currentData(),
            self.value_edit.toPlainText().strip(),
        )


class BatchEditPreviewDialog(QDialog):
    def __init__(self, field_label, new_value, preview_lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批次修改預覽")
        self.setModal(True)
        self.resize(560, 440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        summary = QLabel(
            f"欄位：{field_label}\n"
            f"新內容：{new_value or '(清空)'}\n"
            f"預覽筆數：{len(preview_lines)}"
        )
        layout.addWidget(summary)

        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText("\n".join(preview_lines))
        layout.addWidget(details, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        apply_button = QPushButton("確認套用")
        apply_button.clicked.connect(self.accept)
        button_row.addWidget(apply_button)
        layout.addLayout(button_row)


class SharedLandBatchDialog(QDialog):
    def __init__(self, initial_values=None, parent=None):
        super().__init__(parent)
        initial_values = initial_values or {}
        self.setWindowTitle("同地號批量新增")
        self.setModal(True)
        self.resize(760, 520)

        self.shared_inputs = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        shared_layout = QGridLayout()
        shared_fields = (
            ("district", "地區"),
            ("section", "地段"),
            ("land_number", "地號"),
            ("area", "面積/m²"),
            ("declared_value", "公告現值"),
        )
        for index, (key, label) in enumerate(shared_fields):
            field_row = (index // 3) * 2
            column = index % 3
            edit = QLineEdit(str(initial_values.get(key) or ""))
            self.shared_inputs[key] = edit
            shared_layout.addWidget(QLabel(label), field_row, column)
            shared_layout.addWidget(edit, field_row + 1, column)
        layout.addLayout(shared_layout)

        layout.addWidget(
            QLabel(
                "每行一筆，欄位順序：登記次序、姓名、身分證、地址、分子、分母、備註、出訪記錄。\n"
                "可直接從 Excel 複製貼上（Tab 分隔），也接受逗號分隔；姓名為必填。"
            )
        )
        self.rows_edit = QPlainTextEdit()
        self.rows_edit.setPlaceholderText(
            "1\t王小明\tA123456789\t台北市中正區\t1\t2\t備註\t首次拜訪\n"
            "2\t陳小華\tB123456789\t新北市板橋區\t1\t2"
        )
        layout.addWidget(self.rows_edit, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        preview_button = QPushButton("預覽")
        preview_button.clicked.connect(self.accept)
        button_row.addWidget(preview_button)
        layout.addLayout(button_row)

    def values(self):
        return (
            {key: edit.text().strip() for key, edit in self.shared_inputs.items()},
            self.rows_edit.toPlainText(),
        )


class SavedSearchDialog(QDialog):
    def __init__(self, saved_searches, parent=None):
        super().__init__(parent)
        self.setWindowTitle("常用搜尋條件")
        self.setModal(True)
        self.resize(520, 420)
        self.saved_searches = list(saved_searches)
        self.selected_criteria = None

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["名稱", "條件摘要"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(self.table, 1)

        button_row = QHBoxLayout()
        load_button = QPushButton("載入")
        load_button.clicked.connect(self.load_selected)
        button_row.addWidget(load_button)
        delete_button = QPushButton("刪除")
        delete_button.clicked.connect(self.delete_selected)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("操作記錄")
        self.setModal(True)
        self.resize(860, 520)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["時間", "類型", "摘要", "明細"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(self.table, 1)

        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignRight)

        self.load_logs()

    def load_logs(self):
        rows = get_operation_logs()
        self.table.setRowCount(0)
        for row in rows:
            row_number = self.table.rowCount()
            self.table.insertRow(row_number)
            self.table.setItem(row_number, 0, QTableWidgetItem(row["created_at"]))
            self.table.setItem(row_number, 1, QTableWidgetItem(row["action_type"]))
            self.table.setItem(row_number, 2, QTableWidgetItem(row["summary"]))
            self.table.setItem(row_number, 3, QTableWidgetItem(row["detail"] or ""))


class WatchlistDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("注意名單管理")
        self.setModal(True)
        self.resize(560, 420)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["姓名", "備註"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)

        self.create_layout()
        self.load_entries()

    def create_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(self.table, 1)

        button_row = QHBoxLayout()
        add_button = QPushButton("新增")
        add_button.clicked.connect(self.add_row)
        button_row.addWidget(add_button)

        delete_button = QPushButton("刪除")
        delete_button.clicked.connect(self.delete_selected_row)
        button_row.addWidget(delete_button)

        button_row.addStretch(1)

        save_button = QPushButton("儲存")
        save_button.clicked.connect(self.save_entries)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def load_entries(self):
        rows = get_watchlist_entries()
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
        replace_watchlist_entries(self.collect_entries())
        self.accept()
