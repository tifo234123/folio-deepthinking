"""Reading overview: immediate source text and honest, scoped analysis coverage."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QPlainTextEdit,QLabel
from .theme import label,button,row


def refresh_reading(ui):
    from .desktop import clear_layout,layout_frame
    if not ui.book_id:return
    data=ui.app.research.reading_overview(ui.book_id,ui.section_id)
    clear_layout(ui.reading_layout)
    card,layout=layout_frame('subtle',20,10)
    title='Selected section' if ui.section_id else 'Whole book'
    layout.addWidget(label(title+' · Reading overview','subheading',True))
    layout.addWidget(label(f"{data['pages']} PDF pages · {data['passages']:,} passages · {data['reviewed']:,} previously reviewed · {data['findings']:,} saved findings",'muted',True))
    layout.addWidget(label('Imported text is ready to read. AI findings appear after a reading job; earlier reviews may have used a different research focus.','muted',True))
    layout.addWidget(row(button('Deep read this scope','spark',True,ui.extract),button('See saved findings',callback=lambda:ui.tabs.setCurrentWidget(ui.findings_page)),None))
    ui.reading_layout.addWidget(card)
    jobs=ui.app.db.rows("SELECT status,completed,total,error FROM jobs WHERE book_id=? AND kind='extract' ORDER BY created DESC LIMIT 1",(ui.book_id,))
    if jobs:
        j=jobs[0];ui.reading_layout.addWidget(label(f"Latest book reading: {j['status']} · {j['completed']:,}/{j['total']:,} passages"+(f" · {j['error']}" if j['error'] else ''),'muted',True))
    if data['skipped']:
        ui.reading_layout.addWidget(label(f"{data['skipped']} reviewed passages had no substantive finding for their run. Bibliographies and headings are retained as sources, without inventing research findings.",'muted',True))
    ui.reading_layout.addWidget(label('Inside this scope','subheading'))
    ui.reading_layout.addWidget(label('Selected verbatim excerpts across the scope, prioritizing explanatory prose. These are reading previews, not an AI summary or an exhaustive review.','muted',True))
    for p in data['excerpts']:
        card,layout=layout_frame('card',18,10)
        layout.addWidget(row(label(f"PDF page {p['page']} · printed label {p['label']}",'muted'),None,
            button('Read page','file',quiet=True,callback=lambda checked=False,pid=p['id']:ui.view_source(pid))))
        excerpt=label(p['text'],wrap=True);excerpt.setTextInteractionFlags(Qt.TextSelectableByMouse);layout.addWidget(excerpt)
        ui.reading_layout.addWidget(card)
    if not data['excerpts']:
        ui.reading_layout.addWidget(label('No readable passages in this scope. Check document preparation and the original pages.','muted',True))
    ui.reading_layout.addStretch()


def deep_read_dialog(ui,sections=None,initial_focus=''):
    if not ui.require_book():return
    book_id=ui.book_id
    if sections is None:sections=[i.data(0,Qt.UserRole) for i in ui.sections_tree.selectedItems() if i.data(0,Qt.UserRole)]
    dialog=QDialog(ui);dialog.setWindowTitle('Deep read · Folio Deepthinking');dialog.resize(620,410)
    layout=QVBoxLayout(dialog);layout.setContentsMargins(24,24,24,24);layout.setSpacing(14)
    layout.addWidget(label('Read for understanding','heading',True))
    layout.addWidget(label(f"Scope: {len(sections)} selected section(s)" if sections else 'Scope: whole book','subheading',True))
    info=label('','muted',True);layout.addWidget(info)
    focus=QPlainTextEdit();focus.setPlaceholderText('Optional focus, e.g. explain the links between water, energy, food, and SDGs, with examples and limitations.');focus.setMaximumHeight(110);focus.setPlainText(initial_focus);layout.addWidget(focus)
    layout.addWidget(label('Creates detailed, cited findings for ideas, definitions, methods, formulas and data. Reading uses your selected provider and may incur API charges. You can cancel or resume from Background work.','muted',True))
    error=label('','muted',True);layout.addWidget(error)
    start=button('Start deep reading','spark',True)
    def build_payload():
        payload=ui.app.research.deep_payload(book_id,sections or None,focus.toPlainText().strip())
        settings=ui.app.config.get()
        batches=sum(1 for _ in ui.app.research.deep_batches(book_id,payload['source_ids'],payload['focus'],settings))
        return payload,batches
    try:
        payload,batches=build_payload();info.setText(f"{len(payload['source_ids']):,} passages · about {batches:,} model calls before retries\n{payload['provider']} / {payload['model']}")
    except Exception as exc:error.setText(str(exc));start.setEnabled(False)
    def begin():
        try:
            payload,batches=build_payload()
            ui.app.jobs.create(book_id,'extract',payload)
            dialog.accept();ui.tabs.setCurrentWidget(ui.reading_page);ui.refresh_reading()
            ui.status(f"Deep reading started · {len(payload['source_ids']):,} passages in about {batches:,} batches.")
        except Exception as exc:error.setText(str(exc))
    start.clicked.connect(begin)
    layout.addWidget(row(button('Cancel',callback=dialog.reject),None,start))
    dialog.exec()
