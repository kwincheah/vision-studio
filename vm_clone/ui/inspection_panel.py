"""The Inspection panel: dataset evaluation, failure analysis and experiments.

A thin Qt view over `inspection_controller.InspectionController`.  All decisions - what a
metric is, which failures exist, whether two runs are comparable - are made in the
controller and the evaluation package; this module renders them and forwards user intent.

Layout follows the existing application: the amber accent marks the active/selected
element, panels use the standard `panelHeader` strip, tables use the shared row height,
and undefined metrics print as `n/a` in muted ink rather than as `0`, which would be a
false statement about the detector.

The evaluation itself runs on a worker thread, because a dataset run takes seconds to
minutes and blocking the event loop would freeze the whole application.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal

import logging

LOG = logging.getLogger(__name__)
from PyQt6.QtGui import QColor, QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from vm_clone.ui.inspection_controller import (
    DUPLICATE, FP, FN, FailureCase, InspectionController, filter_failures,
    failure_summary,
)
from vm_clone.ui.styles import SIZE, SPACE, THEME, TYPE

#: Overlay colours, drawn from the approved palette so the failure view reads as part of
#: the same application.  Ground truth and predictions are deliberately different hues
#: *and* different line styles, so the two are distinguishable without relying on colour
#: alone.
COLOR_GROUND_TRUTH = (0, 176, 120)      # teal: the annotation
COLOR_TRUE_POSITIVE = (48, 160, 228)    # blue: a correct prediction
COLOR_FALSE_POSITIVE = (32, 28, 200)    # red: a false alarm
COLOR_FALSE_NEGATIVE = (32, 140, 240)   # amber-blue: a missed defect
COLOR_DUPLICATE = (170, 90, 200)        # violet: a duplicate box

_KIND_COLORS = {
    FP: COLOR_FALSE_POSITIVE,
    DUPLICATE: COLOR_DUPLICATE,
    FN: COLOR_FALSE_NEGATIVE,
}

_KIND_LABELS = {
    FP: "False positive",
    FN: "Missed defect",
    DUPLICATE: "Duplicate box",
}


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
class EvaluationWorker(QObject):
    """Runs one evaluation off the GUI thread.

    Emits progress, then either `finished` with the outcome or `failed` with a message.
    The controller is mutated only on the worker thread while it runs, and the panel
    reads it only after `finished` - so there is no concurrent access to its state.
    """
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, controller: InspectionController, kwargs: Dict[str, Any]):
        super().__init__()
        self.controller = controller
        self.kwargs = kwargs
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            outcome = self.controller.run_evaluation(
                progress=lambda i, n, p: self.progress.emit(i, n, p),
                should_cancel=lambda: self._cancelled,
                **self.kwargs)
        except Exception as exc:                        # noqa: BLE001 - reported to the UI
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(outcome)


# ---------------------------------------------------------------------------
# Small shared widgets
# ---------------------------------------------------------------------------
def _inform(parent, title: str, text: str) -> None:
    """Show an informational dialog, unless the panel is running headless.

    A modal dialog blocks the calling thread until a human dismisses it, which makes
    automated screenshot capture and UI testing impossible - the capture script hung
    here.  `APEX_HEADLESS_UI=1` routes these confirmations to the status message
    instead, so the same code path can be exercised without a person present.
    """
    if os.environ.get("APEX_HEADLESS_UI") == "1":
        return
    QMessageBox.information(parent, title, text)


def _error(parent, title: str, text: str) -> None:
    """Report an error without blocking when running headless.

    Errors are never suppressed - losing them would hide real failures - but the modal
    dialog is skipped under `APEX_HEADLESS_UI=1` and the text is emitted through the
    panel's status signal instead, so an automated run records the failure rather than
    hanging on a dialog nobody can dismiss.
    """
    LOG.error("%s: %s", title, text)
    if os.environ.get("APEX_HEADLESS_UI") == "1":
        return
    QMessageBox.critical(parent, title, text)


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setObjectName("panelHeader")
    label.setFixedHeight(SIZE["header"])
    label.setContentsMargins(SPACE["base"], 0, SPACE["base"], 0)
    return label


def _table(headers: Sequence[str], stretch_last: bool = True,
           select_rows: bool = False) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows
                               if select_rows
                               else QAbstractItemView.SelectionBehavior.SelectItems)
    table.setAlternatingRowColors(True)
    table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents)
    if stretch_last:
        table.horizontalHeader().setStretchLastSection(True)
    table.verticalHeader().setDefaultSectionSize(SIZE["row"])
    return table


def _muted_item(text: str) -> QTableWidgetItem:
    """An item for an undefined value: greyed, so `n/a` never reads as a figure."""
    item = QTableWidgetItem(text)
    item.setForeground(QColor(THEME["text_muted"]))
    item.setFont(QFont(THEME.get("font_family", "Segoe UI")))
    return item


def _value_item(text: str) -> QTableWidgetItem:
    return QTableWidgetItem(text)


# ---------------------------------------------------------------------------
# Failure case list
# ---------------------------------------------------------------------------
class FailureListWidget(QTreeWidget):
    """Failures grouped by image, with kind, class, confidence and reason columns."""

    case_selected = pyqtSignal(object)

    COLUMNS = ("Failure", "Class", "Confidence", "IoU vs truth", "Why")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("failureList")
        self.setColumnCount(len(self.COLUMNS))
        self.setHeaderLabels(list(self.COLUMNS))
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.header().setStretchLastSection(True)
        self.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.verticalScrollBar().setSingleStep(SIZE["row"])
        self._cases: List[FailureCase] = []
        self.currentItemChanged.connect(self._on_current_changed)

    def set_cases(self, cases: Sequence[FailureCase]) -> None:
        self._cases = list(cases)
        self.clear()
        by_image: Dict[str, List[FailureCase]] = {}
        for case in cases:
            by_image.setdefault(case.image, []).append(case)

        for image in sorted(by_image):
            parent = QTreeWidgetItem(self, [os.path.basename(image), "", "", "", ""])
            parent.setFirstColumnSpanned(True)
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            parent.setFont(0, QFont(THEME.get("font_family", "Segoe UI"), -1,
                                    QFont.Weight.DemiBold))
            for case in by_image[image]:
                score = "n/a" if case.score is None else f"{case.score:.3f}"
                iou = f"{case.best_iou:.3f}" if case.best_iou else "0.000"
                child = QTreeWidgetItem(parent, [
                    _KIND_LABELS.get(case.kind, case.kind), case.label, score, iou,
                    case.reason])
                child.setData(0, Qt.ItemDataRole.UserRole, case)
                child.setForeground(0, QColor(_qss_hex(_KIND_COLORS.get(
                    case.kind, COLOR_FALSE_POSITIVE))))
                child.setToolTip(0, f"{case.reason}\nBox: {tuple(round(v, 1) for v in case.box)}"
                                    f"\nNearest class: {case.nearest_label or '-'}")
            parent.setExpanded(True)
            if self.topLevelItemCount() == 1:
                self.expandItem(parent)

    def selected_case(self) -> Optional[FailureCase]:
        item = self.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def select_case(self, index: int) -> None:
        """Select the nth case in list order, for next/previous navigation."""
        flat: List[QTreeWidgetItem] = []
        for i in range(self.topLevelItemCount()):
            parent = self.topLevelItem(i)
            for j in range(parent.childCount()):
                flat.append(parent.child(j))
        if not flat:
            return
        index = max(0, min(index, len(flat) - 1))
        self.setCurrentItem(flat[index])
        self.scrollToItem(flat[index])

    def flat_count(self) -> int:
        return sum(self.topLevelItem(i).childCount()
                   for i in range(self.topLevelItemCount()))

    def current_flat_index(self) -> int:
        current = self.currentItem()
        if current is None:
            return -1
        index = 0
        for i in range(self.topLevelItemCount()):
            parent = self.topLevelItem(i)
            for j in range(parent.childCount()):
                if parent.child(j) is current:
                    return index
                index += 1
        return -1

    def _on_current_changed(self, current, _previous):
        if current is None:
            return
        case = current.data(0, Qt.ItemDataRole.UserRole)
        if case is not None:
            self.case_selected.emit(case)


def _qss_hex(rgb: Sequence[int]) -> str:
    """A QSS hex string from an (R, G, B) tuple, for widget colours."""
    r, g, b = (int(v) for v in rgb[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Image view for the failure analysis
# ---------------------------------------------------------------------------
class FailureImageView(QLabel):
    """Shows one image with ground truth and predictions drawn on it.

    Kept deliberately separate from `ImageCanvasWidget`, which is a pan/zoom instrument
    for the flow editor.  What the failure view needs is a *legible* comparison - both
    the annotation and the prediction visible at once, in different colours - not the
    same interactive surface.  The overlay data model it consumes is the same
    (`{"type": "rect", "box": [...], "color": (B, G, R), "label": ...}`), so the drawing
    conventions do not diverge.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("failureImage")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(140)
        self.setWordWrap(True)
        self._pixmap: Optional[QPixmap] = None

    def show_placeholder(self, text: str) -> None:
        self._pixmap = None
        self.setPixmap(QPixmap())
        self.setText(text)

    def show_case(self, image_path: str, match_result, case: Optional[FailureCase],
                  show_ground_truth: bool = True,
                  show_predictions: bool = True) -> Optional[str]:
        """Render an image with the relevant boxes.  Returns an error message or None."""
        import cv2
        import numpy as np

        if not image_path or not os.path.exists(image_path):
            self.show_placeholder(f"Image not available:\n{image_path}")
            return f"image not found: {image_path}"

        image = cv2.imread(image_path)
        if image is None:
            self.show_placeholder(f"Could not read:\n{image_path}")
            return f"unreadable image: {image_path}"

        canvas = image.copy()
        # Ground truth first, so a prediction over it is visible.
        if show_ground_truth and match_result is not None:
            for pair in match_result.pairs:
                _draw_box(canvas, pair.annotation.box, COLOR_GROUND_TRUTH,
                          f"GT {pair.annotation.label}", dashed=True)
            for item in match_result.false_negatives:
                _draw_box(canvas, item.annotation.box, COLOR_FALSE_NEGATIVE,
                          f"MISSED {item.annotation.label}")
        if show_predictions and match_result is not None:
            for pair in match_result.pairs:
                _draw_box(canvas, pair.prediction.box, COLOR_TRUE_POSITIVE,
                          f"{pair.prediction.label} {pair.prediction.score:.2f}")
            for item in match_result.false_positives:
                _draw_box(canvas, item.prediction.box, COLOR_FALSE_POSITIVE,
                          f"FALSE {item.prediction.label} {item.prediction.score:.2f}")
            for item in match_result.duplicates:
                _draw_box(canvas, item.prediction.box, COLOR_DUPLICATE,
                          f"DUP {item.prediction.label}")

        # Highlight the selected case so the list selection and the image agree.
        if case is not None:
            _draw_box(canvas, case.box, (255, 255, 255), "selected", thickness=3)

        self._set_image(canvas)
        return None

    def _set_image(self, bgr) -> None:
        h, w = bgr.shape[:2]
        rgb = bgr[:, :, ::-1].copy()
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg.copy())
        self._pixmap = pixmap
        self.setText("")
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None:
            return
        self.setPixmap(self._pixmap.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()


def _draw_box(canvas, box: Sequence[float], color: Sequence[int], label: str,
              thickness: int = 2, dashed: bool = False) -> None:
    """Draw one (x, y, w, h) box with a label chip.

    `color` is (B, G, R) to match OpenCV, and the label chip is drawn with an opaque
    background so the text stays readable over any part of the board.
    """
    import cv2

    x, y, w, h = (int(round(v)) for v in box)
    if w <= 0 or h <= 0:
        return
    # cv2 cannot draw dashed lines directly; a solid core with a contrasting outline
    # achieves the same distinction between ground truth and prediction.
    if dashed:
        cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 1)
        for offset in range(0, max(w, h), 8):
            if offset < w:
                cv2.line(canvas, (x + offset, y), (min(x + offset + 4, x + w), y),
                         color, 2)
                cv2.line(canvas, (x + offset, y + h),
                         (min(x + offset + 4, x + w), y + h), color, 2)
    else:
        cv2.rectangle(canvas, (x, y), (x + w, y + h), color, thickness)
    if label:
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale, thick = 0.42, 1
        (tw, th), _base = cv2.getTextSize(label, font, scale, thick)
        ty = y - 4 if y - th - 8 > 0 else y + h + th + 6
        cv2.rectangle(canvas, (x, ty - th - 4), (x + tw + 6, ty + 4), color, -1)
        cv2.putText(canvas, label, (x + 3, ty), font, scale, (255, 255, 255), thick,
                    cv2.LINE_AA)


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------
class InspectionPanel(QWidget):
    """Dataset evaluation, failure analysis, experiments and comparison.

    Owns an `InspectionController`; the main window constructs the panel with a store
    directory and can push the active solution in as the workflow to evaluate.
    """

    status_message = pyqtSignal(str)

    def __init__(self, controller: Optional[InspectionController] = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("inspectionPanel")
        self.controller = controller or InspectionController()
        self._thread: Optional[QThread] = None
        self._worker: Optional[EvaluationWorker] = None
        self._active_solution = None
        self._build()
        self._refresh_all()

    # -- construction ----------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("inspectionTabs")
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs)

        self.tabs.addTab(self._build_evaluate_tab(), "Evaluate")
        self.tabs.addTab(self._build_results_tab(), "Results")
        self.tabs.addTab(self._build_failures_tab(), "Failure Analysis")
        self.tabs.addTab(self._build_experiments_tab(), "Experiments")
        self.tabs.addTab(self._build_compare_tab(), "Compare")

    # ---- Evaluate ------------------------------------------------------
    def _build_evaluate_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(SPACE["base"], SPACE["base"], SPACE["base"],
                                 SPACE["base"])
        outer.setSpacing(SPACE["snug"])

        # dataset row
        dataset_box = QGroupBox("Dataset")
        dl = QVBoxLayout(dataset_box)
        row = QHBoxLayout()
        self.edit_dataset = QLineEdit()
        self.edit_dataset.setPlaceholderText(
            "annotations.json produced by  Tools > Inspection > Generate PCB Dataset")
        self.edit_dataset.setReadOnly(True)
        row.addWidget(self.edit_dataset, 1)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.on_browse_dataset)
        row.addWidget(btn_browse)
        btn_make = QPushButton("Generate Dataset...")
        btn_make.clicked.connect(self.on_generate_dataset)
        row.addWidget(btn_make)
        dl.addLayout(row)
        self.lbl_dataset_summary = QLabel("No dataset loaded.")
        self.lbl_dataset_summary.setObjectName("datasetSummary")
        self.lbl_dataset_summary.setWordWrap(True)
        dl.addWidget(self.lbl_dataset_summary)
        outer.addWidget(dataset_box)

        # settings row
        settings = QGroupBox("Evaluation settings")
        sl = QHBoxLayout(settings)

        sl.addWidget(QLabel("Source:"))
        self.combo_source = QComboBox()
        self.combo_source.addItems(["Reference detector", "Active workflow"])
        self.combo_source.setMinimumWidth(150)
        sl.addWidget(self.combo_source)

        sl.addWidget(QLabel("Operating point:"))
        self.combo_variant = QComboBox()
        self.combo_variant.addItems(["reference", "conservative"])
        sl.addWidget(self.combo_variant)

        sl.addWidget(QLabel("IoU threshold:"))
        self.spin_iou = QDoubleSpinBox()
        self.spin_iou.setRange(0.05, 1.0)
        self.spin_iou.setSingleStep(0.05)
        self.spin_iou.setValue(0.5)
        self.spin_iou.setDecimals(2)
        sl.addWidget(self.spin_iou)

        sl.addWidget(QLabel("Confidence:"))
        self.spin_confidence = QDoubleSpinBox()
        self.spin_confidence.setRange(0.0, 1.0)
        self.spin_confidence.setSingleStep(0.05)
        self.spin_confidence.setValue(0.0)
        self.spin_confidence.setDecimals(2)
        sl.addWidget(self.spin_confidence)

        self.chk_layout = QCheckBox("Supply board design layout")
        self.chk_layout.setChecked(True)
        self.chk_layout.setToolTip(
            "The detector uses the board's pad and trace geometry to distinguish a pad "
            "defect from missing copper.  Measured: without it, false positives rise "
            "from 3 to 156 over 12 boards.")
        sl.addWidget(self.chk_layout)

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("experiment name")
        self.edit_name.setMinimumWidth(130)
        sl.addWidget(QLabel("Name:"))
        sl.addWidget(self.edit_name)

        sl.addStretch(1)
        outer.addWidget(settings)

        # actions
        actions = QHBoxLayout()
        self.btn_run = QPushButton("Run evaluation")
        self.btn_run.setObjectName("primaryAction")
        self.btn_run.clicked.connect(self.on_run)
        actions.addWidget(self.btn_run)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.on_cancel)
        actions.addWidget(self.btn_cancel)
        self.btn_save = QPushButton("Save experiment")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.on_save_experiment)
        actions.addWidget(self.btn_save)
        self.btn_report = QPushButton("Copy text report")
        self.btn_report.setEnabled(False)
        self.btn_report.clicked.connect(self.on_copy_report)
        actions.addWidget(self.btn_report)
        actions.addStretch(1)
        outer.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        outer.addWidget(self.progress)

        self.lbl_store = QLabel()
        self.lbl_store.setObjectName("storePath")
        self.lbl_store.setWordWrap(True)
        outer.addWidget(self.lbl_store)

        outer.addStretch(1)
        return page

    # ---- Results -------------------------------------------------------
    def _build_results_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(SPACE["base"], SPACE["base"], SPACE["base"],
                                 SPACE["base"])
        outer.setSpacing(SPACE["snug"])

        # The headline numbers as a compact readout rather than a table: they are the
        # first thing to read and a two-column table wastes most of its width on them.
        headline = QHBoxLayout()
        headline.setSpacing(SPACE["section"])
        self.metric_labels: Dict[str, QLabel] = {}
        for key in ("Precision", "Recall", "F1", "mAP@IoU", "TP / FP / FN"):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            name = QLabel(key)
            name.setObjectName("metricName")
            value = QLabel("-")
            value.setObjectName("metricValue")
            cell.addWidget(name)
            cell.addWidget(value)
            self.metric_labels[key] = value
            holder = QWidget()
            holder.setLayout(cell)
            headline.addWidget(holder)
        headline.addStretch(1)
        self.lbl_headline_note = QLabel()
        self.lbl_headline_note.setObjectName("headlineNote")
        self.lbl_headline_note.setWordWrap(True)
        headline.addWidget(self.lbl_headline_note, 1)
        outer.addLayout(headline)

        self.lbl_metric_note = QLabel(
            "A match means a box overlapped ground truth above the IoU threshold with "
            "the same class. It is not evidence that the detection is correct. "
            "Metrics with no defined value (for example mAP without a confidence "
            "ranking) read <b>n/a</b>, never 0.")
        self.lbl_metric_note.setWordWrap(True)
        self.lbl_metric_note.setObjectName("metricNote")
        outer.addWidget(self.lbl_metric_note)

        # Everything else in three stacked sections, each taking a share of the height
        # so no table is squeezed below a readable number of rows.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(SPACE["hair"])
        ll.addWidget(_section("Per class"))
        self.table_classes = _table(["Class", "GT", "TP", "FP", "FN", "Precision",
                                     "Recall", "F1", "AP"])
        ll.addWidget(self.table_classes, 1)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(SPACE["hair"])
        rl.addWidget(_section("Latency (ms)"))
        self.table_latency = _table(["Stage", "mean", "median", "p95", "Note"])
        rl.addWidget(self.table_latency, 1)
        rl.addWidget(_section("Run details"))
        self.table_metrics = _table(["Detail", "Value"])
        rl.addWidget(self.table_metrics, 1)
        rl.addWidget(_section("Errors"))
        self.table_errors = _table(["Image", "Stage", "Message"])
        rl.addWidget(self.table_errors, 1)
        splitter.addWidget(right)

        splitter.setSizes([560, 620])
        outer.addWidget(splitter, 1)
        return page

    # ---- Failure analysis ----------------------------------------------
    def _build_failures_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(SPACE["base"], SPACE["base"], SPACE["base"],
                                 SPACE["base"])
        outer.setSpacing(SPACE["snug"])

        # filters
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Show:"))
        self.chk_fp = QCheckBox("False positives")
        self.chk_fp.setChecked(True)
        self.chk_fn = QCheckBox("Missed defects")
        self.chk_fn.setChecked(True)
        self.chk_dup = QCheckBox("Duplicates")
        self.chk_dup.setChecked(True)
        for chk in (self.chk_fp, self.chk_fn, self.chk_dup):
            chk.stateChanged.connect(self._refresh_failures)
            filters.addWidget(chk)

        filters.addWidget(QLabel("Class:"))
        self.combo_class = QComboBox()
        self.combo_class.addItem("all")
        self.combo_class.currentIndexChanged.connect(self._refresh_failures)
        filters.addWidget(self.combo_class)

        filters.addWidget(QLabel("Image:"))
        self.combo_image = QComboBox()
        self.combo_image.addItem("all")
        self.combo_image.currentIndexChanged.connect(self._refresh_failures)
        filters.addWidget(self.combo_image)

        filters.addWidget(QLabel("Min score:"))
        self.spin_min_score = QDoubleSpinBox()
        self.spin_min_score.setRange(0.0, 1.0)
        self.spin_min_score.setSingleStep(0.05)
        self.spin_min_score.setValue(0.0)
        self.spin_min_score.setDecimals(2)
        self.spin_min_score.valueChanged.connect(self._refresh_failures)
        filters.addWidget(self.spin_min_score)

        filters.addWidget(QLabel("Reason:"))
        self.combo_reason = QComboBox()
        self.combo_reason.addItem("all")
        self.combo_reason.currentIndexChanged.connect(self._refresh_failures)
        filters.addWidget(self.combo_reason)
        filters.addStretch(1)
        outer.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # left: the list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(SPACE["hair"])
        self.lbl_failure_summary = QLabel("Run an evaluation to list failures.")
        self.lbl_failure_summary.setObjectName("failureSummary")
        self.lbl_failure_summary.setWordWrap(True)
        ll.addWidget(self.lbl_failure_summary)
        self.failure_list = FailureListWidget()
        self.failure_list.case_selected.connect(self._on_case_selected)
        ll.addWidget(self.failure_list, 1)

        nav = QHBoxLayout()
        self.btn_prev = QPushButton("Previous")
        self.btn_prev.clicked.connect(lambda: self._step_case(-1))
        nav.addWidget(self.btn_prev)
        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(lambda: self._step_case(1))
        nav.addWidget(self.btn_next)
        self.btn_open_image = QPushButton("Open original image")
        self.btn_open_image.clicked.connect(self.on_open_original)
        nav.addWidget(self.btn_open_image)
        self.btn_export_failures = QPushButton("Export failures...")
        self.btn_export_failures.clicked.connect(self.on_export_failures)
        nav.addWidget(self.btn_export_failures)
        nav.addStretch(1)
        ll.addLayout(nav)
        splitter.addWidget(left)

        # right: the image and the selected case's detail
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(SPACE["hair"])
        rl.addWidget(_section("Ground truth and predictions"))
        self.failure_image = FailureImageView()
        rl.addWidget(self.failure_image, 1)
        toggles = QHBoxLayout()
        self.chk_show_gt = QCheckBox("Ground truth")
        self.chk_show_gt.setChecked(True)
        self.chk_show_gt.stateChanged.connect(self._render_selected_case)
        toggles.addWidget(self.chk_show_gt)
        self.chk_show_pred = QCheckBox("Predictions")
        self.chk_show_pred.setChecked(True)
        self.chk_show_pred.stateChanged.connect(self._render_selected_case)
        toggles.addWidget(self.chk_show_pred)
        toggles.addStretch(1)
        # A plain QLabel with a `color` rule renders as plain text, so HTML entities
        # would appear literally (`&nbsp;`).  Rich text is requested explicitly and the
        # spacing is done with CSS margins, which is what actually renders.
        self.lbl_legend = QLabel()
        self.lbl_legend.setObjectName("legend")
        self.lbl_legend.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_legend.setText(
            "<span style='color:#00b078'>ground truth</span>"
            "<span style='color:#5a6168'>&#160;&#183;&#160;</span>"
            "<span style='color:#30a0e4'>correct</span>"
            "<span style='color:#5a6168'>&#160;&#183;&#160;</span>"
            "<span style='color:#201cc8'>false alarm</span>"
            "<span style='color:#5a6168'>&#160;&#183;&#160;</span>"
            "<span style='color:#1c8cf0'>missed defect</span>"
            "<span style='color:#5a6168'>&#160;&#183;&#160;</span>"
            "<span style='color:#aa5ac8'>duplicate</span>")
        toggles.addWidget(self.lbl_legend)
        rl.addLayout(toggles)

        # The detail text is collapsible: when a reviewer is comparing boxes on the
        # image, the image wants the height, and the text is one keypress away.
        self.btn_detail = QPushButton("Show case detail")
        self.btn_detail.setCheckable(True)
        self.btn_detail.setChecked(True)
        self.btn_detail.toggled.connect(self._on_detail_toggled)
        detail_row = QHBoxLayout()
        detail_row.addWidget(self.btn_detail)
        detail_row.addStretch(1)
        rl.addLayout(detail_row)

        self.text_case_detail = QTextEdit()
        self.text_case_detail.setReadOnly(True)
        self.text_case_detail.setMinimumHeight(96)
        self.text_case_detail.setMaximumHeight(150)
        rl.addWidget(self.text_case_detail)
        splitter.addWidget(right)

        splitter.setSizes([400, 660])
        outer.addWidget(splitter, 1)
        return page

    # ---- Experiments ---------------------------------------------------
    def _build_experiments_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(SPACE["base"], SPACE["base"], SPACE["base"],
                                 SPACE["base"])
        outer.setSpacing(SPACE["snug"])

        row = QHBoxLayout()
        row.addWidget(QLabel("Store:"))
        self.edit_store = QLineEdit()
        self.edit_store.setPlaceholderText("choose a folder for experiment records")
        self.edit_store.editingFinished.connect(self._on_store_changed)
        row.addWidget(self.edit_store, 1)
        btn_choose = QPushButton("Change...")
        btn_choose.clicked.connect(self.on_choose_store)
        row.addWidget(btn_choose)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self._refresh_experiments)
        row.addWidget(btn_refresh)
        outer.addLayout(row)

        outer.addWidget(_section("Recorded experiments"))
        self.table_experiments = _table(
            ["Timestamp", "Name", "Dataset", "Split", "IoU", "Conf.",
             "Precision", "Recall", "F1", "FP", "FN", "Status"], select_rows=True)
        self.table_experiments.itemSelectionChanged.connect(self._on_experiment_sel)
        outer.addWidget(self.table_experiments, 1)

        outer.addWidget(_section("Selected record"))
        self.text_experiment = QTextEdit()
        self.text_experiment.setReadOnly(True)
        outer.addWidget(self.text_experiment, 1)
        return page

    # ---- Compare -------------------------------------------------------
    def _build_compare_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(SPACE["base"], SPACE["base"], SPACE["base"],
                                 SPACE["base"])
        outer.setSpacing(SPACE["snug"])

        row = QHBoxLayout()
        row.addWidget(QLabel("Baseline:"))
        self.combo_base = QComboBox()
        self.combo_base.setMinimumWidth(220)
        row.addWidget(self.combo_base)
        row.addWidget(QLabel("Compare with:"))
        self.combo_other = QComboBox()
        self.combo_other.setMinimumWidth(220)
        row.addWidget(self.combo_other)
        self.chk_incomparable = QCheckBox("Compare anyway")
        self.chk_incomparable.setToolTip(
            "Two runs with different datasets, splits or IoU thresholds are not a fair "
            "comparison.  Allow it only to inspect what changed, not to draw a "
            "conclusion.")
        row.addWidget(self.chk_incomparable)
        btn = QPushButton("Compare")
        btn.setObjectName("primaryAction")
        btn.clicked.connect(self.on_compare)
        row.addWidget(btn)
        row.addStretch(1)
        outer.addLayout(row)

        self.lbl_compare_warning = QLabel()
        self.lbl_compare_warning.setObjectName("compareWarning")
        self.lbl_compare_warning.setWordWrap(True)
        self.lbl_compare_warning.setVisible(False)
        outer.addWidget(self.lbl_compare_warning)

        outer.addWidget(_section("Metrics"))
        self.table_compare = _table(["Metric", "Baseline", "Comparison", "Delta"])
        outer.addWidget(self.table_compare, 2)

        outer.addWidget(_section("Trade-offs"))
        self.text_compare = QTextEdit()
        self.text_compare.setReadOnly(True)
        outer.addWidget(self.text_compare, 2)
        return page

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_store_directory(self, directory: str) -> None:
        self.controller.store_directory = directory
        self.edit_store.setText(directory)
        self._refresh_experiments()

    def set_active_solution(self, solution) -> None:
        """Remember the workspace's solution so it can be evaluated as a workflow."""
        self._active_solution = solution

    def load_dataset_path(self, path: str) -> bool:
        try:
            dataset = self.controller.load_dataset(path)
        except (FileNotFoundError, ValueError) as exc:
            self.controller.last_error = str(exc)
            QMessageBox.warning(self, "Dataset", str(exc))
            return False
        self.edit_dataset.setText(path)
        summary = self.controller.dataset_summary()
        self.lbl_dataset_summary.setText(
            f"<b>{summary['name']}</b> &middot; {summary['images']} images "
            f"({summary['empty_images']} with no ground truth) &middot; "
            f"{summary['annotations']} annotations &middot; "
            f"split <b>{summary['split']}</b><br>"
            f"classes: {', '.join(summary['classes']) or '(none)'}"
            + (f"<br>generator: {summary['generator']}" if summary['generator'] else ""))
        self._refresh_all()
        self.status_message.emit(f"Loaded dataset {summary['name']}")
        return True

    # ------------------------------------------------------------------
    # Slots: dataset
    # ------------------------------------------------------------------
    def on_browse_dataset(self) -> None:
        start = os.path.dirname(self.edit_dataset.text()) or os.getcwd()
        path, _ = QFileDialog.getOpenFileName(
            self, "Open dataset annotations", start, "Annotations (*.json);;All files (*)")
        if path:
            self.load_dataset_path(path)

    def on_generate_dataset(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choose a folder for the generated dataset")
        if not directory:
            return
        from vm_clone.samples.pcb_defect_dataset import build_dataset

        try:
            dataset = build_dataset(directory, count=40)
        except Exception as exc:                        # noqa: BLE001 - reported
            _error(self, "Dataset generation failed",
                                 f"{type(exc).__name__}: {exc}")
            return
        self.load_dataset_path(os.path.join(directory, "annotations.json"))
        _inform(
            self, "Dataset generated",
            f"{len(dataset)} boards written to\n{directory}\n\n"
            f"{dataset.counts()['annotations']} ground-truth boxes across "
            f"{len(dataset.label_set())} classes.")

    # ------------------------------------------------------------------
    # Slots: running
    # ------------------------------------------------------------------
    def on_run(self) -> None:
        if self.controller.dataset is None:
            _inform(self, "Evaluate",
                    "Load or generate a dataset first.")
            return
        if self._thread is not None:
            return

        pipeline = None
        if self.combo_source.currentIndex() == 1:
            pipeline = self._active_flow()
            if pipeline is None:
                _inform(
                    self, "Evaluate",
                    "The active workspace has no flow to evaluate. "
                    "Switch to 'Reference detector', or open a workflow.")
                return

        kwargs: Dict[str, Any] = {
            "detector_variant": self.combo_variant.currentText(),
            "iou_threshold": float(self.spin_iou.value()),
            "confidence_threshold": float(self.spin_confidence.value()),
            "use_layout": self.chk_layout.isChecked(),
        }
        if pipeline is not None:
            kwargs["pipeline"] = pipeline
            kwargs["model_id"] = getattr(pipeline, "name", "workflow")

        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, max(1, len(self.controller.dataset.records)))
        self.progress.setValue(0)
        self.status_message.emit("Evaluation running...")

        self._thread = QThread(self)
        self._worker = EvaluationWorker(self.controller, kwargs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_run_finished)
        self._worker.failed.connect(self._on_run_failed)
        self._thread.start()

    def on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status_message.emit("Cancelling...")

    def _on_progress(self, index: int, total: int, path: str) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(index)
        self.progress.setFormat(f"%v / {total}  %p%")

    def _on_run_finished(self, _outcome) -> None:
        self._finish_run()
        self._refresh_all()
        self.tabs.setCurrentIndex(1)          # Results
        result = self.controller.outcome.result
        self.status_message.emit(
            f"Evaluated {result.images_evaluated} images: "
            f"precision {'n/a' if result.precision is None else f'{result.precision:.3f}'}, "
            f"recall {'n/a' if result.recall is None else f'{result.recall:.3f}'}, "
            f"{result.errors and f'{len(result.errors)} error(s)' or 'no errors'}")

    def _on_run_failed(self, message: str) -> None:
        self._finish_run()
        self.status_message.emit("Evaluation failed")
        _error(self, "Evaluation failed", message)

    def _finish_run(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread = None
        self._worker = None
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)

    def _active_flow(self):
        """The pipeline currently shown in the workspace, if any."""
        if self._active_solution is None:
            return None
        try:
            return self._active_solution.get_active_flow()
        except Exception:                               # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Slots: results and experiments
    # ------------------------------------------------------------------
    def on_save_experiment(self) -> None:
        if self.controller.outcome is None:
            return
        if not self.controller.store_directory:
            self.on_choose_store()
            if not self.controller.store_directory:
                return
        name = self.edit_name.text().strip()
        try:
            experiment = self.controller.save_experiment(
                name=name, pipeline=self._active_flow())
        except Exception as exc:                        # noqa: BLE001 - reported
            _error(self, "Save experiment",
                                 f"{type(exc).__name__}: {exc}")
            return
        self._refresh_experiments()
        self.status_message.emit(f"Saved experiment '{experiment.name}'")
        _inform(
            self, "Experiment saved",
            f"'{experiment.name}' recorded.\n\n"
            f"Existing records are never overwritten, so this run keeps its own file "
            f"under\n{self.controller.store_directory}")

    def on_copy_report(self) -> None:
        if self.controller.outcome is None:
            return
        from vm_clone.evaluation import render_text_report

        text = render_text_report(self.controller.outcome.result)
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self.status_message.emit("Text report copied to the clipboard")

    def on_choose_store(self) -> None:
        # A modal folder chooser blocks until a person picks one, so it is skipped when
        # running headless - the caller (usually `on_save_experiment`) then reports that
        # no store is configured instead of hanging.
        if os.environ.get("APEX_HEADLESS_UI") == "1":
            self.status_message.emit("No experiment store configured")
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Choose an experiment store folder",
            self.controller.store_directory or os.getcwd())
        if directory:
            self.set_store_directory(directory)

    def _on_store_changed(self) -> None:
        self.controller.store_directory = self.edit_store.text().strip()
        self._refresh_experiments()

    def on_open_original(self) -> None:
        case = self.failure_list.selected_case()
        if case is None:
            return
        import subprocess
        import sys

        if not os.path.exists(case.image_path):
            QMessageBox.warning(self, "Open image",
                                f"Not found:\n{case.image_path}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(case.image_path)            # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", case.image_path])
            else:
                subprocess.Popen(["xdg-open", case.image_path])
        except Exception as exc:                        # noqa: BLE001 - reported
            QMessageBox.warning(self, "Open image",
                                f"Could not open the image:\n{exc}")

    def on_export_failures(self) -> None:
        cases = self._visible_failures()
        if not cases:
            _inform(self, "Export failures",
                    "No failures match the current filters.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export failure cases", "failures.json",
            "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                import csv

                with open(path, "w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(["image", "kind", "class", "confidence", "iou",
                                     "reason", "x", "y", "w", "h"])
                    for case in cases:
                        writer.writerow([
                            case.image, case.kind, case.label,
                            "" if case.score is None else f"{case.score:.6f}",
                            f"{case.best_iou:.6f}", case.reason_code,
                            *[f"{v:.2f}" for v in case.box]])
            else:
                from vm_clone.core.fileio import atomic_write_json

                atomic_write_json(path, {
                    "dataset": self.controller.dataset_summary(),
                    "iou_threshold": (self.controller.outcome.result.iou_threshold
                                      if self.controller.outcome else None),
                    "count": len(cases),
                    "failures": [{
                        "image": c.image, "kind": c.kind, "class": c.label,
                        "confidence": c.score, "iou": c.best_iou,
                        "reason_code": c.reason_code, "reason": c.reason,
                        "box": list(c.box), "nearest_label": c.nearest_label,
                    } for c in cases],
                })
        except OSError as exc:
            _error(self, "Export failures", f"Could not write:\n{exc}")
            return
        self.status_message.emit(f"Exported {len(cases)} failure case(s)")

    def on_compare(self) -> None:
        experiments = self.controller.list_experiments()
        base_index = self.combo_base.currentIndex()
        other_index = self.combo_other.currentIndex()
        if base_index < 0 or other_index < 0 or base_index == other_index:
            _inform(self, "Compare",
                    "Choose two different experiments to compare.")
            return
        chosen = [experiments[base_index], experiments[other_index]]
        try:
            comparison = self.controller.compare_experiments(
                chosen, base_index=0,
                allow_incomparable=self.chk_incomparable.isChecked())
        except Exception as exc:                        # noqa: BLE001 - reported
            self.lbl_compare_warning.setText(str(exc))
            self.lbl_compare_warning.setVisible(True)
            self.table_compare.setRowCount(0)
            self.text_compare.setPlainText(
                "These runs are not directly comparable, so no side-by-side table is "
                "shown.  Tick 'Compare anyway' to inspect them with the caveat "
                "recorded.")
            return

        self.lbl_compare_warning.setVisible(bool(comparison.warnings))
        self.lbl_compare_warning.setText("  ".join(comparison.warnings))

        keys = ("precision", "recall", "f1", "mAP@IoU", "tp", "fp", "fn",
                "duplicates", "images_evaluated", "inference_mean_ms",
                "inference_throughput_fps")
        self.table_compare.setRowCount(len(keys))
        for row, key in enumerate(keys):
            self.table_compare.setItem(row, 0, _value_item(key))
            for col, entry in enumerate(comparison.rows, start=1):
                value = entry.metrics.get(key)
                text = "n/a" if value is None else (
                    f"{value:.4f}" if isinstance(value, float) else str(value))
                self.table_compare.setItem(row, col, _value_item(text))
            delta = comparison.rows[1].deltas.get(key) if len(comparison.rows) > 1 else None
            if delta is None:
                self.table_compare.setItem(row, 3, _muted_item("n/a"))
            else:
                item = _value_item(f"{delta:+.4f}")
                item.setForeground(QColor(THEME["text_primary"]))
                self.table_compare.setItem(row, 3, item)

        self.text_compare.setPlainText("\n".join(comparison.observations))
        self.status_message.emit("Comparison ready")

    def _on_experiment_sel(self) -> None:
        rows = self.table_experiments.selectionModel().selectedRows()
        experiments = self.controller.list_experiments()
        if not rows or rows[0].row() >= len(experiments):
            self.text_experiment.setPlainText("")
            return
        experiment = experiments[rows[0].row()]
        env = experiment.environment or {}
        software = env.get("software", {})
        hardware = env.get("hardware", {})
        lines = [
            f"name        : {experiment.name}",
            f"timestamp   : {experiment.timestamp}",
            f"status      : {experiment.status}",
            f"dataset     : {experiment.dataset_name}  split={experiment.split}",
            f"model       : {experiment.model.get('id', '')} "
            f"({experiment.model.get('kind', '')})",
            f"workflow    : {experiment.workflow.get('name', '-')} "
            f"fingerprint={experiment.workflow.get('fingerprint', '-')}",
            f"IoU         : {experiment.iou_threshold}",
            f"confidence  : {experiment.settings.get('confidence_threshold')}",
            f"working size: {experiment.settings.get('working_size')}",
            "",
            "software    : " + ", ".join(f"{k} {v}" for k, v in sorted(software.items())),
            "hardware    : " + ", ".join(f"{k}={v}" for k, v in sorted(hardware.items())),
        ]
        if experiment.errors:
            lines += ["", f"errors      : {len(experiment.errors)}"]
            for err in experiment.errors[:5]:
                lines.append(f"   {err.get('stage')}: {err.get('image')} "
                             f"{err.get('message')}")
        if experiment.notes:
            lines += ["", f"notes: {experiment.notes}"]
        self.text_experiment.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------
    def _refresh_all(self) -> None:
        self._refresh_results()
        self._refresh_failure_filters()
        self._refresh_failures()
        self._refresh_experiments()
        self.lbl_store.setText(
            f"Experiment store: {self.controller.store_directory or '(not set)'}")
        has_run = self.controller.outcome is not None
        self.btn_save.setEnabled(has_run)
        self.btn_report.setEnabled(has_run)

    def _refresh_results(self) -> None:
        # headline readout: the five numbers a reviewer reads first
        result = self.controller.outcome.result if self.controller.outcome else None

        def f(value) -> str:
            return "n/a" if value is None else f"{value:.4f}"

        if result is None:
            for label in self.metric_labels.values():
                label.setText("-")
            self.lbl_headline_note.setText("")
        else:
            self.metric_labels["Precision"].setText(f(result.precision))
            self.metric_labels["Recall"].setText(f(result.recall))
            self.metric_labels["F1"].setText(f(result.f1))
            self.metric_labels["mAP@IoU"].setText(f(result.map50))
            self.metric_labels["TP / FP / FN"].setText(
                f"{result.tp} / {result.fp} / {result.fn}")
            note = (f"{result.images_evaluated} images"
                    f" &middot; {result.gt_count} ground-truth boxes"
                    f" &middot; IoU {result.iou_threshold}")
            if result.errors:
                note += (f"<br><b>{len(result.errors)} image(s) errored</b> and are "
                         f"excluded from these counts.")
            if result.map50 is None and result.tp:
                note += ("<br>mAP is n/a: the detector produced no confidence "
                         "ranking, so there is no precision-recall curve.")
            self.lbl_headline_note.setText(note)

        metrics = self.controller.metrics_table()
        self.table_metrics.setRowCount(len(metrics))
        for row, (name, value) in enumerate(metrics):
            self.table_metrics.setItem(row, 0, _value_item(name))
            item = _muted_item(value) if value == "n/a" else _value_item(value)
            self.table_metrics.setItem(row, 1, item)

        classes = self.controller.per_class_rows()
        self.table_classes.setRowCount(len(classes))
        for row, values in enumerate(classes):
            for col, text in enumerate(values):
                item = _muted_item(text) if text == "n/a" else _value_item(text)
                self.table_classes.setItem(row, col, item)

        latency = self.controller.latency_rows()
        self.table_latency.setRowCount(len(latency))
        for row, values in enumerate(latency):
            for col, text in enumerate(values):
                self.table_latency.setItem(row, col, _value_item(text))

        errors = self.controller.error_rows()
        self.table_errors.setRowCount(len(errors))
        for row, values in enumerate(errors):
            for col, text in enumerate(values):
                self.table_errors.setItem(row, col, _value_item(text))

    def _refresh_failure_filters(self) -> None:
        for combo, values in ((self.combo_class, self.controller.available_labels()),
                              (self.combo_image, self.controller.annotated_images),
                              (self.combo_reason,
                               [code for code, _ in
                                self.controller.available_reasons()])):
            previous = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("all")
            combo.addItems(values)
            index = combo.findText(previous)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _selected_kinds(self) -> List[str]:
        kinds = []
        if self.chk_fp.isChecked():
            kinds.append(FP)
        if self.chk_fn.isChecked():
            kinds.append(FN)
        if self.chk_dup.isChecked():
            kinds.append(DUPLICATE)
        return kinds

    def _visible_failures(self) -> List[FailureCase]:
        kinds = self._selected_kinds()
        label = self.combo_class.currentText()
        image = self.combo_image.currentText()
        reason = self.combo_reason.currentText()
        return filter_failures(
            self.controller.failures,
            kinds=kinds,
            labels=None if label == "all" else [label],
            image=None if image == "all" else image,
            reason_codes=None if reason == "all" else [reason],
            min_score=float(self.spin_min_score.value()) or None)

    def _refresh_failures(self) -> None:
        cases = self._visible_failures()
        selected = self.failure_list.selected_case()
        self.failure_list.set_cases(cases)
        summary = failure_summary(cases)
        if not self.controller.failures:
            self.lbl_failure_summary.setText("Run an evaluation to list failures.")
        else:
            by_kind = summary["by_kind"]
            self.lbl_failure_summary.setText(
                f"<b>{summary['total']}</b> shown of "
                f"{len(self.controller.failures)} total &middot; "
                f"false positives {by_kind.get(FP, 0)} &middot; "
                f"missed defects {by_kind.get(FN, 0)} &middot; "
                f"duplicates {by_kind.get(DUPLICATE, 0)}")
        # keep the selection if that case is still visible
        if selected is not None:
            for index in range(self.failure_list.flat_count()):
                self.failure_list.select_case(index)
                if self.failure_list.selected_case() is selected:
                    break
        self._render_selected_case()

    def _step_case(self, delta: int) -> None:
        current = self.failure_list.current_flat_index()
        total = self.failure_list.flat_count()
        if total == 0:
            return
        self.failure_list.select_case((current + delta) % total)

    def _on_detail_toggled(self, shown: bool) -> None:
        self.text_case_detail.setVisible(shown)
        self.btn_detail.setText("Hide case detail" if shown else "Show case detail")

    def _on_case_selected(self, _case) -> None:
        self._render_selected_case()

    def _render_selected_case(self) -> None:
        case = self.failure_list.selected_case()
        if case is None or self.controller.outcome is None:
            self.failure_image.show_placeholder(
                "Select a failure to see the image with its ground truth and "
                "predictions.")
            self.text_case_detail.setPlainText("")
            return
        match = next((m for m in self.controller.outcome.result.per_image
                      if m.image == case.image), None)
        error = self.failure_image.show_case(
            case.image_path, match, case,
            show_ground_truth=self.chk_show_gt.isChecked(),
            show_predictions=self.chk_show_pred.isChecked())
        if error:
            self.status_message.emit(error)

        kind = _KIND_LABELS.get(case.kind, case.kind)
        detail = [
            f"{kind}  -  class '{case.label}'",
            f"reason      : {case.reason}",
            f"box (x,y,w,h): {tuple(round(v, 1) for v in case.box)}",
        ]
        if case.score is not None:
            detail.append(f"confidence  : {case.score:.4f}")
        else:
            detail.append("confidence  : n/a (ground-truth annotation)")
        detail.append(f"best IoU    : {case.best_iou:.4f}")
        if case.nearest_label:
            detail.append(f"nearest GT class: {case.nearest_label}")
        detail.append(f"image       : {case.image_path}")
        self.text_case_detail.setPlainText("\n".join(detail))

    def _refresh_experiments(self) -> None:
        experiments = self.controller.list_experiments()
        self.table_experiments.setRowCount(len(experiments))
        for row, exp in enumerate(experiments):
            def f(value):
                return "n/a" if value is None else f"{value:.4f}"
            values = [exp.timestamp, exp.name, exp.dataset_name, exp.split,
                      str(exp.iou_threshold), str(exp.settings.get(
                          "confidence_threshold", "")),
                      f(exp.precision), f(exp.recall), f(exp.f1),
                      str(exp.fp), str(exp.fn), exp.status]
            for col, text in enumerate(values):
                item = _muted_item(text) if text == "n/a" else _value_item(text)
                self.table_experiments.setItem(row, col, item)

        names = [f"{e.timestamp[:19]}  {e.name[:28]}" for e in experiments]
        for combo in (self.combo_base, self.combo_other):
            previous = combo.currentIndex()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if previous >= 0:
                combo.setCurrentIndex(min(previous, max(0, len(names) - 1)))
            combo.blockSignals(False)
        if len(names) >= 2:
            self.combo_base.setCurrentIndex(0)
            self.combo_other.setCurrentIndex(1)
        self.text_experiment.setPlainText(
            "Select a record to see its full configuration and environment."
            if names else "No experiments recorded yet.  Run an evaluation and use "
                          "'Save experiment'.")
