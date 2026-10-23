"""Explicit, non-fallback provider adapters. No global environment credentials."""
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
import httpx
from .config import PROVIDERS, ProviderSettings


class ProviderError(RuntimeError):
    pass


class Provider:
    def __init__(self, settings: ProviderSettings, transport=None):
        self.settings = settings
        self.transport = transport

    def _headers(self):
        s = self.settings
        headers = {"Content-Type": "application/json"}
        if s.provider == "anthropic":
            headers.update({"x-api-key": s.key, "anthropic-version": "2023-06-01"})
        elif s.provider == "gemini":
            headers["x-goog-api-key"] = s.key
        elif s.key:
            headers["Authorization"] = "Bearer " + s.key
        return headers

    def _request(self, method, path, **kwargs):
        s = self.settings
        if PROVIDERS[s.provider][2] and not s.key:
            raise ProviderError("Add this provider's API key in AI settings")
        try:
            with httpx.Client(timeout=httpx.Timeout(180, connect=10), transport=self.transport,
                              follow_redirects=False, trust_env=False) as client:
                r = client.request(method, s.endpoint + path, headers=self._headers(), **kwargs)
                if r.status_code >= 300:
                    reason = {401: "Check the API key", 403: "Check key permissions and model access",
                              404: "Check the endpoint and selected model", 429: "Rate or usage limit reached; wait before retrying",
                              502: "Provider gateway temporarily unavailable; retry later",
                              503: "Provider temporarily overloaded or unavailable; retry later",
                              504: "Provider gateway timed out; retry later"}.get(r.status_code, "Provider rejected the request")
                    raise ProviderError(f"{PROVIDERS[s.provider][0]}: {reason} (HTTP {r.status_code})")
                return r.json()
        except httpx.TimeoutException:
            raise ProviderError("The provider timed out. Completed work is saved; retry when available.") from None
        except httpx.RequestError:
            raise ProviderError("Cannot connect to the provider. Check the server address and connection.") from None
        except (ValueError, KeyError, TypeError):
            raise ProviderError("The provider returned an unreadable response") from None

    def models(self):
        return [m["id"] for m in self.catalog()]

    def catalog(self):
        p = self.settings.provider
        data = self._request("GET", "/api/tags" if p == "ollama" else "/models")
        if p == "ollama":
            rows = [{"id": m["name"], "name": m["name"], "local": True} for m in data.get("models", [])]
        elif p == "gemini":
            rows = [{"id": m["name"].removeprefix("models/"), "name": m.get("displayName", m["name"]),
                     "context_length": m.get("inputTokenLimit"), "max_output": m.get("outputTokenLimit")}
                    for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
        else:
            rows = []
            for m in data.get("data", []):
                model_id = m.get("id")
                if not model_id: continue
                modalities = m.get("architecture", {}).get("output_modalities", ["text"])
                if "text" not in modalities: continue
                # Discovery only: inference testing still determines compatibility.
                if p == "openai" and any(term in model_id.lower() for term in ("embedding", "whisper", "tts", "dall-e", "image", "transcribe", "realtime", "moderation", "audio")):
                    continue
                pricing = m.get("pricing") or {}
                row = {"id": model_id, "name": m.get("name") or m.get("display_name") or model_id,
                       "context_length": m.get("context_length"),
                       "max_output": (m.get("top_provider") or {}).get("max_completion_tokens"),
                       "supported_parameters": m.get("supported_parameters") or [],
                       "description": str(m.get("description") or "")[:1600],
                       "pricing": {k: str(pricing[k]) for k in ("prompt", "completion", "request") if pricing.get(k) is not None}}
                row["free"] = zero_price(row["pricing"])
                rows.append(row)
        return sorted(rows, key=lambda m: m["name"].casefold())

    def key_status(self):
        if self.settings.provider != "openrouter":
            raise ProviderError("Key-status inspection is available for OpenRouter")
        data = self._request("GET", "/key").get("data", {})
        # Do not propagate key labels, hashes, account identity, or metadata.
        return {k: data.get(k) for k in ("is_free_tier", "limit", "limit_remaining", "usage")}

    def complete(self, system, messages, max_tokens=None, json_mode=False):
        s = self.settings
        if not s.model:
            raise ProviderError("Choose a model in AI settings first")
        size = len(system) + sum(len(m["content"]) for m in messages)
        if size > s.input_chars:
            raise ProviderError("Request exceeds the configured input budget. Select a smaller scope or increase the budget for this model.")
        tokens = max_tokens or s.output_tokens
        p = s.provider
        if p == "openai":
            data = self._request("POST", "/responses", json={"model": s.model, "instructions": system,
                "input": messages, "max_output_tokens": tokens, "store": False,
                **({"text": {"format": {"type": "json_object"}}} if json_mode else {})})
            if data.get("status") == "incomplete":
                raise ProviderError("Model output was incomplete; increase the output limit or use a smaller scope")
            result = "".join(c.get("text", "") for item in data.get("output", [])
                             for c in item.get("content", []) if c.get("type") == "output_text")
        elif p == "anthropic":
            data = self._request("POST", "/messages", json={"model": s.model, "system": system,
                "messages": messages, "max_tokens": tokens})
            if data.get("stop_reason") == "max_tokens":
                raise ProviderError("Model output was truncated; increase the output limit")
            result = "".join(c.get("text", "") for c in data.get("content", []) if c.get("type") == "text")
        elif p == "gemini":
            data = self._request("POST", "/models/" + quote(s.model, safe="") + ":generateContent", json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages],
                "generationConfig": {"maxOutputTokens": tokens, **({"responseMimeType": "application/json"} if json_mode else {})}})
            candidates = data.get("candidates", [])
            if not candidates or candidates[0].get("finishReason") not in ("STOP", None):
                raise ProviderError("Gemini did not return a complete answer")
            result = "".join(c.get("text", "") for c in candidates[0].get("content", {}).get("parts", []) if not c.get("thought"))
        else:
            body = {"model": s.model, "messages": [{"role": "system", "content": system}] + messages, "stream": False}
            if p == "ollama":
                body["options"] = {"num_predict": tokens}
                if json_mode: body["format"] = "json"
                data = self._request("POST", "/api/chat", json=body)
                if data.get("done_reason") == "length":
                    raise ProviderError("Model output was truncated; increase the output limit")
                result = data.get("message", {}).get("content", "")
            else:
                # JSON mode support varies across compatible servers; validation handles these.
                body["max_tokens"] = tokens
                data = self._request("POST", "/chat/completions", json=body)
                choices = data.get("choices", [])
                if not choices or choices[0].get("finish_reason") not in ("stop", None):
                    raise ProviderError("The model did not return a complete answer")
                result = choices[0].get("message", {}).get("content", "")
        if not isinstance(result, str) or not result.strip():
            raise ProviderError("The model returned no text. Check its capabilities and output limit.")
        return result

    def test(self):
        # Model inference is tested independently from model-list permissions.
        return self.complete("Respond briefly.", [{"role": "user", "content": "Reply with OK."}], max_tokens=256)


def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    # Tolerate prose around a single JSON object; schema validation still applies.
    start, end = text.find("{"), text.rfind("}")
    try:
        if start < 0 or end <= start: raise ValueError
        return json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        raise ValueError("The model returned invalid JSON; no changes were applied. Try another model or a smaller scope.") from None


def zero_price(pricing):
    if "prompt" not in pricing or "completion" not in pricing: return False
    try:
        return all(Decimal(str(pricing.get(k, "0"))) == 0 for k in ("prompt", "completion", "request"))
    except (InvalidOperation, ValueError): return False


def price_per_million(value):
    if value is None: return "—"
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0: return "Variable"
        return "$" + format(number * 1000000, ".4f").rstrip("0").rstrip(".")
    except (InvalidOperation, ValueError): return "—"
