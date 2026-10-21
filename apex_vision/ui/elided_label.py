"""A QLabel that elides (…) instead of clipping when it is given less room than its text needs."""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    """Single-line label: shows as much text as fits, the full text goes to the tooltip."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self._auto_tip = True
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def full_text(self) -> str:
        return self._full

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        text = text or ""
        if self._auto_tip and self.toolTip() in ("", self._full):
            self.setToolTip(text)
        self._full = text
        self._refresh()

    def setToolTip(self, tip: str) -> None:  # noqa: N802
        # An explicit tooltip from the caller wins over the automatic full-text one.
        self._auto_tip = tip in ("", self._full)
        super().setToolTip(tip)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + 2, super().sizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        avail = max(0, self.width() - self.contentsMargins().left() - self.contentsMargins().right())
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, avail) \
            if avail else self._full
        super().setText(shown)
