"""Section navigation with one smoothly moving, full-row selection highlight."""
from PySide6.QtCore import Qt, QRectF, QVariantAnimation, QEasingCurve, QPointF
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QTreeWidget, QStyledItemDelegate, QStyleOptionViewItem, QStyle


class SectionDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        clean = QStyleOptionViewItem(option)
        clean.state &= ~(QStyle.State_Selected | QStyle.State_HasFocus | QStyle.State_MouseOver)
        super().paint(painter, clean, index)


class SectionTree(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('sectionNavigation')
        self.setItemDelegate(SectionDelegate(self))
        self.setAnimated(True)
        self.setMouseTracking(True)
        self._highlight = QRectF()
        self._start = QRectF()
        self._target = QRectF()
        self._motion = QVariantAnimation(self)
        self._motion.setDuration(190)
        self._motion.setStartValue(0.0); self._motion.setEndValue(1.0)
        self._motion.setEasingCurve(QEasingCurve.OutCubic)
        self._motion.valueChanged.connect(self._advance)
        self.setStyleSheet('''
            QTreeWidget#sectionNavigation {
                selection-background-color: transparent;
                selection-color: #25262b;
                show-decoration-selected: 0;
            }
            QTreeWidget#sectionNavigation::item,
            QTreeWidget#sectionNavigation::item:selected,
            QTreeWidget#sectionNavigation::item:hover,
            QTreeWidget#sectionNavigation::branch,
            QTreeWidget#sectionNavigation::branch:selected,
            QTreeWidget#sectionNavigation::branch:hover {
                background: transparent; border: none;
            }
        ''')

    def _row_rect(self, index):
        rect = self.visualRect(index)
        if not rect.isValid(): return QRectF()
        return QRectF(2, rect.y() + 1, max(0, self.viewport().width() - 4), max(0, rect.height() - 2))

    def currentChanged(self, current, previous):
        super().currentChanged(current, previous)
        if not hasattr(self, '_motion'): return
        self._motion.stop()
        target = self._row_rect(current)
        if self._highlight.isEmpty() or not previous.isValid() or not self.isVisible() or self.signalsBlocked():
            self._highlight = target; self.viewport().update(); return
        self._start = QRectF(self._highlight); self._target = target
        self._motion.start()

    def _advance(self, progress):
        a, b = self._start, self._target
        self._highlight = QRectF(a.x() + (b.x()-a.x())*progress,
                                a.y() + (b.y()-a.y())*progress,
                                a.width() + (b.width()-a.width())*progress,
                                a.height() + (b.height()-a.height())*progress)
        self.viewport().update()

    def drawRow(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        # Qt draws the branch separately. Paint a single pill across both areas.
        row = self._row_rect(index)
        painter.setClipRect(QRectF(0, option.rect.y(), self.viewport().width(), option.rect.height()))
        painter.setPen(Qt.NoPen)
        selected = self.selectionModel().isSelected(index)
        if selected and index != self.currentIndex():
            painter.setBrush(QColor('#e0e8f5')); painter.drawRoundedRect(row, 7, 7)
        if self.selectionModel().isSelected(self.currentIndex()):
            rect = self._highlight if self._motion.state() == QVariantAnimation.Running else self._row_rect(self.currentIndex())
            painter.setBrush(QColor('#dce7f8')); painter.drawRoundedRect(rect, 7, 7)
        painter.restore()
        clean = QStyleOptionViewItem(option)
        clean.state &= ~(QStyle.State_Selected | QStyle.State_HasFocus | QStyle.State_MouseOver)
        super().drawRow(painter, clean, index)

    def scrollContentsBy(self, dx, dy):
        if hasattr(self, '_motion'):
            self._motion.stop()
            self._highlight = self._row_rect(self.currentIndex())
        super().scrollContentsBy(dx, dy)

    def drawBranches(self, painter, rect, index):
        # Native Linux styles can paint a blue selection block in the indentation.
        # Keep Qt's expand/collapse hit testing, but draw only the disclosure arrow.
        if not self.model().hasChildren(index): return
        x, y = rect.right() - self.indentation() / 2, rect.center().y()
        points = ([QPointF(x-3, y-2), QPointF(x+3, y-2), QPointF(x, y+2)]
                  if self.isExpanded(index) else
                  [QPointF(x-2, y-3), QPointF(x+2, y), QPointF(x-2, y+3)])
        painter.save(); painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen); painter.setBrush(QColor('#777b85'))
        painter.drawPolygon(QPolygonF(points)); painter.restore()

    def clear(self):
        if hasattr(self, '_motion'):
            self._motion.stop(); self._highlight = QRectF()
        super().clear()
