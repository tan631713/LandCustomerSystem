"""TRIAL ONLY: the login / font-size dialogs as they are now vs. built with QFluentWidgets.

Needs the separate trial environment (PySide6-Fluent-Widgets is NOT installed
in the Python that builds the real program):

    ..\\.venv_fluent_trial\\Scripts\\python tools\\fluent_trial\\preview_fluent.py AuthDialog
    ..\\.venv_fluent_trial\\Scripts\\python tools\\fluent_trial\\preview_fluent.py FontSizeDialog dark
    ... --only fluent              (just the Fluent version)
    ... --screenshots <folder>     (save PNGs of both versions and exit)

Nothing here is used by the real program or the build; no data is read or
written.  The Fluent .ui files are copies of ui\\dialogs\\*.ui with the buttons,
boxes and labels promoted (Designer "Promote to...") to Fluent classes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DIALOGS = ("AuthDialog", "FontSizeDialog")
FLUENT_UI = {"AuthDialog": "auth_dialog_fluent.ui", "FontSizeDialog": "font_size_dialog_fluent.ui"}
FONT_SIZE_SAMPLE = (("small", "小"), ("medium", "中"), ("large", "大"), ("xlarge", "特大"))


def load_fluent_ui(file_name):
    """QUiLoader with the Fluent classes registered, so promoted widgets become them."""

    import qfluentwidgets
    from PySide6.QtCore import QFile, QIODevice
    from PySide6.QtUiTools import QUiLoader

    loader = QUiLoader()
    for class_name in ("BodyLabel", "SubtitleLabel", "LineEdit", "PasswordLineEdit",
                       "PushButton", "PrimaryPushButton", "ComboBox"):
        loader.registerCustomWidget(getattr(qfluentwidgets, class_name))
    ui_file = QFile(str(HERE / file_name))
    ui_file.open(QIODevice.ReadOnly)
    try:
        widget = loader.load(ui_file)
    finally:
        ui_file.close()
    if widget is None:
        raise RuntimeError(loader.errorString())
    return widget


def build_fluent(name, theme):
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QDialog, QVBoxLayout

    dialog = QDialog()
    content = load_fluent_ui(FLUENT_UI[name])
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(content)
    dialog.setWindowTitle(content.windowTitle() + "（Fluent 試用）")
    dialog.setMinimumSize(content.minimumSize())
    dialog.setMaximumSize(content.maximumSize())
    content.setMinimumSize(0, 0)
    content.setMaximumSize(16777215, 16777215)
    size = content.property("dialogSize")
    if isinstance(size, QSize) and size.isValid():
        dialog.resize(size)
    # Fluent's own window colours (Windows 11 "Mica" fallback greys).
    dialog.setStyleSheet(
        "QDialog { background-color: %s; }" % ("#202020" if theme == "dark" else "#F3F3F3")
    )
    if name == "AuthDialog":
        content.findChild(object, "passwordEdit").setPlaceholderText("請輸入密碼")
        content.findChild(object, "confirmEdit").hide()
        content.findChild(object, "confirmLabel").hide()
    else:
        combo = content.findChild(object, "fontSizeCombo")
        for key, label in FONT_SIZE_SAMPLE:
            combo.addItem(label, userData=key)
        combo.setCurrentIndex(1)
    return dialog


def build_original(name, theme):
    import customer_auth
    import customer_dialogs
    import customer_theme

    dialog = (customer_auth.AuthDialog(setup_mode=False) if name == "AuthDialog"
              else customer_dialogs.FontSizeDialog("medium"))
    dialog.setWindowTitle(dialog.windowTitle() + "（目前版本）")
    # The real program sets this sheet on the whole application; here it is
    # set on this one dialog so it cannot restyle the Fluent widgets.
    dialog.setStyleSheet(customer_theme.build_app_stylesheet(customer_theme.theme_tokens()))
    return dialog


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", choices=DIALOGS)
    parser.add_argument("theme", nargs="?", default="light", choices=("light", "dark"))
    parser.add_argument("--only", choices=("original", "fluent"))
    parser.add_argument("--screenshots", help="folder for PNGs; exits after saving them")
    args = parser.parse_args(argv)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    import customer_theme
    import customer_ui_qt as legacy  # noqa: F401 - injects the dialogs' settings
    import qfluentwidgets

    customer_theme.activate_theme(args.theme)
    legacy.refresh_theme_constants()
    customer_theme.load_bundled_fonts()
    legacy.apply_font_size(app, legacy.DEFAULT_FONT_SIZE_KEY)

    qfluentwidgets.setTheme(qfluentwidgets.Theme.DARK if args.theme == "dark" else qfluentwidgets.Theme.LIGHT)
    qfluentwidgets.setThemeColor(customer_theme.token("green"))
    if hasattr(qfluentwidgets, "setFontFamilies"):
        # Fluent defaults to Microsoft YaHei (Simplified Chinese glyph shapes).
        qfluentwidgets.setFontFamilies(["Segoe UI", "Microsoft JhengHei UI", "Microsoft JhengHei"])

    shown = []
    if args.only != "fluent":
        shown.append(("original", build_original(args.name, args.theme)))
    if args.only != "original":
        shown.append(("fluent", build_fluent(args.name, args.theme)))
    x = 120
    for _kind, dialog in shown:
        dialog.move(x, 160)
        dialog.show()
        x += dialog.width() + 40

    if args.screenshots:
        folder = Path(args.screenshots)
        folder.mkdir(parents=True, exist_ok=True)

        def save_and_quit():
            for kind, dialog in shown:
                dialog.grab().save(str(folder / f"{args.name}_{kind}_{args.theme}.png"))
            app.quit()

        QTimer.singleShot(800, save_and_quit)
    else:
        for _kind, dialog in shown:
            dialog.finished.connect(lambda _result: app.quit() if not any(d.isVisible() for _k, d in shown) else None)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
