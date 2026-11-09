"""Qt Designer plugin: puts the Fluent widgets in Designer's widget box.

pyside6-designer loads every ``register*.py`` in the folders listed in the
PYSIDE_DESIGNER_PLUGINS environment variable; tools\\open_designer.bat sets it
to this folder.  The widgets then appear in the widget box under
"Fluent 按鈕", "Fluent 輸入", ... and are drawn as they look in the program
(accent colour and font from ui\\fluent_theme.json).

Without this plugin the .ui files still open in Designer: their Fluent widgets
are "promoted" widgets and show as the plain Qt widget they extend.
"""

# Designer runs this file with separate globals and locals, so names defined
# at the top level are not visible inside functions: everything lives in
# _register_fluent_widgets() and is reached through its closure.


def _register_fluent_widgets():
    import json
    import os
    from pathlib import Path

    from PySide6.QtDesigner import QPyDesignerCustomWidgetCollection

    import qfluentwidgets

    try:
        ROOT = Path(__file__).resolve().parents[2]
    except NameError:  # not every Designer version defines __file__
        ROOT = Path(os.environ["PYSIDE_DESIGNER_PLUGINS"].split(os.pathsep)[0]).resolve().parents[1]
    MODULE = "qfluentwidgets"

    # (group, class name, default objectName, text shown when dropped)
    WIDGETS = (
        ("Fluent 按鈕", "PushButton", "pushButton", "按鈕"),
        ("Fluent 按鈕", "PrimaryPushButton", "primaryButton", "主要按鈕"),
        ("Fluent 按鈕", "TransparentPushButton", "transparentButton", "透明按鈕"),
        ("Fluent 按鈕", "ToggleButton", "toggleButton", "切換按鈕"),
        ("Fluent 按鈕", "DropDownPushButton", "dropDownButton", "下拉按鈕"),
        ("Fluent 按鈕", "TransparentDropDownPushButton", "transparentDropDownButton", "透明下拉按鈕"),
        ("Fluent 按鈕", "HyperlinkButton", "hyperlinkButton", "連結"),
        ("Fluent 按鈕", "ToolButton", "toolButton", None),
        ("Fluent 按鈕", "TransparentToolButton", "transparentToolButton", None),
        ("Fluent 按鈕", "CheckBox", "checkBox", "勾選框"),
        ("Fluent 按鈕", "RadioButton", "radioButton", "選項"),
        ("Fluent 按鈕", "SwitchButton", "switchButton", None),
        ("Fluent 輸入", "LineEdit", "lineEdit", None),
        ("Fluent 輸入", "PasswordLineEdit", "passwordEdit", None),
        ("Fluent 輸入", "SearchLineEdit", "searchEdit", None),
        ("Fluent 輸入", "ComboBox", "comboBox", None),
        ("Fluent 輸入", "EditableComboBox", "editableComboBox", None),
        ("Fluent 輸入", "SpinBox", "spinBox", None),
        ("Fluent 輸入", "DoubleSpinBox", "doubleSpinBox", None),
        ("Fluent 輸入", "DateEdit", "dateEdit", None),
        ("Fluent 輸入", "TimeEdit", "timeEdit", None),
        ("Fluent 輸入", "PlainTextEdit", "plainTextEdit", None),
        ("Fluent 輸入", "TextEdit", "textEdit", None),
        ("Fluent 輸入", "Slider", "slider", None),
        ("Fluent 文字", "BodyLabel", "bodyLabel", "內文"),
        ("Fluent 文字", "StrongBodyLabel", "strongBodyLabel", "粗體內文"),
        ("Fluent 文字", "CaptionLabel", "captionLabel", "小字說明"),
        ("Fluent 文字", "SubtitleLabel", "subtitleLabel", "副標題"),
        ("Fluent 文字", "TitleLabel", "titleLabel", "標題"),
        ("Fluent 顯示", "ProgressBar", "progressBar", None),
        ("Fluent 顯示", "TableWidget", "tableWidget", None),
        ("Fluent 顯示", "ListWidget", "listWidget", None),
        ("Fluent 顯示", "TreeWidget", "treeWidget", None),
    )
    CONTAINERS = (
        ("Fluent 容器", "CardWidget", "cardWidget"),
        ("Fluent 容器", "SimpleCardWidget", "simpleCardWidget"),
    )


    def _apply_program_look():
        """Same accent colour / fonts as the program (light theme), if the file reads."""

        try:
            data = json.loads((ROOT / "ui" / "fluent_theme.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        qfluentwidgets.setThemeColor(data.get("primaryColor") or "#2F6B4F")
        families = data.get("fontFamilies") or ["Microsoft JhengHei UI", "Microsoft JhengHei", "Segoe UI"]
        qfluentwidgets.setFontFamilies(list(families))


    def _qt_base(widget_class):
        """The Qt class it builds on (QPushButton for PrimaryPushButton), as the .ui files say."""

        for base in widget_class.__mro__[1:]:
            if base.__module__.startswith("PySide6"):
                return base.__name__
        return "QWidget"

    def _dom_xml(widget_class, object_name, text=None):
        class_name = widget_class.__name__
        text_property = (
            f'<property name="text"><string>{text}</string></property>' if text else ""
        )
        # <extends> keeps Designer from warning that the base class in a .ui
        # file (QPushButton) differs from the plugin's (PushButton).
        return (
            "<ui language='c++'>"
            f"<widget class='{class_name}' name='{object_name}'>{text_property}</widget>"
            "<customwidgets><customwidget>"
            f"<class>{class_name}</class><extends>{_qt_base(widget_class)}</extends>"
            "</customwidget></customwidgets>"
            "</ui>"
        )


    def register():
        _apply_program_look()
        for group, class_name, object_name, text in WIDGETS:
            widget_class = getattr(qfluentwidgets, class_name, None)
            if widget_class is None:
                continue
            QPyDesignerCustomWidgetCollection.registerCustomWidget(
                widget_class,
                xml=_dom_xml(widget_class, object_name, text),
                tool_tip=f"{class_name}（Fluent）",
                group=group,
                module=MODULE,
            )
        # The program's own Fluent-styled button row (header customer_fluent).
        import sys

        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        try:
            import customer_fluent

            button_box = customer_fluent.dialog_button_box_class()
        except Exception:  # the plugin must never stop Designer from opening
            button_box = None
        if button_box is not None:
            QPyDesignerCustomWidgetCollection.registerCustomWidget(
                button_box,
                xml=_dom_xml(button_box, "buttonBox"),
                tool_tip="DialogButtonBox（確定／取消列，程式執行時換成 Fluent 按鈕）",
                group="Fluent 按鈕",
                module="customer_fluent",
            )
        for group, class_name, object_name in CONTAINERS:
            widget_class = getattr(qfluentwidgets, class_name, None)
            if widget_class is None:
                continue
            QPyDesignerCustomWidgetCollection.registerCustomWidget(
                widget_class,
                xml=_dom_xml(widget_class, object_name),
                tool_tip=f"{class_name}（Fluent 容器）",
                group=group,
                module=MODULE,
                container=True,
            )

    register()


_register_fluent_widgets()
