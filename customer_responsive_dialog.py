"""Shared screen-aware behavior for application dialogs."""

from PySide6.QtWidgets import QApplication, QDialog


QT_MAX_WIDGET_SIZE = 16777215


class ResponsiveDialog(QDialog):
    """Keep a dialog inside the usable area of its current screen."""

    screen_width_ratio = 0.94
    screen_height_ratio = 0.90

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_to_available_screen()

    def fit_to_available_screen(self, available_geometry=None):
        if available_geometry is None:
            screen = self.screen() or QApplication.primaryScreen()
            if screen is None:
                return
            available_geometry = screen.availableGeometry()

        max_width = max(1, int(available_geometry.width() * self.screen_width_ratio))
        max_height = max(1, int(available_geometry.height() * self.screen_height_ratio))

        if self.width() > max_width:
            self.setMinimumWidth(0)
            if self.maximumWidth() == self.width():
                self.setMaximumWidth(QT_MAX_WIDGET_SIZE)
        if self.height() > max_height:
            self.setMinimumHeight(0)
            if self.maximumHeight() == self.height():
                self.setMaximumHeight(QT_MAX_WIDGET_SIZE)

        self.resize(min(self.width(), max_width), min(self.height(), max_height))

        frame = self.frameGeometry()
        frame.moveCenter(available_geometry.center())
        x = min(
            max(frame.left(), available_geometry.left()),
            available_geometry.right() - frame.width() + 1,
        )
        y = min(
            max(frame.top(), available_geometry.top()),
            available_geometry.bottom() - frame.height() + 1,
        )
        self.move(x, y)
