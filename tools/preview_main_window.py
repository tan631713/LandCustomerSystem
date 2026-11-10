"""Open the desktop main window with an empty throw-away database to check ui/ edits.

    python tools\\preview_main_window.py          (light theme)
    python tools\\preview_main_window.py dark     (dark theme)
    python tools\\preview_main_window.py --screenshot out.png
    python tools\\preview_main_window.py --sample   (three sample owners, one land
                                                 selected and two rows checked)

No login, no real data: the window runs against a new database in a temporary
folder that is deleted afterwards, and the main splitter position is not saved.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("theme", nargs="?", default="light", choices=("light", "dark"))
    parser.add_argument("--screenshot", help="save a PNG of the window and exit")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="add sample owners so the land header, share bar and batch bar show",
    )
    args = parser.parse_args(argv)

    from cryptography.fernet import Fernet
    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication

    import customer_theme
    import customer_ui_qt as app
    import customer_window_ui
    from customer_database import CustomerDatabase
    from customer_repository import CustomerRepository

    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    with tempfile.TemporaryDirectory(prefix="land-ui-preview-") as folder:
        temp = Path(folder)
        app.DB_PATH = temp / "customers.db"
        app.BACKUP_DIR = temp / "backups"
        app.DATABASE = CustomerDatabase(app.DB_PATH, app.BACKUP_DIR)
        app.REPOSITORY = CustomerRepository(
            app.DATABASE, app.SCHEMA_PATH, temp / "missing-seed.sql", app.LAND_FIELDS
        )
        app.init_db()
        customer_theme.activate_theme(args.theme)
        app.refresh_theme_constants()
        customer_theme.load_bundled_fonts()
        app.apply_font_size(qt_app, app.get_saved_font_size_key())
        app.apply_app_style(qt_app)

        settings = QSettings(str(temp / "layout.ini"), QSettings.IniFormat)
        with patch.object(customer_window_ui, "QSettings", return_value=settings):
            window = app.LandApp(Fernet.generate_key())
        window.setWindowTitle(window.windowTitle() + "（介面預覽，空白測試資料）")
        if args.sample:
            add_sample_records(app, window)
        window.show()
        if args.screenshot:
            def save_and_quit():
                window.grab().save(args.screenshot)
                window.close()
                qt_app.quit()

            QTimer.singleShot(500, save_and_quit)
        result = qt_app.exec()
        window.close()
        qt_app.processEvents()
        return result


SAMPLE_OWNERS = (
    ("123", "王小明", "1", "2", "下午較方便"),
    ("123", "李小華", "1", "2", ""),
    ("124", "陳大文", "1", "1", ""),
)


def add_sample_records(app, window):
    """Three owners on two lands in the throw-away database; select one, tick two."""

    from PySide6.QtCore import QEventLoop, QTimer

    record_ids = []
    for land_number, owner, numerator, denominator, note in SAMPLE_OWNERS:
        plain = window.normalize_record_data({
            "district": "桃園區", "section": "中路段", "subsection": "", "land_number": land_number,
            "area": "100", "declared_value": "1000", "numerator": numerator,
            "denominator": denominator, "owner_name": owner, "external_id": "",
            "address": "桃園市", "note": note, "name": owner,
        })
        record_ids.append(app.REPOSITORY.save_customer(app.encrypt_record(window.fernet, plain)))
    window.refresh_records(record_ids[0])
    loop = QEventLoop()
    for _attempt in range(200):
        if not window.record_searches:
            break
        QTimer.singleShot(30, loop.quit)
        loop.exec()
    window.select_record_in_table(record_ids[0])
    window.update_checked_records([record_ids[0], record_ids[2]], True, "預覽")


if __name__ == "__main__":
    raise SystemExit(main())
