from dataclasses import dataclass
from pathlib import Path
import io
import os
import tempfile
from urllib.parse import urlparse

from dotenv import dotenv_values, set_key
from filelock import FileLock


PROVIDERS = {
    "ollama": ("Ollama (local)", "http://127.0.0.1:11434", False),
    "openai": ("OpenAI", "https://api.openai.com/v1", True),
    "anthropic": ("Anthropic Claude", "https://api.anthropic.com/v1", True),
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta", True),
    "nvidia": ("NVIDIA API", "https://integrate.api.nvidia.com/v1", True),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", True),
    "lmstudio": ("LM Studio (local)", "http://127.0.0.1:1234/v1", False),
    "compatible": ("Custom compatible API", "http://127.0.0.1:1234/v1", False),
}


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    model: str
    endpoint: str
    key: str = ""
    input_chars: int = 24000
    output_tokens: int = 4096

    def public(self):
        return {"provider": self.provider, "model": self.model, "endpoint": self.endpoint,
                "has_key": bool(self.key), "input_chars": self.input_chars,
                "output_tokens": self.output_tokens}


class Config:
    def __init__(self, home: Path):
        self.home = Path(home).expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / ".env"
        self.lock = FileLock(str(self.path) + ".lock")

    def values(self):
        return dict(dotenv_values(self.path, interpolate=False)) if self.path.exists() else {}

    def get(self, provider=None):
        values = self.values()
        provider = provider or values.get("FOLIO_ACTIVE_PROVIDER", "ollama")
        if provider not in PROVIDERS:
            raise ValueError("Unknown AI provider")
        prefix = f"FOLIO_{provider.upper()}_"
        return ProviderSettings(provider, values.get(prefix + "MODEL", "") or "",
                                values.get(prefix + "ENDPOINT") or PROVIDERS[provider][1],
                                values.get(prefix + "KEY", "") or "",
                                int(values.get(prefix + "INPUT_CHARS") or 24000),
                                int(values.get(prefix + "OUTPUT_TOKENS") or 4096))

    def draft(self, provider, model, endpoint=None, key=None,
              input_chars=24000, output_tokens=4096):
        """Validate a candidate without changing the active connection."""
        if provider not in PROVIDERS:
            raise ValueError("Unknown AI provider")
        endpoint = (endpoint or PROVIDERS[provider][1]).strip().rstrip("/")
        url = urlparse(endpoint)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Use an HTTP(S) base URL without credentials or query parameters")
        if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Remote AI endpoints require HTTPS")
        if not 12000 <= int(input_chars) <= 200000 or not 256 <= int(output_tokens) <= 32768:
            raise ValueError("Input budget must be 12000–200000 characters; output 256–32768 tokens")
        return ProviderSettings(provider, model.strip(), endpoint,
                                self.get(provider).key if key is None else key.strip(),
                                int(input_chars), int(output_tokens))

    def save(self, provider, model, endpoint=None, key=None, activate=True,
             input_chars=24000, output_tokens=4096):
        settings = self.draft(provider, model, endpoint, key, input_chars, output_tokens)
        endpoint = settings.endpoint
        prefix = f"FOLIO_{provider.upper()}_"
        updates = {prefix + "MODEL": model.strip(), prefix + "ENDPOINT": endpoint,
                   prefix + "INPUT_CHARS": str(input_chars), prefix + "OUTPUT_TOKENS": str(output_tokens)}
        if key is not None:
            updates[prefix + "KEY"] = key.strip()
        if activate:
            updates["FOLIO_ACTIVE_PROVIDER"] = provider
        self.update(updates)
        return self.get(provider)

    def update(self, updates):
        # One writer across desktop/CLI, atomic replacement, preserved unrelated lines.
        with self.lock:
            fd, name = tempfile.mkstemp(prefix=".env-", dir=self.home)
            temp = Path(name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    out.write(self.path.read_text() if self.path.exists() else "# Folio configuration\n")
                for key, value in updates.items():
                    set_key(str(temp), key, str(value), quote_mode="always")
                os.chmod(temp, 0o600)
                parsed = dotenv_values(stream=io.StringIO(temp.read_text()), interpolate=False)
                if any(parsed.get(k) != str(v) for k, v in updates.items()):
                    raise ValueError("Configuration could not be serialized safely")
                with temp.open("rb") as saved:
                    os.fsync(saved.fileno())
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)

    @property
    def library(self):
        return Path(self.values().get("FOLIO_LIBRARY") or self.home / "library").expanduser().resolve()

    def set_library(self, path):
        path = Path(path).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        # Existing book records retain their absolute managed paths.
        self.update({"FOLIO_LIBRARY": str(path)})
