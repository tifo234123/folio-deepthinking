"""Native Qt desktop client. No browser, web server, or hosted UI."""
import html
import json
import queue
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

import pymupdf
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap, QLinearGradient, QShortcut, QKeySequence, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
    QSplitter, QStackedWidget, QScrollArea, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QLabel, QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox,
    QCheckBox, QTabWidget, QDialog, QDialogButtonBox, QInputDialog, QFileDialog,
    QMessageBox, QProgressBar, QMenu, QGraphicsDropShadowEffect, QSizePolicy, QSizeGrip,
)
from .app import App
from .config import PROVIDERS
from .providers import Provider
from .cli import export_book
from .theme import LIGHT, DARK, button, label, row, icon
from .settings_ui import SettingsWindow
from .section_tree import SectionTree
from .reading_ui import refresh_reading, deep_read_dialog
from .section_reader import SectionReader


def layout_frame(name="", margin=0, spacing=10):
    widget = QFrame(); widget.setObjectName(name)
    layout = QVBoxLayout(widget); layout.setContentsMargins(margin, margin, margin, margin); layout.setSpacing(spacing)
    return widget, layout


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget(): item.widget().deleteLater()
        elif item.layout(): clear_layout(item.layout())


def scroll_content(name="", margin=0):
    scroll = QScrollArea(); scroll.setWidgetResizable(True)
    widget, layout = layout_frame(name, margin)
    scroll.setWidget(widget)
    return scroll, layout


class Titlebar(QFrame):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        window = self.window()
        window.showNormal() if window.isMaximized() else window.showMaximized()


class Desktop(QMainWindow):
    def __init__(self, app, owns_app=True):
        super().__init__()
        self.app, self.owns_app = app, owns_app
        self.book_id = self.section_id = self.source_id = None
        self.note_id, self.note_baseline = None, ""
        self.events = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="folio-ui")
        self.chat_busy = False
        self.pending_tasks = 0
        self.closed = self.ready_to_close = False
        self.job_signature = self.book_signature = None
        self.structure_rows, self.source_rows = [], []
        self.cover_cache = {}
        self.dialogs = []
        self.setWindowTitle("Folio Deepthinking — Research Library")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "static" / "folio.svg")))
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1500, 940); self.setMinimumSize(1180, 760)
        self.setStyleSheet(LIGHT)
        self.build()
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(200)
        self.refresh_books(force=True)
        self.show_library(initial=True)
        previous = app.db.one("SELECT value FROM ui_state WHERE key='last_book'")
        section = app.db.one("SELECT value FROM ui_state WHERE key='last_section'")
        if previous and app.db.one("SELECT id FROM books WHERE id=?", (previous["value"],)):
            self.select_book(previous["value"])
            if section and section["value"]:
                self.select_section(section["value"])
        if not app.config.get().model: QTimer.singleShot(650, self.settings)

    def build(self):
        outer, outer_layout = layout_frame(margin=10, spacing=0)
        self.setCentralWidget(outer)
        window, shell = layout_frame("window", 0, 0); outer_layout.addWidget(window)
        shadow = QGraphicsDropShadowEffect(self); shadow.setBlurRadius(23); shadow.setOffset(0, 5); shadow.setColor(QColor(0, 0, 0, 35)); window.setGraphicsEffect(shadow)
        titlebar = Titlebar(); titlebar.setObjectName("titlebar"); titlebar.setFixedHeight(50)
        tl = QHBoxLayout(titlebar); tl.setContentsMargins(18, 0, 18, 0); tl.setSpacing(9)
        for color, tip, action in [("#ff6059", "Close", self.close), ("#ffbd2e", "Minimize", self.showMinimized), ("#28c840", "Maximize / restore", self.toggle_maximize)]:
            b = button(callback=action); b.setFixedSize(13, 13); b.setToolTip(tip)
            b.setStyleSheet(f"QPushButton {{ background:{color}; border:1px solid rgba(0,0,0,25); border-radius:6px; padding:0; min-height:0; }} QPushButton:hover {{ border:1px solid #777; }}")
            tl.addWidget(b)
        tl.addSpacing(18); tl.addWidget(label("Folio Deepthinking", "brand")); tl.addWidget(label("Research Library", "muted")); tl.addStretch()
        self.connection_label = label("Local workspace", "muted"); tl.addWidget(self.connection_label)
        tl.addWidget(button(name="settings", quiet=True, callback=self.settings))
        shell.addWidget(titlebar)
        split = QSplitter(Qt.Horizontal); split.setChildrenCollapsible(False); split.setHandleWidth(1)
        shell.addWidget(split, 1)
        sidebar, left = layout_frame("sidebar", 18, 9); sidebar.setMinimumWidth(205); sidebar.setMaximumWidth(370)
        split.addWidget(sidebar)
        self.filter = QLineEdit(); self.filter.setObjectName("search"); self.filter.setPlaceholderText("Search your library")
        self.filter.addAction(icon("search", size=16), QLineEdit.LeadingPosition)
        self.filter.textChanged.connect(lambda: self.refresh_books(force=True)); left.addWidget(self.filter)
        left.addSpacing(12); left.addWidget(label("LIBRARY", "eyebrow"))
        self.library_button = button("All books", "library", callback=self.show_library); self.library_button.setObjectName("nav"); self.library_button.setCheckable(True); left.addWidget(self.library_button)
        self.subject = QComboBox(); self.subject.addItem("All subjects", None); self.subject.currentIndexChanged.connect(lambda: self.refresh_books(force=True)); left.addWidget(self.subject)
        left.addWidget(button("Assign book subjects…", "folder", quiet=True, callback=self.edit_subjects))
        self.books_tree = QTreeWidget(); self.books_tree.setHeaderHidden(True); self.books_tree.setRootIsDecorated(False)
        self.books_tree.itemClicked.connect(lambda item: self.select_book(item.data(0, Qt.UserRole)))
        left.addWidget(self.books_tree, 2)
        section_header = row(label("SECTIONS", "eyebrow"), None, button(name="grid", quiet=True, callback=self.structure_menu)); left.addWidget(section_header)
        self.sections_tree = SectionTree(); self.sections_tree.setHeaderHidden(True)
        self.sections_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.sections_tree.itemSelectionChanged.connect(self.on_section)
        left.addWidget(self.sections_tree, 3)
        left.addWidget(button("Import PDFs", "plus", callback=self.import_files))
        left.addWidget(button("Library options", "folder", quiet=True, callback=self.library_menu))
        left.addWidget(label("Stored on this computer", "muted"))

        main, main_layout = layout_frame(spacing=0); main.setMinimumWidth(570); split.addWidget(main)
        toolbar = row(button(name="back", quiet=True, callback=self.show_library), label("Library", "muted"), label("/", "muted"), label("Research workspace", "muted"), None,
                      button("Import", "plus", callback=self.import_files), margins=14)
        toolbar.setObjectName("toolbar"); main_layout.addWidget(toolbar)
        self.pages = QStackedWidget(); main_layout.addWidget(self.pages, 1)
        self.library_page, self.library_layout = layout_frame(margin=28, spacing=16); self.pages.addWidget(self.library_page)
        self.library_heading = label("Your library", "heading")
        self.library_count = label("A place for everything you want to understand.", "muted")
        self.library_layout.addWidget(self.library_heading); self.library_layout.addWidget(self.library_count)
        self.library_layout.addWidget(row(label("Books", "subheading"), None, label("Recently added", "muted")))
        self.book_scroll, self.book_grid_container = scroll_content(); self.library_layout.addWidget(self.book_scroll, 1)
        self.book_grid = QGridLayout(); self.book_grid.setSpacing(20); self.book_grid_container.addLayout(self.book_grid)
        self.book_grid_container.addStretch()
        self.library_layout.addWidget(label("Every finding has a source. Your original books stay intact.", "muted", True))

        self.book_page, book_layout = layout_frame(margin=24, spacing=12); self.pages.addWidget(self.book_page)
        self.book_title = label("", "heading", True); self.book_title.setStyleSheet("font-size:22px;font-weight:700;"); self.book_meta = label("", "muted", True)
        book_layout.addWidget(self.book_title); book_layout.addWidget(self.book_meta)
        self.structure_choice = QComboBox(); self.structure_choice.setMinimumWidth(165)
        self.structure_choice.activated.connect(self.choose_structure)
        book_layout.addWidget(row(button("Reorganize book…", "grid", callback=self.reorganize_book), None))
        book_layout.addWidget(row(self.structure_choice, None, button("Original PDF", "book", callback=self.open_pdf), button("Deep read", "spark", True, self.extract)))
        self.tabs = QTabWidget(); book_layout.addWidget(self.tabs, 1)
        self.reading_page, reading_outer = layout_frame(spacing=9)
        self.tabs.addTab(self.reading_page, "Reading overview")
        self.reading_scroll, self.reading_layout = scroll_content(margin=1)
        reading_outer.addWidget(self.reading_scroll)
        self.findings_page, findings_layout = layout_frame(spacing=9)
        self.tabs.addTab(self.findings_page, "Findings")
        self.section_reader = SectionReader(self); self.tabs.addTab(self.section_reader, "Section reader")
        self.run_choice = QComboBox(); self.run_choice.addItem("All extraction runs", None); self.run_choice.activated.connect(lambda: self.refresh_findings())
        self.finding_category = QComboBox()
        for title, key in [('All finding types', None), ('Arguments & ideas', 'main'), ('Definitions', 'definition'), ('Methods', 'method'), ('Formulas', 'formula'), ('Data & results', 'data')]:
            self.finding_category.addItem(title, key)
        self.finding_category.activated.connect(lambda: self.refresh_findings())
        findings_layout.addWidget(row(self.run_choice, self.finding_category))
        self.findings_scroll, self.findings_layout = scroll_content(margin=1); findings_layout.addWidget(self.findings_scroll, 1)

        sources_page, sources_layout = layout_frame(spacing=8); self.tabs.addTab(sources_page, "Sources")
        self.source_query = QLineEdit(); self.source_query.setPlaceholderText("Find a term, formula, or topic in this book")
        self.source_query.returnPressed.connect(self.search_sources)
        sources_layout.addWidget(row(self.source_query, button("Search", "search", callback=self.search_sources)))
        self.sources_tree = QTreeWidget(); self.sources_tree.setHeaderLabels(["Passage", "PDF page"]); self.sources_tree.setRootIsDecorated(False)
        self.sources_tree.setColumnWidth(0, 380); self.sources_tree.itemSelectionChanged.connect(self.on_source)
        sources_layout.addWidget(self.sources_tree, 2)
        self.source_text = QTextBrowser(); self.source_text.setOpenExternalLinks(False); sources_layout.addWidget(self.source_text, 3)
        sources_layout.addWidget(row(label("Original text · verify layout in the PDF", "muted"), None, button("View page", "arrow", callback=self.open_pdf)))

        notes_page, notes_layout = layout_frame(spacing=9); self.tabs.addTab(notes_page, "My notes")
        self.notes_list = QListWidget(); self.notes_list.setMaximumHeight(145); self.notes_list.itemClicked.connect(self.on_note); notes_layout.addWidget(self.notes_list)
        self.note_text = QPlainTextEdit(); self.note_text.setPlaceholderText("Your observations, questions, and research notes…"); notes_layout.addWidget(self.note_text, 1)
        notes_layout.addWidget(row(button("New note", "plus", callback=self.new_note), None, button("Save note", "check", True, self.save_note)))
        notes_layout.addWidget(label("Personal notes are preserved when findings are regenerated.", "muted", True))

        assistant, right = layout_frame("assistant", 19, 12); assistant.setMinimumWidth(305); assistant.setMaximumWidth(430); split.addWidget(assistant)
        heading_icon = label(""); heading_icon.setPixmap(icon("spark", "#4785f5", 22).pixmap(22, 22))
        right.addWidget(row(heading_icon, label("Assistant", "subheading"), None, label("Always here", "muted")))
        self.context_label = label("Your library", "context", True); right.addWidget(self.context_label)
        self.whole_book = QCheckBox("Use the whole book"); right.addWidget(self.whole_book)
        self.chat_scroll, self.chat_layout = scroll_content(); right.addWidget(self.chat_scroll, 1)
        composer, composer_layout = layout_frame("composer", 10, 4)
        self.chat_input = QPlainTextEdit(); self.chat_input.setPlaceholderText("Ask a question or give an instruction…"); self.chat_input.setFixedHeight(90)
        self.chat_input.setStyleSheet("QPlainTextEdit { border:none; padding:4px; background:transparent; }")
        composer_layout.addWidget(self.chat_input)
        self.send = button("Send", "send", True, self.ask)
        composer_layout.addWidget(row(label("Ctrl ↵ to send", "muted"), None, self.send)); right.addWidget(composer)
        right.addWidget(label("Grounded in your sources. Changes stay under your control.", "muted", True))
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.ask)
        split.setSizes([285, 825, 365]); split.setStretchFactor(0, 0); split.setStretchFactor(1, 1); split.setStretchFactor(2, 0)

        self.status_label = label("Ready · Your library is saved locally", "muted"); self.status_label.setMinimumWidth(0)
        self.progress = QProgressBar(); self.progress.setFixedWidth(110); self.progress.setTextVisible(False); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.jobs_button = button("Background work", "clock", quiet=True, callback=self.show_jobs)
        jobbar = row(self.status_label, None, self.progress, self.jobs_button, QSizeGrip(self), margins=12); jobbar.setObjectName("jobbar"); shell.addWidget(jobbar)

    def toggle_maximize(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def status(self, text):
        self.status_label.setText(text[:140]); self.status_label.setToolTip(text)

    def error(self, text):
        self.status(text); QMessageBox.warning(self, "Folio", text)

    def run(self, text, work, done=lambda result: None):
        self.status(text)
        self.pending_tasks += 1
        def complete(outcome):
            self.pending_tasks -= 1
            result, error = outcome
            if error: self.error(error)
            else: done(result)
        def task():
            try: outcome = work(), None
            except Exception as exc: outcome = None, str(exc)
            self.events.put((complete, outcome, None))
        self.pool.submit(task)

    def tick(self):
        if self.closed: return
        while not self.events.empty():
            callback, result, error = self.events.get()
            if error: self.error(error)
            elif callback:
                try: callback(result)
                except Exception as exc: self.error(str(exc))
        if self.closed: return
        self.refresh_books()
        self.refresh_jobs()
        s = self.app.config.get()
        self.connection_label.setText(PROVIDERS[s.provider][0] + (" · " + s.model if s.model else " · Not configured"))

    def require_book(self):
        if self.book_id: return True
        self.status("Open a book in your library first."); return False

    def cover(self, book):
        if book["id"] in self.cover_cache: return self.cover_cache[book["id"]]
        pixmap = QPixmap(300, 360); pixmap.fill(Qt.white)
        try:
            with pymupdf.open(book["path"]) as d:
                p = d[0].get_pixmap(matrix=pymupdf.Matrix(.6, .6), alpha=False)
                image = QImage(p.samples, p.width, p.height, p.stride, QImage.Format_RGB888).copy()
                pixmap = QPixmap.fromImage(image).scaled(300, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            painter = QPainter(pixmap)
            gradient = QLinearGradient(0, 0, 300, 360); gradient.setColorAt(0, QColor("#7693b7")); gradient.setColorAt(1, QColor("#263b5b"))
            painter.fillRect(pixmap.rect(), gradient); painter.setPen(QColor("#ffffff")); painter.setFont(QFont("Noto Sans", 20))
            painter.drawText(pixmap.rect().adjusted(20, 20, -20, -20), Qt.AlignLeft | Qt.AlignBottom | Qt.TextWordWrap, book["title"]); painter.end()
        self.cover_cache[book["id"]] = pixmap
        return pixmap

    def refresh_books(self, force=False):
        books = self.app.library.books(self.filter.text(), self.subject.currentData())
        signature = [(b["id"], b["title"], b["status"], b["subjects"]) for b in books]
        if signature == self.book_signature and not force: return
        self.book_signature = signature
        self.books_tree.blockSignals(True); self.books_tree.clear()
        for b in books:
            item = QTreeWidgetItem([b["title"]]); item.setIcon(0, icon("book")); item.setData(0, Qt.UserRole, b["id"]); item.setToolTip(0, b["status"].replace("_", " ")); self.books_tree.addTopLevelItem(item)
            if b["id"] == self.book_id: self.books_tree.setCurrentItem(item)
        self.books_tree.blockSignals(False)
        selected = self.subject.currentData()
        self.subject.blockSignals(True); self.subject.clear(); self.subject.addItem("All subjects", None)
        for s in self.app.db.rows("SELECT * FROM subjects ORDER BY name"): self.subject.addItem(s["name"], s["id"])
        self.subject.setCurrentIndex(max(0, self.subject.findData(selected))); self.subject.blockSignals(False)
        self.library_count.setText(f"{len(books)} {'book' if len(books) == 1 else 'books'}  ·  Saved locally  ·  Ready when you are")
        clear_layout(self.book_grid)
        if not books:
            empty, layout = layout_frame("subtle", 28, 14)
            art = label(""); art.setPixmap(icon("book", "#8da4c6", 52).pixmap(52, 52)); layout.addWidget(art)
            layout.addWidget(label("Make room for your next discovery.", "subheading", True))
            layout.addWidget(label("Bring your books together. Explore their ideas, collect useful findings, and return to the original source whenever you need it.", "muted", True))
            layout.addWidget(row(button("Import your first PDF", "plus", True, self.import_files), None))
            layout.addWidget(label("PDF books · Local storage · Your choice of AI", "muted", True))
            self.book_grid.addWidget(empty, 0, 0, 1, 3)
        for index, b in enumerate(books):
            card, content = layout_frame(margin=0, spacing=7)
            cover = button(callback=lambda checked=False, bid=b["id"]: self.select_book(bid))
            cover.setMinimumSize(150, 180); cover.setMaximumHeight(205)
            cover.setIcon(self.cover(b)); cover.setIconSize(QSize(150, 180)); cover.setStyleSheet("QPushButton { border:1px solid #e5e5eb; border-radius:9px; background:#f4f4f7; padding:8px; }")
            content.addWidget(cover)
            title = label(b["title"], wrap=True); title.setStyleSheet("font-weight:600;font-size:13px;"); content.addWidget(title)
            content.addWidget(label(b["author"] or b["filename"], "muted", True))
            content.addWidget(label(f"{b['page_count']} pages  ·  {b['status'].replace('_', ' ')}", "muted", True))
            self.book_grid.addWidget(card, index // 3, index % 3, alignment=Qt.AlignTop)
        for col in range(3): self.book_grid.setColumnStretch(col, 1)

    def show_library(self, initial=False):
        if not initial and not self.guard_note(): return
        self.book_id = self.section_id = self.source_id = None
        self.library_button.setChecked(True)
        self.pages.setCurrentWidget(self.library_page)
        self.sections_tree.blockSignals(True); self.sections_tree.clear(); self.sections_tree.blockSignals(False)
        self.context_label.setText("Your library")
        self.whole_book.setEnabled(False)
        if not initial: self.app.db.execute("DELETE FROM ui_state WHERE key='last_book'")
        self.refresh_chat()

    def select_book(self, book_id):
        if self.book_id == book_id and self.pages.currentWidget() == self.book_page: return
        if not self.guard_note(): return
        self.book_id, self.section_id, self.source_id = book_id, None, None
        self.new_note(force=True)
        self.library_button.setChecked(False); self.whole_book.setEnabled(True)
        self.pages.setCurrentWidget(self.book_page)
        self.app.db.execute("INSERT OR REPLACE INTO ui_state VALUES('last_book',?)", (book_id,))
        self.refresh_workspace(); self.refresh_chat()

    def refresh_workspace(self):
        if not self.book_id: return
        b = self.app.library.book(self.book_id)
        self.book_title.setText(b["title"])
        warnings = len(json.loads(b["warnings"]))
        self.book_meta.setText(f"{b['author'] or 'Author unspecified'}  ·  {b['page_count']} pages  ·  {b['status'].replace('_',' ')}" + (f"  ·  {warnings} pages have layout flags" if warnings else ""))
        self.book_meta.setToolTip(b["error"] or "")
        subjects = self.app.db.rows("SELECT s.name FROM subjects s JOIN book_subjects bs ON bs.subject_id=s.id WHERE bs.book_id=? ORDER BY s.name", (self.book_id,))
        if subjects: self.book_meta.setText(self.book_meta.text() + "  ·  " + ", ".join(s["name"] for s in subjects))
        self.structure_rows = self.app.db.rows("SELECT * FROM structures WHERE book_id=? ORDER BY created", (self.book_id,))
        self.structure_choice.blockSignals(True); self.structure_choice.clear()
        for s in self.structure_rows: self.structure_choice.addItem(s["name"] + (" · Preview" if not s["applied"] else ""), s["id"])
        self.structure_choice.setCurrentIndex(self.structure_choice.findData(b["active_structure"])); self.structure_choice.blockSignals(False)
        self.sections_tree.blockSignals(True); self.sections_tree.clear()
        all_item = QTreeWidgetItem(["Whole book"]); all_item.setData(0, Qt.UserRole, ""); all_item.setIcon(0, icon("book")); self.sections_tree.addTopLevelItem(all_item)
        items = {}
        for s in self.app.library.sections(self.book_id):
            item = QTreeWidgetItem([s["title"]]); item.setData(0, Qt.UserRole, s["id"]); item.setIcon(0, icon("file", size=16))
            item.setToolTip(0, f"{s['title']}\n{s['origin']}\nPDF pages: {', '.join(map(str,s['pages']))}")
            parent = items.get(s["parent_id"])
            parent.addChild(item) if parent else self.sections_tree.addTopLevelItem(item)
            items[s["id"]] = item
        if self.section_id not in items: self.section_id = None
        self.sections_tree.setCurrentItem(items.get(self.section_id, all_item)); self.sections_tree.expandAll(); self.sections_tree.blockSignals(False)
        self.refresh_findings(); self.refresh_reading(); self.refresh_sources(); self.refresh_notes(); self.update_context()

    def select_section(self, section_id):
        def visit(item):
            if item.data(0, Qt.UserRole) == section_id: self.sections_tree.setCurrentItem(item); return True
            return any(visit(item.child(i)) for i in range(item.childCount()))
        for i in range(self.sections_tree.topLevelItemCount()):
            if visit(self.sections_tree.topLevelItem(i)): break

    def on_section(self):
        if not self.book_id: return
        items = self.sections_tree.selectedItems()
        self.section_id = items[0].data(0, Qt.UserRole) or None if items else None
        self.source_id = None
        self.app.db.execute("INSERT OR REPLACE INTO ui_state VALUES('last_section',?)", (self.section_id or "",))
        self.refresh_findings(); self.refresh_reading(); self.refresh_sources(); self.update_context()

    def update_context(self):
        if not self.book_id: return self.context_label.setText("Your library")
        title = self.app.library.book(self.book_id)["title"]
        if self.source_id:
            title += f"  ›  Passage · p. {self.app.library.source(self.book_id,self.source_id)['page']}"
        elif self.section_id:
            section = self.app.db.one("SELECT title FROM sections WHERE id=?", (self.section_id,))
            title += "  ›  " + section["title"]
        else: title += "  ›  Whole book"
        self.context_label.setText(title)

    def refresh_findings(self):
        if not self.book_id: return
        selected = self.run_choice.currentData()
        jobs = self.app.db.rows("SELECT * FROM jobs WHERE book_id=? AND kind='extract' ORDER BY created DESC", (self.book_id,))
        self.run_choice.blockSignals(True); self.run_choice.clear(); self.run_choice.addItem("All extraction runs", None)
        for j in jobs: self.run_choice.addItem(f"{j['created'][:16].replace('T',' ')} · {j['status']} · {j['id'][:6]}", j["id"])
        self.run_choice.setCurrentIndex(max(0, self.run_choice.findData(selected))); self.run_choice.blockSignals(False)
        findings = self.app.research.findings(self.book_id, self.section_id, self.run_choice.currentData())
        total_findings = len(findings)
        category = self.finding_category.currentData()
        if category: findings = [f for f in findings if f['category'] == category]
        clear_layout(self.findings_layout)
        if not findings and total_findings:
            self.findings_layout.addWidget(label('No saved findings of this type. Choose All finding types to see the other results.', 'muted', True))
        if not findings and not total_findings:
            card, layout = layout_frame("subtle", 25, 14)
            layout.addWidget(label("This scope has no saved findings yet.", "subheading", True))
            layout.addWidget(label("Extract the key ideas, definitions, formulas, and methods from this section. Each finding stays connected to the passage behind it.", "muted", True))
            layout.addWidget(row(button("Deep read this scope", "spark", True, self.extract), None))
            layout.addWidget(label("Importing preserves the source text. Deep read generates the detailed findings; Reading overview already shows source excerpts.", "muted", True))
            self.findings_layout.addWidget(card)
        for finding in findings:
            card, layout = layout_frame("card", 18, 10)
            layout.addWidget(label(finding["category"].upper(), "eyebrow"))
            layout.addWidget(label(finding["title"], "subheading", True))
            content = label(finding["content"], wrap=True); content.setTextInteractionFlags(Qt.TextSelectableByMouse); layout.addWidget(content)
            for key, value in finding["details"].items():
                detail = label(key.replace("_", " ").title() + ": " + value, wrap=True); detail.setTextInteractionFlags(Qt.TextSelectableByMouse); layout.addWidget(detail)
            sources = row()
            for e in finding["sources"]:
                source = self.app.library.source(self.book_id, e["source_id"])
                b = button(f"PDF p. {source['page']}", "file", quiet=True, callback=lambda checked=False, pid=source["id"]: self.view_source(pid))
                b.setToolTip(e["quote"]); sources.layout().addWidget(b)
                quote = label('“' + e['quote'] + '”', 'muted', True)
                quote.setTextInteractionFlags(Qt.TextSelectableByMouse); layout.addWidget(quote)
            sources.layout().addStretch(); layout.addWidget(sources)
            layout.addWidget(label(f"{finding['provider']} / {finding['model']}  ·  {finding['created'][:10]}  ·  Review interpretation", "muted", True))
            self.findings_layout.addWidget(card)
        self.findings_layout.addStretch()

    def refresh_sources(self, rows=None):
        if not self.book_id: return
        self.source_rows = rows if rows is not None else self.app.library.passages(self.book_id, self.section_id)
        self.sources_tree.blockSignals(True); self.sources_tree.clear()
        for p in self.source_rows:
            item = QTreeWidgetItem([" ".join(p["text"].split())[:150], str(p["page"])])
            item.setData(0, Qt.UserRole, p["id"]); self.sources_tree.addTopLevelItem(item)
        self.sources_tree.blockSignals(False)
        self.source_query.setPlaceholderText("Search the selected section" if self.section_id else "Search this book")
        self.source_text.setPlainText(f"{len(self.source_rows)} passages available. Select one to read it and give the assistant precise context.")

    def on_source(self):
        items = self.sources_tree.selectedItems()
        if not self.book_id or not items: return
        self.source_id = items[0].data(0, Qt.UserRole)
        source = self.app.library.source(self.book_id, self.source_id)
        p = self.app.db.one("SELECT warnings FROM pages WHERE book_id=? AND page=?", (self.book_id, source["page"]))
        warnings = json.loads(p["warnings"])
        self.source_text.setPlainText(f"PDF page {source['page']} · printed label {source['label']}\n\n{source['text']}" + ("\n\nReview notes:\n" + "\n".join(warnings) if warnings else ""))
        self.update_context()

    def search_sources(self):
        if self.require_book(): self.refresh_sources(self.app.library.search(self.book_id, self.source_query.text(), self.section_id, limit=50))

    def view_source(self, source_id):
        self.source_id = source_id; self.update_context(); self.open_pdf()

    def refresh_notes(self):
        if not self.book_id: return
        self.notes_list.clear()
        for n in self.app.db.rows("SELECT * FROM notes WHERE book_id=? ORDER BY updated DESC", (self.book_id,)):
            item = QListWidgetItem(n["text"].replace("\n", " ")[:100]); item.setData(Qt.UserRole, n["id"]); self.notes_list.addItem(item)

    def guard_note(self):
        if not self.book_id or not hasattr(self, "note_text") or self.note_text.toPlainText().strip() == self.note_baseline: return True
        choice = QMessageBox.question(self, "Unsaved note", "Save your note before leaving it?", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if choice == QMessageBox.Cancel: return False
        if choice == QMessageBox.Save:
            self.save_note(); return self.note_text.toPlainText().strip() == self.note_baseline
        return True

    def new_note(self, checked=False, force=False):
        if not force and not self.guard_note(): return
        self.note_id, self.note_baseline = None, ""; self.note_text.clear()

    def on_note(self, item):
        if item.data(Qt.UserRole) == self.note_id or not self.guard_note(): return
        n = self.app.db.one("SELECT * FROM notes WHERE id=?", (item.data(Qt.UserRole),))
        self.note_id, self.note_baseline = n["id"], n["text"]; self.note_text.setPlainText(n["text"])

    def save_note(self):
        if not self.require_book(): return
        sources = [self.source_id] if self.source_id else []
        if self.note_id: sources = json.loads(self.app.db.one("SELECT source_ids FROM notes WHERE id=?", (self.note_id,))["source_ids"])
        try:
            self.note_id = self.app.library.save_note(self.book_id, self.note_text.toPlainText().strip(), sources, self.note_id)
            self.note_baseline = self.note_text.toPlainText().strip(); self.refresh_notes(); self.status("Note saved locally.")
        except Exception as exc: self.error(str(exc))

    def import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import PDF books", "", "PDF documents (*.pdf)")
        if paths: self.import_paths(paths)

    def import_paths(self, paths):
        def work():
            results = []
            for path in paths:
                try:
                    b, created = self.app.library.import_pdf(path)
                    if created: self.app.jobs.create(b["id"], "prepare")
                    results.append({"book_id": b["id"], "created": created})
                except Exception as exc: results.append({"error": f"{Path(path).name}: {exc}"})
            return results
        def done(results):
            self.refresh_books(force=True)
            errors = [r["error"] for r in results if "error" in r]
            self.status(f"{sum(r.get('created',False) for r in results)} new books imported. Preparation runs in the background.")
            if errors: self.error("\n".join(errors))
        self.run("Copying PDFs into your library…", work, done)

    def prepare(self):
        if not self.require_book(): return
        try: self.app.jobs.create(self.book_id, "prepare")
        except Exception as exc: self.error(str(exc))

    def refresh_reading(self):
        refresh_reading(self)
        if self.book_id: self.section_reader.set_scope(self.book_id, self.section_id)

    def extract(self):
        deep_read_dialog(self)

    def refresh_jobs(self):
        jobs = self.app.db.rows("SELECT j.*,b.title FROM jobs j JOIN books b ON b.id=j.book_id ORDER BY j.created DESC LIMIT 50")
        signature = [(j["id"], j["status"], j["completed"], j["total"]) for j in jobs]
        if signature == self.job_signature: return
        old = self.job_signature; self.job_signature = signature
        active = next((j for j in jobs if j["status"] in ("running", "queued", "cancelling")), None)
        if active:
            self.jobs_button.setText(f"{active['kind'].title()} · {active['completed']}/{active['total']}")
            self.progress.setValue(int(100 * active["completed"] / max(1, active["total"])))
        else:
            self.jobs_button.setText("Background work"); self.progress.setValue(100 if jobs and jobs[0]["status"] == "done" else 0)
        if old and self.book_id:
            if any(j['book_id']==self.book_id and j['status']=='running' for j in jobs):
                self.refresh_findings(); self.refresh_reading()
            for j in jobs:
                if j["book_id"] == self.book_id and j["status"] in ("done", "failed", "cancelled") and (j["id"], j["status"], j["completed"], j["total"]) not in old:
                    self.refresh_workspace(); self.status(j["error"] or "Research saved. Background work complete."); break

    def show_jobs(self):
        dialog = QDialog(self); dialog.setWindowTitle("Background work"); dialog.resize(840, 450)
        layout = QVBoxLayout(dialog); tree = QTreeWidget(); tree.setHeaderLabels(["Book / operation", "Progress", "Status"]); tree.setColumnWidth(0, 430); layout.addWidget(tree)
        error = label("Select a job to see its details.", "muted", True); layout.addWidget(error)
        def populate():
            selected = tree.currentItem().data(0, Qt.UserRole) if tree.currentItem() else None
            tree.clear()
            for j in self.app.db.rows("SELECT j.*,b.title FROM jobs j JOIN books b ON b.id=j.book_id ORDER BY created DESC"):
                item = QTreeWidgetItem([f"{j['title']} · {j['kind']}", f"{j['completed']} / {j['total']}", j["status"]]); item.setData(0, Qt.UserRole, j["id"]); tree.addTopLevelItem(item)
                if j["id"] == selected: tree.setCurrentItem(item)
        def selected_job(): return tree.currentItem().data(0, Qt.UserRole) if tree.currentItem() else None
        def details():
            if selected_job():
                j = self.app.jobs.get(selected_job()); error.setText(j["error"] or "Completed units are stored independently and remain saved when work stops.")
        def action(resume):
            if not selected_job(): return
            try:
                self.app.jobs.resume(selected_job()) if resume else self.app.jobs.cancel(selected_job()); populate(); details()
            except Exception as exc: error.setText(str(exc))
        tree.itemSelectionChanged.connect(details)
        layout.addWidget(row(button("Refresh", callback=populate), None, button("Cancel job", callback=lambda: action(False)), button("Resume", "arrow", True, lambda: action(True))))
        populate(); self.open_dialog(dialog)

    def refresh_chat(self):
        clear_layout(self.chat_layout)
        history = self.app.assistant.history(self.book_id)
        if not history:
            card, layout = layout_frame("subtle", 17, 10)
            layout.addWidget(label("A little help with the big ideas.", "subheading", True))
            layout.addWidget(label("Ask about a passage, find a definition, or explore a different way to organize your book." if self.book_id else "I can help you find books in your library. Open one to explore its ideas and sources together.", "muted", True))
            self.chat_layout.addWidget(card)
            if self.book_id:
                # Short button labels: Qt buttons do not wrap and would widen the panel.
                for short, text in (("Explain the argument", "Explain the argument and supporting evidence in detail"),
                                    ("Methods and limitations", "Analyze the methods, assumptions, and limitations"),
                                    ("Key concepts", "Define the key concepts and how they connect")):
                    self.chat_layout.addWidget(button(short, "spark", quiet=True, callback=lambda checked=False, t=text: self.chat_input.setPlainText(t)))
        for m in history:
            if m["role"] == "user": self.chat_message("You", m["content"], user=True)
            else:
                try: self.render_answer(json.loads(m["content"]))
                except ValueError: self.chat_message("Assistant", m["content"])
        self.chat_layout.addStretch()

    def chat_message(self, who, text, user=False):
        card, layout = layout_frame("card" if user else "subtle", 14, 7)
        layout.addWidget(label(who, "blue" if user else "eyebrow"))
        content = label(text, wrap=True); content.setTextInteractionFlags(Qt.TextSelectableByMouse); layout.addWidget(content)
        count = self.chat_layout.count()
        self.chat_layout.insertWidget(max(0, count - 1) if count and self.chat_layout.itemAt(count - 1).spacerItem() else count, card)
        QTimer.singleShot(30, lambda: self.chat_scroll.verticalScrollBar().setValue(self.chat_scroll.verticalScrollBar().maximum()))
        return layout

    def render_answer(self, result):
        text = "\n\n".join(("Explanation: " if p["kind"] == "explanation" else "") + p["text"] for p in result.get("parts", []))
        layout = self.chat_message("ASSISTANT", text)
        cited = {p for part in result.get("parts", []) for p in part["source_ids"]}
        for s in result.get("sources", []):
            if s["id"] in cited:
                b = button(f"Source · PDF page {s['page']}", "file", quiet=True, callback=lambda checked=False, pid=s["id"]: self.view_source(pid)); b.setToolTip(s["text"]); layout.addWidget(b)
        layout.addWidget(label(result.get("coverage", ""), "muted", True))

    def ask(self):
        if self.chat_busy: return
        text = self.chat_input.toPlainText().strip()
        if not text: return
        self.chat_input.clear(); self.chat_busy = True; self.send.setEnabled(False)
        self.chat_message("You", text, user=True)
        book_id = self.book_id
        section = None if self.whole_book.isChecked() else self.section_id
        source = None if self.whole_book.isChecked() else self.source_id
        def work():
            try: return self.app.assistant.ask(text, book_id, section, source, on_status=lambda s: self.events.put((self.status, s, None)))
            except Exception as exc: return {"error": str(exc)}
        def done(result):
            self.chat_busy = False; self.send.setEnabled(True)
            if "error" in result:
                if self.book_id == book_id: self.chat_message("Could not finish", result["error"])
                self.status(result["error"]); return
            if self.book_id == book_id:
                self.render_answer(result); self.refresh_workspace()
                for event in result["events"]:
                    value = event["result"]
                    if event["tool"] == "navigate":
                        if value.get("section_id"): self.select_section(value["section_id"])
                        if value.get("source_id"): self.view_source(value["source_id"])
                    if event["tool"] == "propose_structure": self.preview_structure(value["structure_id"])
                    if event["tool"] == "extract":
                        deep_read_dialog(self, [value["section_id"]] if value.get("section_id") else [], value.get("focus", ""))
            self.status("Response saved. Verify interpretations using the linked sources.")
        self.run("Asking your selected model…", work, done)

    def choose_structure(self, index):
        if not self.book_id or index < 0: return
        structure = self.structure_rows[index]
        if not structure["applied"]:
            self.structure_choice.setCurrentIndex(self.structure_choice.findData(self.app.library.book(self.book_id)["active_structure"]))
            return self.preview_structure(structure["id"])
        self.app.research.apply_structure(self.book_id, structure["id"]); self.section_id = None; self.refresh_workspace()

    def preview_structure(self, structure_id):
        if not self.require_book(): return
        book_id = self.book_id
        sections = self.app.library.sections(book_id, structure_id)
        dialog = QDialog(self); dialog.setWindowTitle("Review proposed structure"); dialog.resize(700, 620)
        layout = QVBoxLayout(dialog); layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label("A new way to explore this book", "subheading", True))
        layout.addWidget(label("Review the section titles and their source pages. Original chapters remain available.", "muted", True))
        if any(s['origin'].startswith('Grouped source') for s in sections):
            layout.addWidget(label('This large-book preview uses sampled excerpts from groups of passages. Check the thematic boundaries before accepting; it is not a complete semantic reading.', 'muted', True))
        tree = QTreeWidget(); tree.setHeaderLabels(["Section", "PDF pages"]); tree.setColumnWidth(0, 370)
        for s in sections: tree.addTopLevelItem(QTreeWidgetItem([s["title"], ", ".join(map(str, s["pages"]))]))
        layout.addWidget(tree, 1)
        def apply():
            self.app.research.apply_structure(book_id, structure_id); self.section_id = None; dialog.accept(); self.refresh_workspace()
        layout.addWidget(row(button("Keep for later", callback=dialog.reject), None, button("Accept structure", "check", True, apply)))
        self.open_dialog(dialog)

    def reorganize_book(self):
        if not self.require_book(): return
        instruction, ok = QInputDialog.getText(self, "Reorganize book", "How should this book be organized? For example: group chapters by water treatment method.")
        if not ok or not instruction.strip(): return
        book_id = self.book_id
        def done(result):
            if self.book_id == book_id:
                self.refresh_workspace(); self.preview_structure(result["structure_id"])
        self.run("Preparing a new book structure…", lambda: self.app.research.propose_structure(book_id, instruction.strip()), done)

    def manual_structure(self):
        if not self.require_book(): return
        book_id = self.book_id; sections = self.app.library.sections(book_id); indices = {s["id"]: i for i, s in enumerate(sections)}
        spec = {"name": "My research structure", "sections": [{"title": s["title"], "parent_index": indices.get(s["parent_id"]), "source_ids": s["source_ids"]} for s in sections]}
        dialog = QDialog(self); dialog.setWindowTitle("Advanced structure editor"); dialog.resize(800, 650)
        layout = QVBoxLayout(dialog); layout.addWidget(label("Edit titles, parents, or source mappings. Saving creates a preview.", "muted", True))
        edit = QPlainTextEdit(); edit.setPlainText(json.dumps(spec, indent=2)); layout.addWidget(edit, 1)
        def save():
            try:
                result = self.app.research.save_structure(book_id, json.loads(edit.toPlainText()), origin="Manual correction")
                dialog.accept(); self.refresh_workspace(); self.preview_structure(result["structure_id"])
            except Exception as exc: QMessageBox.warning(dialog, "Invalid structure", str(exc))
        layout.addWidget(button("Validate and preview", "check", True, save)); self.open_dialog(dialog)

    def undo_structure(self):
        if not self.require_book(): return
        try: self.app.research.undo_structure(self.book_id); self.section_id = None; self.refresh_workspace()
        except Exception as exc: self.error(str(exc))

    def structure_menu(self):
        if not self.require_book(): return
        menu = QMenu(self)
        menu.addAction("Edit structure…", self.manual_structure)
        menu.addAction("Undo structure change", self.undo_structure)
        menu.addAction("Prepare / retry document", self.prepare)
        menu.exec(self.cursor().pos())

    def library_menu(self):
        menu = QMenu(self)
        menu.setObjectName("libraryMenu")
        menu.addAction("Scan a folder…", self.scan_folder)
        menu.addAction("Choose managed library folder…", self.choose_library)
        menu.addSeparator()
        menu.addAction("Organize current book…", self.edit_subjects)
        menu.addAction("Export current research…", self.export)
        menu.addAction("Remove current book…", self.remove_book)
        menu.exec(self.cursor().pos())

    def scan_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Scan PDF folder")
        if path: self.import_paths(sorted(Path(path).glob("*.pdf")))

    def choose_library(self):
        path = QFileDialog.getExistingDirectory(self, "Managed library folder")
        if path:
            try: self.app.config.set_library(path); self.status("New imports use this folder. Existing books remain at their recorded locations.")
            except Exception as exc: self.error(str(exc))

    def edit_subjects(self):
        if not self.book_id:
            books = self.app.library.books()
            if not books: self.status("Import a book first, then assign its subjects."); return
            titles = [f"{index + 1}. {book['title']}" for index, book in enumerate(books)]
            chosen, ok = QInputDialog.getItem(self, "Choose a book", "Book to organize:", titles, 0, False)
            if not ok: return
            self.select_book(books[titles.index(chosen)]["id"])
            if not self.book_id: return
        names = self.app.db.rows("SELECT s.name FROM subjects s JOIN book_subjects b ON b.subject_id=s.id WHERE b.book_id=?", (self.book_id,))
        value, ok = QInputDialog.getText(self, "Assign book subjects", "Enter subjects, for example: Water, Energy. Separate subjects with commas; use / for nested subjects:", text=", ".join(n["name"] for n in names))
        if ok:
            self.app.library.set_subjects(self.book_id, value.split(","))
            self.subject.setCurrentIndex(0); self.refresh_books(force=True); self.refresh_workspace()
            self.status("Subjects saved. Select one in All subjects to filter your library.")

    def export(self):
        if not self.require_book(): return
        path, _ = QFileDialog.getSaveFileName(self, "Export research", "research.json", "JSON research (*.json)")
        if path:
            try: Path(path).write_text(json.dumps(export_book(self.app, self.book_id), indent=2, ensure_ascii=False)); self.status("Research exported with source mappings. Credentials are excluded.")
            except Exception as exc: self.error(str(exc))

    def remove_book(self):
        if not self.require_book() or not self.guard_note(): return
        if QMessageBox.question(self, "Remove book", "Remove this book and its saved research from Folio? Your original and managed PDF files will be retained.") != QMessageBox.Yes: return
        try: self.app.library.remove(self.book_id); self.note_baseline = self.note_text.toPlainText().strip(); self.show_library(); self.refresh_books(force=True)
        except Exception as exc: self.error(str(exc))

    def open_pdf(self):
        if not self.require_book(): return
        page = self.app.library.source(self.book_id, self.source_id)["page"] if self.source_id else 1
        try: self.open_dialog(PDFWindow(self, self.app.library.book(self.book_id)["path"], page))
        except Exception as exc: self.error(str(exc))

    def open_dialog(self, dialog):
        self.dialogs.append(dialog)
        dialog.finished.connect(lambda: self.dialogs.remove(dialog) if dialog in self.dialogs else None)
        dialog.show(); dialog.raise_()

    def settings(self):
        for dialog in self.dialogs:
            if isinstance(dialog, SettingsWindow):
                dialog.raise_(); dialog.activateWindow(); return
        self.open_dialog(SettingsWindow(self))

    def closeEvent(self, event):
        if self.ready_to_close: event.accept(); return
        if not self.guard_note(): event.ignore(); return
        running = self.pending_tasks or self.chat_busy or self.app.db.one("SELECT id FROM jobs WHERE status IN ('queued','running','cancelling')")
        if running and QMessageBox.question(self, "Close Folio", "Stop background work and close when the current request returns? Completed work remains saved.") != QMessageBox.Yes:
            event.ignore(); return
        self.timer.stop()
        if running:
            event.ignore(); self.setEnabled(False); self.status("Closing safely after the current request returns…")
            for dialog in list(self.dialogs): dialog.reject()
            for j in self.app.db.rows("SELECT id FROM jobs WHERE status IN ('queued','running')"): self.app.jobs.cancel(j["id"])
            import threading
            def wait():
                self.pool.shutdown(wait=True, cancel_futures=True)
                if self.owns_app: self.app.close()
                self.events.put((self.finish_close, None, None))
            threading.Thread(target=wait, daemon=True).start()
            self.timer.start(200)
        else:
            self.pool.shutdown(wait=True, cancel_futures=True)
            if self.owns_app: self.app.close()
            self.closed = True; event.accept()

    def finish_close(self, _):
        self.timer.stop(); self.closed = True; self.ready_to_close = True; self.close()


class PDFWindow(QDialog):
    def __init__(self, parent, path, page=1):
        super().__init__(parent)
        self.doc = pymupdf.open(path)
        self.page = max(1, min(page, len(self.doc))); self.scale = 1.2
        self.setWindowTitle("Original source · Folio"); self.resize(930, 850)
        layout = QVBoxLayout(self)
        self.page_label = label("")
        layout.addWidget(row(button("Previous", "back", callback=lambda: self.move(-1)), button("Next", "arrow", callback=lambda: self.move(1)), self.page_label, None,
                             button("−", callback=lambda: self.zoom(-.2)), button("+", callback=lambda: self.zoom(.2))))
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(False); self.scroll.setAlignment(Qt.AlignHCenter)
        self.image = QLabel(); self.scroll.setWidget(self.image); layout.addWidget(self.scroll, 1)
        self.finished.connect(lambda: self.doc.close()); self.render()

    def render(self):
        p = self.doc[self.page - 1]
        pix = p.get_pixmap(matrix=pymupdf.Matrix(self.scale, self.scale), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        self.image.setPixmap(QPixmap.fromImage(img)); self.image.resize(pix.width, pix.height)
        self.page_label.setText(f"PDF page {self.page} / {len(self.doc)} · Label {p.get_label() or self.page}")
        self.scroll.verticalScrollBar().setValue(0)

    def move(self, delta): self.page = max(1, min(len(self.doc), self.page + delta)); self.render()
    def zoom(self, delta): self.scale = max(.6, min(2.4, self.scale + delta)); self.render()


def main(home=None):
    qt = QApplication.instance() or QApplication(sys.argv)
    qt.setApplicationName("Folio Deepthinking"); qt.setOrganizationName("Folio Research")
    qt.setFont(QFont("Noto Sans", 10))
    try: core = App(home)
    except Exception as exc:
        QMessageBox.critical(None, "Folio", str(exc)); return
    window = Desktop(core); window.show(); qt.exec()


if __name__ == "__main__": main()
