"""Native provider setup with explicit model selection and verified activation."""
from datetime import datetime, timezone
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QGridLayout, QComboBox, QLineEdit,
    QCheckBox, QTreeWidget, QTreeWidgetItem, QSpinBox,
)
from .config import PROVIDERS
from .providers import Provider, price_per_million
from .theme import DARK, LIGHT, button, label, row


PRESET_LABELS = {
    "ollama": "Ollama", "lmstudio": "LM Studio", "openai": "OpenAI",
    "anthropic": "Claude", "gemini": "Gemini", "nvidia": "NVIDIA",
    "openrouter": "OpenRouter", "compatible": "Custom API",
}
PRESET_ORDER = ["ollama", "lmstudio", "nvidia", "openrouter", "openai", "anthropic", "gemini", "compatible"]


def panel(name, margin=18, spacing=10):
    widget = QFrame(); widget.setObjectName(name)
    layout = QVBoxLayout(widget); layout.setContentsMargins(margin, margin, margin, margin); layout.setSpacing(spacing)
    return widget, layout


def context_label(value):
    try: return f"{int(value):,}" if value else "—"
    except (ValueError, TypeError): return "—"


class ModelPicker(QDialog):
    def __init__(self, parent, catalog, current="", openrouter=False):
        super().__init__(parent)
        self.catalog, self.selected_id = catalog, ""
        self.setWindowTitle("Choose a model · Folio"); self.resize(910, 650)
        self.setStyleSheet(LIGHT + "QDialog { background: #fff; }")
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 22, 24, 22); layout.setSpacing(12)
        layout.addWidget(label("Choose your model", "heading"))
        layout.addWidget(label("Search the provider’s catalogue. Access is verified when you use the model.", "muted", True))
        self.search = QLineEdit(); self.search.setPlaceholderText("Search by model name or ID…"); self.search.setClearButtonEnabled(True)
        self.free_only = QCheckBox("Free models only"); self.free_only.setVisible(openrouter)
        layout.addWidget(row(self.search, self.free_only))
        self.results = QTreeWidget(); self.results.setRootIsDecorated(False); self.results.setAlternatingRowColors(False)
        self.results.setHeaderLabels(["Model", "Context · tokens", "Input / 1M", "Output / 1M"])
        self.results.setColumnWidth(0, 395); self.results.setColumnWidth(1, 150)
        self.results.setColumnWidth(2, 130)
        layout.addWidget(self.results, 1)
        self.count = label("", "muted"); layout.addWidget(self.count)
        self.details = label("Select a model to see its details.", "muted", True); self.details.setMinimumHeight(84); layout.addWidget(self.details)
        self.choose = button("Choose model", "check", True, self.accept_selection); self.choose.setEnabled(False)
        layout.addWidget(row(button("Cancel", callback=self.reject), None, self.choose))
        self.search.textChanged.connect(self.populate); self.free_only.toggled.connect(self.populate)
        self.results.currentItemChanged.connect(self.describe)
        self.results.itemDoubleClicked.connect(lambda *_: self.accept_selection())
        self.populate()
        for index in range(self.results.topLevelItemCount()):
            item = self.results.topLevelItem(index)
            if item.data(0, Qt.UserRole)["id"] == current:
                self.results.setCurrentItem(item); self.results.scrollToItem(item); break
        self.search.setFocus()

    def populate(self, *_):
        terms = self.search.text().casefold().split()
        current = self.results.currentItem()
        previous = current.data(0, Qt.UserRole)["id"] if current else ""
        self.results.clear()
        for model in self.catalog:
            haystack = (model["name"] + " " + model["id"]).casefold()
            if any(term not in haystack for term in terms) or (self.free_only.isChecked() and not model.get("free")): continue
            pricing = model.get("pricing") or {}
            title = model["name"] + (" · Free" if model.get("free") else "")
            item = QTreeWidgetItem([title, context_label(model.get("context_length")), price_per_million(pricing.get("prompt")), price_per_million(pricing.get("completion"))])
            item.setData(0, Qt.UserRole, model); item.setToolTip(0, model["id"])
            self.results.addTopLevelItem(item)
            if model["id"] == previous: self.results.setCurrentItem(item)
        total = self.results.topLevelItemCount()
        self.count.setText(f"{total} of {len(self.catalog)} models" + (" · No matches. Try a different search." if not total else ""))
        self.describe()

    def describe(self, *_):
        item = self.results.currentItem(); self.choose.setEnabled(item is not None)
        if not item: self.details.setText("Select a model to see its details."); return
        model = item.data(0, Qt.UserRole)
        flags = []
        supported = model.get("supported_parameters", [])
        if "tools" in supported: flags.append("Tools")
        if "structured_outputs" in supported or "response_format" in supported: flags.append("Structured output")
        if model.get("max_output"): flags.append(f"Max output: {context_label(model['max_output'])} tokens")
        description = model.get("description", "").replace("\n", " ")[:220]
        self.details.setText(model["id"] + ("\n" + " · ".join(flags) if flags else "") + ("\n" + description if description else "") + "\nUSD per million tokens; other charges and provider limits may apply. Prices are from the last refresh.")

    def accept_selection(self):
        item = self.results.currentItem()
        if item:
            self.selected_id = item.data(0, Qt.UserRole)["id"]; self.accept()


class SettingsWindow(QDialog):
    def __init__(self, desktop):
        super().__init__(desktop)
        self.desktop, self.app = desktop, desktop.app
        self.catalog = []; self.generation = 0; self.busy = False
        self.setWindowTitle("AI settings · Folio"); self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(DARK); self.setFixedWidth(640)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_StyledBackground)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        shell, layout = panel("settingsShell", 26, 14); outer.addWidget(shell)
        close = button("×", quiet=True, callback=self.reject); close.setFixedWidth(28)
        layout.addWidget(row(label("AI settings", "heading"), None, close))
        layout.addWidget(label("Your research. Your choice of AI.", "muted"))
        self.controls, form = panel("settingsGroup", 20, 12); layout.addWidget(self.controls)
        form.addWidget(label("1   Choose a provider"))
        presets = QFrame(); grid = QGridLayout(presets); grid.setContentsMargins(0, 0, 0, 0); grid.setSpacing(8)
        self.provider = QComboBox(self); self.provider.hide(); self.preset_buttons = {}
        for index, name in enumerate(PRESET_ORDER):
            self.provider.addItem(PROVIDERS[name][0], name)
            b = button(PRESET_LABELS[name], callback=lambda checked=False, p=name: self.provider.setCurrentIndex(self.provider.findData(p)))
            b.setObjectName("preset"); b.setCheckable(True); b.setMinimumWidth(116)
            grid.addWidget(b, index // 4, index % 4); self.preset_buttons[name] = b
        form.addWidget(presets)
        self.provider_hint = label("", "muted", True); form.addWidget(self.provider_hint)
        self.key_label = label("2   Paste your API key"); form.addWidget(self.key_label)
        self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.Password); self.key.setPlaceholderText("Paste your API key")
        self.key.setClearButtonEnabled(True); self.key.setAccessibleName("Provider API key")
        form.addWidget(self.key)
        self.key_hint = label("", "muted", True); form.addWidget(self.key_hint)
        self.connect_button = button("Connect and load models", "arrow", callback=self.discover)
        form.addWidget(self.connect_button)
        form.addWidget(label("3   Choose a model"))
        self.model = QComboBox(); self.model.setEditable(True); self.model.setInsertPolicy(QComboBox.NoInsert)
        self.model.lineEdit().setPlaceholderText("Choose a model or paste its ID")
        self.browse = button("Browse…", "search", callback=self.pick_model)
        form.addWidget(row(self.model, self.browse))
        self.model_hint = label("", "muted", True); form.addWidget(self.model_hint)
        self.endpoint = QLineEdit(self); self.endpoint.hide()
        self.input_chars = QLineEdit(self); self.input_chars.hide()
        self.output_tokens = QLineEdit(self); self.output_tokens.hide()
        self.clear_key = QCheckBox(self); self.clear_key.hide()
        self.advanced_button = button("Advanced…", quiet=True, callback=self.advanced)
        form.addWidget(row(label("Standard server addresses are ready to use.", "muted"), None, self.advanced_button))
        self.info = label("", "muted", True); self.info.setMinimumHeight(34); layout.addWidget(self.info)
        self.use_button = button("Use this model", "check", True, self.save); layout.addWidget(self.use_button)
        layout.addWidget(label("A short test verifies your model before activation. Online providers receive the passages needed for your request.", "muted", True))
        self.provider.setCurrentIndex(self.provider.findData(self.app.config.get().provider))
        self.provider.currentIndexChanged.connect(self.load)
        self.model.currentTextChanged.connect(self.describe_model)
        self.load(); self.adjustSize()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().y() < 70 and self.windowHandle():
            self.windowHandle().startSystemMove()

    def reject(self):
        self.generation += 1
        super().reject()

    def load(self):
        self.generation += 1
        settings = self.app.config.get(self.provider.currentData())
        for name, b in self.preset_buttons.items(): b.setChecked(name == settings.provider)
        local = settings.provider in ("ollama", "lmstudio")
        self.provider_hint.setText("Runs on your computer. Start the server and load a model first." if local else "One key for many model providers, with live pricing and free-model filters." if settings.provider == "openrouter" else "Connect your own server using an OpenAI-compatible API." if settings.provider == "compatible" else "Ready to connect with your provider’s API key.")
        self.endpoint.setText(settings.endpoint); self.key.clear(); self.clear_key.setChecked(False)
        self.key_label.setVisible(not local); self.key.setVisible(not local)
        self.key.setPlaceholderText("Saved key hidden · paste to replace" if settings.key else "Paste your API key")
        self.key_hint.setText("No API key needed for the default local server." if local else "A key is saved on this computer." if settings.key else "Your key is saved locally after the model test succeeds.")
        self.input_chars.setText(str(settings.input_chars)); self.output_tokens.setText(str(settings.output_tokens))
        self.catalog = []; self.model.clear()
        cached = self.app.db.one("SELECT value FROM ui_state WHERE key=?", ("catalog_" + settings.provider,))
        cache_time = ""
        if cached:
            try:
                data = json.loads(cached["value"])
                if data.get("endpoint") == settings.endpoint:
                    self.catalog = data["models"]; cache_time = data.get("fetched_at", "")
            except (ValueError, KeyError, TypeError): pass
        if self.catalog: self.model.addItems([m["id"] for m in self.catalog])
        self.model.setEditText(settings.model)
        self.browse.setEnabled(bool(self.catalog)); self.describe_model()
        self.info.setText(f"Cached catalogue · {cache_time}. Connect to refresh." if cache_time else "Choose a provider, connect, then select your model.")

    def draft(self):
        return self.app.config.draft(self.provider.currentData(), self.model.currentText(), self.endpoint.text(),
            "" if self.clear_key.isChecked() else self.key.text() or None,
            int(self.input_chars.text()), int(self.output_tokens.text()))

    def operation(self, message, work, done):
        self.busy = True; self.controls.setEnabled(False); self.use_button.setEnabled(False); self.info.setText(message)
        generation = self.generation
        def guarded():
            try: return work(), None
            except Exception as exc: return None, str(exc)
        def finished(result):
            if self.generation != generation: return
            self.busy = False; self.controls.setEnabled(True); self.use_button.setEnabled(True)
            value, error = result
            if error: self.info.setText(error + " Your active setup is unchanged.")
            else: done(value)
        self.desktop.run(message, guarded, finished)

    def discover(self):
        if self.busy: return
        try: settings = self.draft()
        except Exception as exc: self.info.setText(str(exc)); return
        def work():
            provider = Provider(settings)
            status = provider.key_status() if settings.provider == "openrouter" else None
            return provider.catalog(), status
        def done(result):
            models, status = result
            self.catalog = models
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            cache = {"models": models, "endpoint": settings.endpoint, "fetched_at": timestamp}
            self.app.db.execute("INSERT OR REPLACE INTO ui_state VALUES(?,?)", ("catalog_" + settings.provider, json.dumps(cache)))
            self.model.clear(); self.model.addItems([m["id"] for m in models]); self.model.setEditText(settings.model)
            # Never silently select a paid model or OpenRouter’s random free router.
            self.browse.setEnabled(bool(models)); self.describe_model()
            account = ""
            if status is not None:
                account = " Key verified."
                remaining = status.get("limit_remaining")
                if remaining is not None: account += f" Key spending limit remaining: ${remaining}."
            self.info.setText(f"{len(models)} models loaded.{account} Choose a model, then use it." if models else "Connected, but no text models were returned. Load a local model or enter a model ID manually.")
            if models: self.pick_model()
        self.operation("Connecting and loading available models…", work, done)

    def pick_model(self):
        if not self.catalog: return
        picker = ModelPicker(self, self.catalog, self.model.currentText(), self.provider.currentData() == "openrouter")
        if picker.exec() == QDialog.Accepted: self.model.setEditText(picker.selected_id)

    def describe_model(self, *_):
        if not hasattr(self, "model_hint"): return
        model = next((m for m in self.catalog if m["id"] == self.model.currentText()), None)
        if not model:
            self.model_hint.setText("Model IDs can also be entered manually when discovery is unavailable."); return
        parts = []
        if model.get("free"): parts.append("Free token pricing · provider limits apply")
        elif model.get("pricing"):
            prices = model["pricing"]
            parts.append(f"{price_per_million(prices.get('prompt'))} in / {price_per_million(prices.get('completion'))} out per 1M tokens")
        if model.get("context_length"): parts.append(f"{context_label(model['context_length'])} context tokens")
        self.model_hint.setText(" · ".join(parts) or "Selected from the provider’s catalogue. Access will be tested.")

    def save(self, checked=False):
        if self.busy: return
        try:
            settings = self.draft()
            if not settings.model: raise ValueError("Choose a model or enter its exact ID first.")
        except Exception as exc: self.info.setText(str(exc)); return
        def done(_):
            self.app.config.save(settings.provider, settings.model, settings.endpoint, settings.key,
                input_chars=settings.input_chars, output_tokens=settings.output_tokens)
            self.key.clear(); self.clear_key.setChecked(False)
            self.key.setPlaceholderText("Saved key hidden · paste to replace" if settings.key else "Paste your API key")
            self.key_hint.setText("A key is saved on this computer." if settings.key else "Local connection saved.")
            self.info.setText(f"Connected · {PRESET_LABELS[settings.provider]} / {settings.model}. Ready for research.")
            self.desktop.connection_label.setText(f"{PRESET_LABELS[settings.provider]} · {settings.model}")
        self.operation("Testing this model before saving your connection…", lambda: Provider(settings).test(), done)

    def advanced(self):
        dialog = QDialog(self); dialog.setWindowTitle("Advanced AI settings"); dialog.setStyleSheet(LIGHT + "QDialog { background: #fff; }"); dialog.setMinimumWidth(510)
        form = QVBoxLayout(dialog); form.setContentsMargins(24, 24, 24, 24); form.setSpacing(12)
        form.addWidget(label("Advanced connection", "subheading"))
        endpoint = QLineEdit(self.endpoint.text()); form.addWidget(label("Server / API base URL")); form.addWidget(endpoint)
        form.addWidget(button("Restore provider address", callback=lambda: endpoint.setText(PROVIDERS[self.provider.currentData()][1])))
        chars = QSpinBox(); chars.setRange(12000, 200000); chars.setSingleStep(1000); chars.setValue(int(self.input_chars.text()))
        tokens = QSpinBox(); tokens.setRange(256, 32768); tokens.setSingleStep(256); tokens.setValue(int(self.output_tokens.text()))
        form.addWidget(label("Maximum input characters")); form.addWidget(chars)
        form.addWidget(label("Maximum output tokens")); form.addWidget(tokens)
        clear_key = QCheckBox("Use this server without a saved API key"); clear_key.setChecked(self.clear_key.isChecked()); form.addWidget(clear_key)
        clear_key.setVisible(not PROVIDERS[self.provider.currentData()][2])
        form.addWidget(label("These edits take effect only after Use this model succeeds.", "muted", True))
        form.addWidget(row(button("Cancel", callback=dialog.reject), None, button("Apply to setup", primary=True, callback=dialog.accept)))
        if dialog.exec() == QDialog.Accepted:
            changed_endpoint = endpoint.text().strip().rstrip("/") != self.endpoint.text()
            self.endpoint.setText(endpoint.text()); self.input_chars.setText(str(chars.value())); self.output_tokens.setText(str(tokens.value())); self.clear_key.setChecked(clear_key.isChecked())
            if changed_endpoint:
                self.catalog = []; self.browse.setEnabled(False); current = self.model.currentText(); self.model.clear(); self.model.setEditText(current)
                self.info.setText("Server address changed. Connect to refresh this server’s models.")
