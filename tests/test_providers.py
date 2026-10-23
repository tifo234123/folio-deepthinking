import json
import httpx
import pytest
from folio.config import ProviderSettings, PROVIDERS
from folio.providers import Provider, ProviderError


@pytest.mark.parametrize("name", list(PROVIDERS))
def test_wire_contracts_and_selected_model(name):
    def respond(request):
        body = json.loads(request.content)
        assert "secret-test-key" not in request.url.query.decode()
        assert body.get("model", "chosen") == "chosen"
        if name == "openai":
            assert request.url.path.endswith("/responses") and body["store"] is False
            return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": "OK"}]}]})
        if name == "anthropic":
            assert request.headers["x-api-key"] == "secret-test-key"
            return httpx.Response(200, json={"content": [{"type": "text", "text": "OK"}]})
        if name == "gemini":
            assert request.headers["x-goog-api-key"] == "secret-test-key"
            assert request.url.path.endswith("/models/chosen:generateContent")
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "OK"}]}, "finishReason": "STOP"}]})
        if name == "ollama":
            assert request.url.path.endswith("/api/chat")
            return httpx.Response(200, json={"message": {"content": "OK"}})
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]})
    p = Provider(ProviderSettings(name, "chosen", PROVIDERS[name][1], "secret-test-key"), httpx.MockTransport(respond))
    assert p.test() == "OK"


def test_model_listing_success_is_not_model_validation():
    def respond(request):
        if request.method == "GET": return httpx.Response(200, json={"data": [{"id": "unusable"}]})
        return httpx.Response(404, json={"error": "secret-test-key must not leak"})
    p = Provider(ProviderSettings("nvidia", "unusable", PROVIDERS["nvidia"][1], "secret-test-key"), httpx.MockTransport(respond))
    assert p.models() == ["unusable"]
    with pytest.raises(ProviderError) as error: p.test()
    assert "secret-test-key" not in str(error.value)
    assert "404" in str(error.value)


def test_truncated_response_rejected():
    p = Provider(ProviderSettings("openrouter", "chosen", PROVIDERS["openrouter"][1], "key"),
                 httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]})))
    with pytest.raises(ProviderError, match="complete"): p.test()



def test_openrouter_catalog_metadata_and_key_privacy():
    def respond(request):
        assert request.headers['Authorization'] == 'Bearer private-key'
        if request.url.path.endswith('/key'):
            return httpx.Response(200, json={'data': {'label': 'private-label', 'hash': 'private-hash',
                'is_free_tier': False, 'limit': 20, 'limit_remaining': 12, 'usage': 8}})
        return httpx.Response(200, json={'data': [
            {'id': 'a/free', 'name': 'Free model', 'context_length': 128000,
             'top_provider': {'max_completion_tokens': 8192}, 'supported_parameters': ['tools'],
             'pricing': {'prompt': '0', 'completion': '0', 'request': '0'}},
            {'id': 'a/request-fee', 'pricing': {'prompt': '0', 'completion': '0', 'request': '0.01'}},
            {'id': 'a/unknown'},
            {'id': 'a/image', 'architecture': {'output_modalities': ['image']}}
        ]})
    provider = Provider(ProviderSettings('openrouter', '', PROVIDERS['openrouter'][1], 'private-key'), httpx.MockTransport(respond))
    models = {model['id']: model for model in provider.catalog()}
    assert models['a/free']['free'] and models['a/free']['context_length'] == 128000
    assert models['a/free']['max_output'] == 8192
    assert not models['a/request-fee']['free'] and not models['a/unknown']['free']
    assert 'a/image' not in models
    assert provider.key_status() == {'is_free_tier': False, 'limit': 20, 'limit_remaining': 12, 'usage': 8}


def test_price_display_and_free_detection():
    from folio.providers import price_per_million, zero_price
    assert price_per_million('0.0000025') == '$2.5'
    assert price_per_million('0') == '$0'
    assert price_per_million(None) == '—'
    assert price_per_million('-1') == 'Variable'
    assert price_per_million('nan') == 'Variable'
    assert not zero_price({'prompt': '0'})
    assert not zero_price({'prompt': 'unknown', 'completion': '0'})
    assert zero_price({'prompt': '0', 'completion': '0'})


@pytest.mark.parametrize("name,check", [
    ("openai", lambda b: b["text"]["format"]["type"] == "json_object"),
    ("gemini", lambda b: b["generationConfig"]["responseMimeType"] == "application/json"),
    ("ollama", lambda b: b["format"] == "json"),
    ("openrouter", lambda b: "response_format" not in b)])
def test_json_mode_only_where_documented(name, check):
    seen = []
    def respond(request):
        seen.append(json.loads(request.content))
        if name == "openai": return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": "{}"}]}]})
        if name == "gemini": return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}]})
        if name == "ollama": return httpx.Response(200, json={"message": {"content": "{}"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
    p = Provider(ProviderSettings(name, "chosen", PROVIDERS[name][1], "secret-test-key"), httpx.MockTransport(respond))
    p.complete("Return JSON.", [{"role": "user", "content": "x"}], json_mode=True)
    assert check(seen[0])


def test_parse_json_tolerates_surrounding_prose():
    from folio.providers import parse_json
    assert parse_json('Sure:\n{"a": 1}\nDone.') == {"a": 1}
    with pytest.raises(ValueError): parse_json("no object here")
