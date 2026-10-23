"""Browse all extracted text in the chosen section, page by page."""
import html
from PySide6.QtWidgets import QFrame,QVBoxLayout,QTextBrowser,QComboBox
from .theme import label,button,row


class SectionReader(QFrame):
    def __init__(self, desktop):
        super().__init__();self.desktop=desktop;self.scope=None;self.pages=[];self.passages=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(10)
        self.heading=label('','subheading',True);layout.addWidget(self.heading)
        self.page_choice=QComboBox();self.page_choice.activated.connect(self.render)
        self.previous=button('Previous','back',callback=lambda:self.move(-1))
        self.next=button('Next','arrow',callback=lambda:self.move(1))
        layout.addWidget(row(self.previous,self.page_choice,self.next))
        self.text=QTextBrowser();self.text.setOpenLinks(False);self.text.setOpenExternalLinks(False)
        self.text.anchorClicked.connect(lambda url:self.desktop.view_source(url.toString()))
        layout.addWidget(self.text,1)
        layout.addWidget(label('Extracted text may lose table or equation layout. Open the original PDF to verify.','muted',True))
        self.explain=button('Explain this page in depth','spark',callback=self.ask_page)
        layout.addWidget(row(self.explain,None,button('Original PDF','file',callback=self.original)))

    def set_scope(self,book_id,section_id):
        changed=self.scope!=(book_id,section_id);self.scope=(book_id,section_id)
        page=self.page_choice.currentData() if not changed else None
        self.passages=self.desktop.app.library.passages(book_id,section_id)
        self.pages=sorted({p['page'] for p in self.passages})
        section=self.desktop.app.db.one('SELECT title FROM sections WHERE id=?',(section_id,)) if section_id else None
        self.heading.setText(section['title'] if section else 'Whole book')
        self.page_choice.clear()
        for index,value in enumerate(self.pages):
            source=next(p for p in self.passages if p['page']==value)
            self.page_choice.addItem(f"{index+1} / {len(self.pages)} · PDF {value} · label {source['label']}",value)
        if page in self.pages:self.page_choice.setCurrentIndex(self.pages.index(page))
        self.render()

    def render(self,*_):
        page=self.page_choice.currentData()
        self.previous.setEnabled(self.page_choice.currentIndex()>0)
        self.next.setEnabled(0<=self.page_choice.currentIndex()<len(self.pages)-1)
        self.explain.setEnabled(page is not None)
        parts=[f'<p style="margin-bottom:18px;line-height:1.5">{html.escape(p["text"]).replace(chr(10),"<br>")}<br><a href="{p["id"]}">View supporting PDF page</a></p>' for p in self.passages if p['page']==page]
        self.text.setHtml(''.join(parts) if parts else '<p>No readable text in this scope.</p>')

    def move(self,delta):
        index=self.page_choice.currentIndex()+delta
        if 0<=index<len(self.pages):self.page_choice.setCurrentIndex(index);self.render()

    def page_source(self):
        return next((p for p in self.passages if p['page']==self.page_choice.currentData()),None)

    def ask_page(self):
        source=self.page_source()
        if source:
            self.desktop.source_id=source['id'];self.desktop.update_context()
            self.desktop.chat_input.setPlainText('Explain this page in depth for a PhD reading: the argument, concepts, mechanisms, evidence, methods, assumptions, and limitations. Cite the passages and distinguish author statements from your interpretation.')
            self.desktop.chat_input.setFocus()

    def original(self):
        source=self.page_source()
        if source:self.desktop.view_source(source['id'])
