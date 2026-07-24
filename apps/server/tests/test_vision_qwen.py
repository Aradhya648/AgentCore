"""QwenVLReader + build_vision_reader (AI协作白板.md §九.4).

Verifies the reader sends the board PNG as an OpenAI-compatible multimodal message
(``image_url`` data URL), parses the text reading back, maps upstream HTTP errors to
typed LLM errors, and that the factory only builds a reader when a key is configured.
Network is mocked via ``httpx.MockTransport`` (injected through the reader's ``transport``
seam) — no real DashScope calls.
"""

import json
from types import SimpleNamespace

import httpx
import pytest

from agentcore.core.errors import LLMAuthError, LLMError
from agentcore.vision import QwenVLReader, build_vision_reader

pytestmark = pytest.mark.anyio

_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mნ"  # opaque blob


def _reader(handler, **kwargs) -> QwenVLReader:
    return QwenVLReader(
        api_key="k",
        base_url="http://vision.invalid/v1",
        model="qwen-vl-max",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_read_sends_image_as_data_url_and_returns_text():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "qwen-vl-max",
                "choices": [{"message": {"content": "草图：登录 → 校验 → 首页"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1200, "completion_tokens": 40},
            },
        )

    reader = _reader(handler)
    reading = await reader.read(_PNG, "把这张手绘当 brief，描述结构与意图")

    assert reading.text == "草图：登录 → 校验 → 首页"
    # 读图入账 (§九.4 Gap ②): the reading carries the sub-call usage + model so board_read
    # can price it. The OpenAI usage block has no cache split, so cache_hit/miss stay 0 on
    # the raw usage — calculate_cost reconciles the whole prompt to a miss at pricing time.
    assert reading.model == "qwen-vl-max"
    assert reading.usage.input_tokens == 1200
    assert reading.usage.output_tokens == 40
    assert reading.usage.cache_hit_tokens == 0
    assert captured["url"].endswith("/chat/completions")
    body = captured["body"]
    assert body["model"] == "qwen-vl-max"
    assert body["stream"] is False
    parts = body["messages"][0]["content"]
    text_part = next(p for p in parts if p["type"] == "text")
    image_part = next(p for p in parts if p["type"] == "image_url")
    assert text_part["text"] == "把这张手绘当 brief，描述结构与意图"
    assert image_part["image_url"]["url"] == f"data:image/png;base64,{_PNG}"


async def test_read_parses_dashscope_cache_split():
    """DashScope reports the prefix-cache hit as OpenAI-style
    ``prompt_tokens_details.cached_tokens`` — the reader must surface it so the
    QWEN_VL_MAX cache_hit price applies instead of billing the whole prompt as a miss."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen-vl-max",
                "choices": [{"message": {"content": "看板读数"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 1200,
                    "completion_tokens": 40,
                    "prompt_tokens_details": {"cached_tokens": 900},
                },
            },
        )

    reading = await _reader(handler).read(_PNG, "读一下")
    assert reading.usage.cache_hit_tokens == 900
    assert reading.usage.cache_miss_tokens == 300


async def test_read_coerces_list_content_to_text():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": [{"type": "text", "text": "两个便签 + 一条连线"}]}}
                ]
            },
        )

    assert (await _reader(handler).read(_PNG, "读一下")).text == "两个便签 + 一条连线"


async def test_read_maps_401_to_auth_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(LLMAuthError):
        await _reader(handler).read(_PNG, "读一下")


async def test_read_empty_content_raises():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    with pytest.raises(LLMError, match="空内容"):
        await _reader(handler).read(_PNG, "读一下")


def test_build_vision_reader_none_without_key():
    cfg = SimpleNamespace(vision_api_key="")
    assert build_vision_reader(cfg) is None


def test_build_vision_reader_returns_qwen_with_key():
    cfg = SimpleNamespace(
        vision_api_key="sk-x",
        vision_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        vision_model="qwen-vl-max",
        vision_timeout_seconds=60.0,
    )
    reader = build_vision_reader(cfg)
    assert isinstance(reader, QwenVLReader)
