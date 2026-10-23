"""Native Qt smoke tests with synthetic documents and simulated AI responses."""
import os
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from folio.desktop import Desktop, PDFWindow, SettingsWindow
from folio.settings_ui import ModelPicker
from folio.providers import ProviderError


def wait_until(qt, predicate):
    for _ in range(100):
        qt.processEvents(); QTest.qWait(20)
        if predicate(): return
    assert predicate(), "UI operation did not finish"


@pytest.fixture(scope="module")
def qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen" if not os.environ.get("DISPLAY") else "xcb")
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Noto Sans", 10))
    return app


def test_desktop_workflow(qt, app, book, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: errors.append(text))
    ui = Desktop(app, owns_app=False); ui.show()
    screenshots = os.environ.get("FOLIO_QA_SCREENSHOTS")
    def settle(): qt.processEvents(); QTest.qWait(150); qt.processEvents()
    def capture(widget, name):
        if screenshots:
            path = Path(screenshots); path.mkdir(parents=True, exist_ok=True); widget.grab().save(str(path / name))
    try:
        ui.select_book(book["id"]); settle()
        assert ui.sections_tree.topLevelItemCount() == 3
        section = app.library.sections(book["id"])[1]["id"]
        ui.select_section(section); settle(); assert ui.section_id == section
        job = app.jobs.create(book["id"], "extract", app.research.extraction_payload(book["id"], [section]), background=False)
        assert job["status"] == "done"
        ui.refresh_workspace(); settle(); assert ui.findings_layout.count() > 1
        ui.new_note(); ui.note_text.setPlainText("A saved observation about this synthetic fixture."); ui.save_note()
        assert app.db.one("SELECT id FROM notes WHERE book_id=?", (book["id"],))
        ui.sources_tree.setCurrentItem(ui.sources_tree.topLevelItem(0)); settle(); assert ui.source_id
        result = app.assistant.ask("Explain pressure", book["id"], section); ui.render_answer(result); settle()
        capture(ui, "desktop-workspace.png")
        pdf = PDFWindow(ui, book["path"], 3); pdf.show(); settle()
        assert pdf.page == 3
        pdf.move(-1); assert pdf.page == 2
        pdf.zoom(.2); capture(pdf, "desktop-pdf.png"); pdf.close()
        settings = SettingsWindow(ui)
        settings.provider.setCurrentIndex(settings.provider.findData("nvidia")); settings.show(); settle()
        assert "integrate.api.nvidia.com" in settings.endpoint.text()
        settings.model.setEditText("test-only/model")
        settings.key.setText("fake-key-not-a-real-credential")
        monkeypatch.setattr("folio.settings_ui.Provider.test", lambda self: "OK")
        settings.save(); wait_until(qt, lambda: not settings.busy)
        assert app.config.get().provider == "nvidia"
        assert not settings.key.text()
        capture(settings, "desktop-settings.png"); settings.close()
        ui.show_library(); settle(); assert ui.book_id is None
        capture(ui, "desktop-library.png")
        ui.select_book(book["id"]); ui.select_section(section); settle()
        assert app.db.one("SELECT value FROM ui_state WHERE key='last_book'")["value"] == book["id"]
        assert not errors
    finally:
        ui.close(); qt.processEvents()


def test_desktop_restores_context(qt, app, book):
    section = app.library.sections(book["id"])[1]["id"]
    app.db.execute("INSERT OR REPLACE INTO ui_state VALUES('last_book',?)", (book["id"],))
    app.db.execute("INSERT OR REPLACE INTO ui_state VALUES('last_section',?)", (section,))
    ui = Desktop(app, owns_app=False)
    try:
        assert ui.book_id == book["id"] and ui.section_id == section
    finally: ui.close(); qt.processEvents()


def test_provider_setup_failure_preserves_active_settings(qt, app, monkeypatch):
    ui = Desktop(app, owns_app=False)
    settings = SettingsWindow(ui)
    before = app.config.values()
    try:
        settings.provider.setCurrentIndex(settings.provider.findData("openrouter"))
        settings.key.setText("fake-new-key"); settings.model.setEditText("test/model")
        def fail(_): raise ProviderError("Check the API key (HTTP 401)")
        monkeypatch.setattr("folio.settings_ui.Provider.test", fail)
        settings.save(); wait_until(qt, lambda: not settings.busy)
        assert app.config.values() == before
        assert "401" in settings.info.text() and "unchanged" in settings.info.text()
        # A change to the already active provider is also transactional.
        settings.provider.setCurrentIndex(settings.provider.findData(app.config.get().provider))
        settings.model.setEditText("unusable-model")
        settings.save(); wait_until(qt, lambda: not settings.busy)
        assert app.config.values() == before
    finally: settings.close(); ui.close(); qt.processEvents()


def test_openrouter_catalog_cache_and_model_picker(qt, app, monkeypatch):
    catalog = [
        {"id": "acme/research:free", "name": "Acme Research", "free": True, "context_length": 128000,
         "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools", "response_format"]},
        {"id": "acme/paid", "name": "Acme Paid", "free": False, "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
    ]
    monkeypatch.setattr("folio.settings_ui.Provider.catalog", lambda _: catalog)
    monkeypatch.setattr("folio.settings_ui.Provider.key_status", lambda _: {"limit_remaining": 9.5})
    monkeypatch.setattr(SettingsWindow, "pick_model", lambda _: None)
    ui = Desktop(app, owns_app=False); settings = SettingsWindow(ui)
    before = app.config.values()
    try:
        settings.preset_buttons["openrouter"].click()
        settings.key.setText("fake-key"); settings.discover(); wait_until(qt, lambda: not settings.busy)
        assert settings.catalog == catalog and settings.browse.isEnabled()
        assert settings.model.currentText() == ""  # No automatic paid/random model selection.
        assert "$9.5" in settings.info.text()
        assert app.config.values() == before
        cached = app.db.one("SELECT value FROM ui_state WHERE key='catalog_openrouter'")["value"]
        assert "fake-key" not in cached and "limit_remaining" not in cached
        picker = ModelPicker(settings, catalog, openrouter=True)
        screenshots = os.environ.get("FOLIO_QA_SCREENSHOTS")
        if screenshots:
            settings.show(); qt.processEvents()
            settings.grab().save(str(Path(screenshots) / "desktop-openrouter.png"))
            picker.show(); qt.processEvents()
            picker.results.setCurrentItem(picker.results.topLevelItem(0)); qt.processEvents()
            picker.grab().save(str(Path(screenshots) / "desktop-model-picker.png"))
        assert picker.results.topLevelItemCount() == 2
        picker.free_only.setChecked(True); assert picker.results.topLevelItemCount() == 1
        picker.results.setCurrentItem(picker.results.topLevelItem(0)); picker.accept_selection()
        assert picker.selected_id == "acme/research:free"
        picker.free_only.setChecked(False); picker.search.setText("acme paid")
        assert picker.results.topLevelItemCount() == 1
        picker.search.setText("nothing matches"); assert not picker.choose.isEnabled()
        picker.close()
        settings.load(); assert settings.catalog == catalog
        def fail(_): raise ProviderError("Offline")
        monkeypatch.setattr("folio.settings_ui.Provider.catalog", fail)
        settings.discover(); wait_until(qt, lambda: not settings.busy)
        assert settings.catalog == catalog and settings.browse.isEnabled()
    finally: settings.close(); ui.close(); qt.processEvents()


def test_dismissed_connection_does_not_activate(qt, app, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    def respond(_):
        entered.set(); assert release.wait(3); return "OK"
    monkeypatch.setattr("folio.settings_ui.Provider.test", respond)
    ui = Desktop(app, owns_app=False); settings = SettingsWindow(ui)
    before = app.config.values()
    try:
        settings.provider.setCurrentIndex(settings.provider.findData("nvidia"))
        settings.key.setText("fake-key"); settings.model.setEditText("new-model")
        settings.save(); wait_until(qt, entered.is_set)
        settings.reject(); release.set(); wait_until(qt, lambda: ui.pending_tasks == 0)
        assert app.config.values() == before
    finally: release.set(); settings.close(); ui.close(); qt.processEvents()


def test_subject_assignment_and_reorganized_outline(qt, app, book, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QPushButton
    ui = Desktop(app, owns_app=False); ui.show()
    try:
        ui.select_book(book['id'])
        original = ui.structure_choice.currentData()
        monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **kw: ('Water, Energy', True))
        ui.edit_subjects()
        assert ui.subject.findText('Water') >= 0
        assert 'Water' in ui.book_meta.text()
        ui.subject.setCurrentIndex(ui.subject.findText('Water'))
        assert ui.books_tree.topLevelItemCount() == 1
        def propose(book_id, instruction):
            return app.research.save_structure(book_id, {'name': 'By water treatment', 'sections': [
                {'title': 'Water methods', 'source_ids': [p['id'] for p in app.library.passages(book_id)]}]})
        monkeypatch.setattr(app.research, 'propose_structure', propose)
        ui.reorganize_book(); wait_until(qt, lambda: ui.pending_tasks == 0)
        index = ui.structure_choice.findText('By water treatment · Preview')
        assert index >= 0 and ui.structure_choice.currentData() == original
        preview = ui.dialogs[-1]
        accept = next(b for b in preview.findChildren(QPushButton) if b.text() == 'Accept structure')
        accept.click()
        assert ui.structure_choice.currentText() == 'By water treatment'
        assert ui.structure_choice.findData(original) >= 0
        ui.choose_structure(ui.structure_choice.findData(original))
        assert ui.structure_choice.currentData() == original
        screenshots = os.environ.get('FOLIO_QA_SCREENSHOTS')
        if screenshots:
            ui.subject.showPopup(); qt.processEvents()
            ui.subject.view().grab().save(str(Path(screenshots) / 'subjects-dropdown.png'))
            ui.subject.hidePopup()
            ui.structure_choice.showPopup(); qt.processEvents()
            ui.structure_choice.view().grab().save(str(Path(screenshots) / 'structures-dropdown.png'))
            ui.structure_choice.hidePopup()
    finally:
        for dialog in list(ui.dialogs): dialog.reject()
        ui.close(); qt.processEvents()


def test_section_reader_keeps_complete_scope_and_page_context(qt,app,book):
    ui=Desktop(app,owns_app=False)
    try:
        ui.select_book(book['id'])
        section=app.library.sections(book['id'])[-1]['id'];ui.select_section(section)
        expected=app.library.passages(book['id'],section)
        reader=ui.section_reader
        assert {p['id'] for p in reader.passages}=={p['id'] for p in expected}
        assert reader.pages==sorted({p['page'] for p in expected})
        for p in expected:
            if p['page']==reader.page_choice.currentData():
                assert ' '.join(p['text'].split()) in ' '.join(reader.text.toPlainText().split())
        reader.ask_page()
        assert ui.source_id in {p['id'] for p in expected}
        assert 'PhD' in ui.chat_input.toPlainText()
        assert ui.source_query.placeholderText()=='Search the selected section'
    finally:ui.close();qt.processEvents()
