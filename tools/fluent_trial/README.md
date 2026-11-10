# Fluent 元件試用（PySide6-Fluent-Widgets）

**這是 2026-11-02 的試用紀錄，已被正式改造取代**：Fluent 第 1 批起正式程式已改用 Fluent（見 `docs\Fluent改造計畫.md`），套件也裝進打包用的 Python。這個資料夾只保留當時的比較，可整個刪除。

## 內容

| 檔案 | 說明 |
|---|---|
| `auth_dialog_fluent.ui` | 登入對話框的 Fluent 版（複製自 `ui\dialogs\auth_dialog.ui`，按鈕／輸入框／標籤用「提升」換成 Fluent 類別） |
| `font_size_dialog_fluent.ui` | 字體大小對話框的 Fluent 版 |
| `preview_fluent.py` | 並排顯示「目前版本」與「Fluent 版」，範例資料，不讀寫任何資料 |
| `screenshots\` | 淺色／深色截圖；`comparison_all.png` 是全部並排 |

## 預覽

套件裝在專案外的獨立環境 `..\..\..\.venv_fluent_trial`（即 `outputs\.venv_fluent_trial`），在專案資料夾執行：

```
..\.venv_fluent_trial\Scripts\python tools\fluent_trial\preview_fluent.py AuthDialog
..\.venv_fluent_trial\Scripts\python tools\fluent_trial\preview_fluent.py FontSizeDialog dark
```

加 `--only fluent` 只看 Fluent 版。

版本：PySide6 6.11.1（與正式程式相同）、PySide6-Fluent-Widgets 1.11.3、PySideSix-Frameless-Window 0.8.2。

## 移除試用

刪掉兩個資料夾即可，正式程式不受影響：

1. `C:\Users\Laptop\Documents\Codex\2026-06-24\new-chat\outputs\.venv_fluent_trial`
2. `customer_system\tools\fluent_trial`
