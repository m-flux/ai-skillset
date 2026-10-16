import json
import httpx
import pytest
from forgebench.providers.ollama import OllamaProvider
from forgebench.schemas import TaskSpec


def test_ollama_structured_response(monkeypatch, tmp_path):
    response_body = {"model":"fake:latest","message":{"role":"assistant","content":json.dumps({
      "selected_skill":"python-bugfix","patch":{"path":"solution.py","old_text":"return 1","new_text":"return 2"},"summary":"fix it"})},
      "done":True,"prompt_eval_count":10,"eval_count":8}
    def fake_post(url, json, timeout):
        assert url.endswith("/api/chat")
        assert json["stream"] is False
        return httpx.Response(200, json=response_body, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    (tmp_path / "solution.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    task = TaskSpec(id="t", description="fix", fixture="x", target_file="solution.py", required_skill="python-bugfix")
    output = OllamaProvider(model="fake:latest").complete(task, "skill", tmp_path)
    assert output.model == "fake:latest"
    assert output.prompt_tokens == 10 and output.completion_tokens == 8


def test_ollama_invalid_json_rejected(monkeypatch, tmp_path):
    def fake_post(url, json, timeout):
        return httpx.Response(200, json={"message":{"content":"not-json"}}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    (tmp_path / "solution.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    task = TaskSpec(id="t", description="fix", fixture="x", target_file="solution.py", required_skill="python-bugfix")
    with pytest.raises(RuntimeError, match="invalid structured response"):
        OllamaProvider().complete(task, "skill", tmp_path)


def test_ollama_health(monkeypatch):
    def fake_get(url, timeout):
        return httpx.Response(200, json={"models":[{"name":"model:tag"}]}, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", fake_get)
    assert OllamaProvider().health()["models"] == ["model:tag"]
