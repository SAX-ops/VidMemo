import json
import os
from unittest.mock import MagicMock

import pytest

from services.summarizer import (
    _is_bilibili_url,
    _parse_vtt,
    _pick_best_subtitle,
    _time_to_seconds,
)


def test_is_bilibili_url_matches_domains():
    assert _is_bilibili_url("https://www.bilibili.com/video/BV1xx411c7mD")
    assert _is_bilibili_url("https://bilibili.com/video/BV1xx411c7mD")
    assert _is_bilibili_url("https://b23.tv/abc123")
    assert _is_bilibili_url("https://www.bilibili.com/bangumi/play/ep123")


def test_is_bilibili_url_rejects_others():
    assert not _is_bilibili_url("https://www.youtube.com/watch?v=xxx")
    assert not _is_bilibili_url("https://www.douyin.com/video/123")
    assert not _is_bilibili_url("https://example.com")


def test_time_to_seconds():
    assert _time_to_seconds("00:00:00.000") == 0.0
    assert _time_to_seconds("00:01:30.500") == 90.5
    assert _time_to_seconds("01:02:03.456") == 3723.456


def test_parse_vtt_simple(tmp_path):
    f = tmp_path / "subs.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "Hello world\n\n"
        "00:00:04.000 --> 00:00:06.500\n"
        "Second line\n",
        encoding="utf-8",
    )
    segs = _parse_vtt(str(f))
    assert len(segs) == 2
    assert segs[0]["start"] == 1.0
    assert segs[0]["end"] == 3.0
    assert segs[0]["text"] == "Hello world"
    assert segs[1]["start"] == 4.0
    assert segs[1]["end"] == 6.5


def test_parse_vtt_strips_html_tags(tmp_path):
    f = tmp_path / "subs.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "<c.color>Colored</c> text\n",
        encoding="utf-8",
    )
    segs = _parse_vtt(str(f))
    assert segs[0]["text"] == "Colored text"


def test_parse_vtt_dedup_consecutive(tmp_path):
    f = tmp_path / "subs.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "Same text\n\n"
        "00:00:02.500 --> 00:00:03.500\n"
        "Same text\n\n"
        "00:00:04.000 --> 00:00:05.000\n"
        "Different\n",
        encoding="utf-8",
    )
    segs = _parse_vtt(str(f))
    assert len(segs) == 2
    assert segs[0]["text"] == "Same text"
    assert segs[1]["text"] == "Different"


def test_pick_prefers_manual_zh_hans():
    manual = {
        "en": [{"ext": "vtt", "url": "u-en"}],
        "zh-Hans": [{"ext": "vtt", "url": "u-zh"}],
    }
    auto = {}
    lang, url, kind, is_target = _pick_best_subtitle(manual, auto, "zh")
    assert lang == "zh-Hans"
    assert url == "u-zh"
    assert kind == "manual"
    assert is_target is True


def test_pick_falls_back_to_other_lang_with_flag():
    manual = {"en": [{"ext": "vtt", "url": "u-en"}]}
    auto = {}
    lang, url, kind, is_target = _pick_best_subtitle(manual, auto, "zh")
    assert lang == "en"
    assert url == "u-en"
    assert kind == "manual"
    assert is_target is False


def test_pick_falls_back_to_auto_when_no_manual():
    manual = {}
    auto = {"zh-Hans": [{"ext": "vtt", "url": "u-zh-auto"}]}
    lang, url, kind, is_target = _pick_best_subtitle(manual, auto, "zh")
    assert lang == "zh-Hans"
    assert kind == "auto"
    assert is_target is True


def test_pick_returns_empty_when_no_subtitles():
    lang, url, kind, is_target = _pick_best_subtitle({}, {}, "zh")
    assert lang == ""
    assert url is None
    assert is_target is False


@pytest.mark.network
def test_extract_bilibili_real_video():
    """Hit the real B站 API. Skip when offline."""
    from services.summarizer import _extract_bilibili

    result = _extract_bilibili("https://www.bilibili.com/video/BV1GJ411x7h7")
    assert result["has_subtitle"] is True
    assert result["language"] in ("zh-Hans", "zh", "ai-zh")
    assert result["subtitle_type"] in ("manual", "auto")
    assert len(result["segments"]) > 0
    assert result["segments"][0]["start"] >= 0
    assert result["segments"][0]["text"]  # non-empty


def test_extract_returns_bilibili_result(monkeypatch):
    """When B站 extractor returns a result, use it directly without calling yt-dlp."""
    from services.summarizer import SubtitleExtractor

    bilibili_result = {
        "has_subtitle": True, "language": "zh-Hans", "subtitle_type": "manual",
        "is_target_language": True, "fallback_mode": None,
        "segments": [{"start": 0.0, "end": 1.0, "text": "你好"}],
        "full_text": "你好",
    }
    monkeypatch.setattr("services.summarizer._extract_bilibili", lambda url: bilibili_result)
    mock_info = MagicMock()
    monkeypatch.setattr("services.summarizer._get_video_info", mock_info)

    result = SubtitleExtractor().extract("https://www.bilibili.com/video/BV1xx")
    assert result["has_subtitle"] is True
    assert result["language"] == "zh-Hans"
    assert not mock_info.called  # B站 short-circuit: yt-dlp must not be called


def test_extract_falls_through_to_ytdlp_when_bilibili_empty(monkeypatch):
    """B站 returns no subtitles → fall through to yt-dlp path."""
    from services.summarizer import SubtitleExtractor

    empty_bili = {
        "has_subtitle": False, "language": "", "subtitle_type": "none",
        "is_target_language": True, "fallback_mode": None, "segments": [], "full_text": "",
    }
    fake_info = {
        "subtitles": {"zh-Hans": [{"ext": "vtt", "url": "u1"}]},
        "automatic_captions": {},
    }
    monkeypatch.setattr("services.summarizer._extract_bilibili", lambda url: empty_bili)
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)
    monkeypatch.setattr(
        "services.summarizer._download_and_parse",
        lambda url, lang, sub_type: [{"start": 0.0, "end": 1.0, "text": f"yt-{lang}"}],
    )

    result = SubtitleExtractor().extract("https://www.bilibili.com/video/BV1xx-no-sub", language="zh")
    assert result["has_subtitle"] is True
    assert result["language"] == "zh-Hans"
    assert result["full_text"] == "yt-zh-Hans"


def test_extract_falls_back_to_ytdlp_for_non_bilibili(monkeypatch):
    """YouTube URLs go through yt-dlp; subtitles selected by priority."""
    from services.summarizer import SubtitleExtractor

    fake_info = {
        "subtitles": {"zh-Hans": [{"ext": "vtt", "url": "u1"}]},
        "automatic_captions": {"en": [{"ext": "vtt", "url": "u2"}]},
    }
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)
    monkeypatch.setattr(
        "services.summarizer._download_and_parse",
        lambda url, lang, sub_type: [{"start": 0.0, "end": 1.0, "text": f"text-{lang}"}],
    )

    result = SubtitleExtractor().extract("https://www.youtube.com/watch?v=xxx", language="zh")
    assert result["has_subtitle"] is True
    assert result["language"] == "zh-Hans"
    assert result["is_target_language"] is True
    assert result["full_text"] == "text-zh-Hans"


def test_extract_no_subtitles_anywhere_returns_metadata_fallback(monkeypatch):
    """No subtitles + no metadata at all → has_subtitle=False, fallback_mode=None (caller decides)."""
    from services.summarizer import SubtitleExtractor

    fake_info = {"subtitles": {}, "automatic_captions": {}}
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)

    result = SubtitleExtractor().extract("https://www.youtube.com/watch?v=xxx")
    assert result["has_subtitle"] is False
    assert result["language"] == ""
    assert result["full_text"] == ""


def test_extract_truncates_full_text_to_15000_chars(monkeypatch):
    from services.summarizer import SubtitleExtractor

    long_text = "x" * 20000
    fake_info = {
        "subtitles": {"zh": [{"ext": "vtt", "url": "u1"}]},
        "automatic_captions": {},
    }
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)
    monkeypatch.setattr(
        "services.summarizer._download_and_parse",
        lambda url, lang, sub_type: [{"start": 0.0, "end": 1.0, "text": long_text}],
    )

    result = SubtitleExtractor().extract("https://www.youtube.com/watch?v=xxx", language="zh")
    assert len(result["full_text"]) == 15000


def test_build_summarizer_raises_without_api_key_when_not_mock(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import build_summarizer
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_summarizer()


def test_build_summarizer_returns_mock_when_env_set(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SUMMARY_MOCK", "true")

    from services.summarizer import build_summarizer, MockSummarizer
    s = build_summarizer()
    assert isinstance(s, MockSummarizer)


def test_build_summarizer_returns_real_with_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import build_summarizer, VideoSummarizer
    s = build_summarizer()
    assert isinstance(s, VideoSummarizer)


class FakeChunk:
    def __init__(self, content):
        self.choices = [type("Choice", (), {"delta": type("Delta", (), {"content": content})()})()]


class FakeStreamingResponse:
    def __init__(self, tokens):
        self._tokens = tokens

    def __iter__(self):
        return iter([FakeChunk(t) for t in self._tokens])


def test_summarize_stream_yields_all_tokens(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_MODEL", "fake-model")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    s.client.chat.completions.create = lambda **kwargs: FakeStreamingResponse(["Hi", " there", "!"])

    tokens = list(s.summarize_stream("subtitle text here", "zh"))
    assert "".join(tokens) == "Hi there!"


def test_summarize_stream_uses_standard_prompt_for_subtitles(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["model"] = kwargs.get("model")
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("字幕内容", "zh", has_subtitle=True))
    prompt = captured["messages"][1]["content"]
    assert "视频概述" in prompt
    assert "视频大纲" in prompt
    assert "字幕内容" in prompt


def test_summarize_stream_uses_fallback_prompt_without_subtitles(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("video title here", "zh", has_subtitle=False, video_meta={"title": "X", "duration": 600}))
    prompt = captured["messages"][1]["content"]
    assert "没有可用的字幕" in prompt
    assert "X" in prompt


def test_summarize_stream_uses_english_hint_when_language_not_zh(monkeypatch):
    """I1: language='en' should use '与原文相同的语言' instead of '中文'."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("English subtitles", "en", has_subtitle=True))
    prompt = captured["messages"][1]["content"]
    assert "与原文相同的语言" in prompt
    assert "中文" not in prompt


def test_summarize_stream_fallback_handles_none_video_meta(monkeypatch):
    """I2: video_meta=None should produce '（未知）' sentinels for title/platform."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("placeholder", "zh", has_subtitle=False, video_meta=None))
    prompt = captured["messages"][1]["content"]
    assert "没有可用的字幕" in prompt
    assert "（未知）" in prompt


def test_summarize_stream_uses_chinese_system_prompt(monkeypatch):
    """I3: messages[0] should be a system message with the Chinese assistant persona."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("字幕", "zh", has_subtitle=True))
    system_msg = captured["messages"][0]
    assert system_msg["role"] == "system"
    assert "视频内容分析助手" in system_msg["content"]


def test_summarize_stream_standard_prompt_is_distinct_from_mock_body(monkeypatch):
    """I4: assert distinct-header strings (not the same as MockSummarizer.BODY)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer, MockSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("字幕内容", "zh", has_subtitle=True))
    prompt = captured["messages"][1]["content"]
    # "结构化深度总结" is unique to SUMMARY_PROMPT_STANDARD (not in MockSummarizer.BODY)
    assert "结构化深度总结" in prompt
    # Make sure we did NOT accidentally return the unformatted template
    # (note: SUMMARY_PROMPT_STANDARD intentionally has {{...}} which renders to {...} in
    # the JSON example, so we check the placeholders directly instead of bare braces)
    assert "{language}" not in prompt
    assert "{subtitle}" not in prompt
    assert "{duration}" not in prompt
    # Sanity: prompt is substantively different from mock body
    assert len(prompt) != len(MockSummarizer.BODY)


def test_standard_prompt_enforces_markdown_h2_headers():
    """Regression: MiMo previously emitted `1. 视频概述` instead of `## 视频概述`.
    Prompt must use `##` as the main section marker and explicitly forbid
    numbered-list style."""
    from services.summarizer import SUMMARY_PROMPT_STANDARD
    p = SUMMARY_PROMPT_STANDARD
    # Use `## ` (markdown H2) as the canonical main-section marker
    assert "## 视频概述" in p
    assert "## 视频大纲" in p
    assert "## 总结" in p
    # Must contain a full JSON example with the correct outer braces
    assert '{{"outline":' in p
    # Must explicitly forbid the wrong style so the LLM sees a DO/DON'T
    assert "不要" in p  # "do not write 1. 视频概述"


def test_standard_prompt_has_full_output_example():
    """The prompt should embed a complete expected-output example so the LLM
    has a concrete shape to imitate (avoids the MiMo bug where it dropped
    section markers and the JSON outer braces)."""
    from services.summarizer import SUMMARY_PROMPT_STANDARD
    p = SUMMARY_PROMPT_STANDARD
    # The example block should show the exact "## 视频概述\n(...)" pattern
    assert "## 视频概述" in p
    assert "## 总结" in p
    assert "## 视频大纲" in p
    # The example should show a JSON code fence with the 2-level outline shape
    assert "```json" in p
    assert "{{\"outline\":" in p
    assert "{{\"timestamp\":" in p
    assert "\"part_outline\":" in p
    assert "\"content\":" in p


def test_summarize_stream_filters_none_and_empty_chunk_content(monkeypatch):
    """I5: chunks with None or '' content should be filtered out (OpenAI emits these)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    s.client.chat.completions.create = lambda **kwargs: FakeStreamingResponse(["", None, "Hi", None, " there", ""])

    tokens = list(s.summarize_stream("subtitle text", "zh"))
    assert "".join(tokens) == "Hi there"
    # No literal "None" string leaked through
    assert "None" not in "".join(tokens)


def test_mock_summarizer_streams_body_and_includes_json():
    from services.summarizer import MockSummarizer
    s = MockSummarizer()
    s.DELAY_MS = 0  # instant for test
    tokens = list(s.summarize_stream("ignored", "zh"))
    body = "".join(tokens)
    assert "## 视频概述" in body
    assert '"outline"' in body
    assert '"part_outline"' in body
    assert body.endswith("```\n")


from services.summarizer import parse_outline_json


def test_parse_outline_json_valid():
    body = (
        "## 视频概述\nhi\n"
        "```json\n"
        '{"outline": [{"title": "开场", "timestamp": 0, "part_outline": [{"timestamp": 5, "content": "要点1"}]}, '
        '{"title": "中段", "timestamp": 90, "part_outline": [{"timestamp": 95, "content": "要点2"}]}]}\n'
        "```\n"
    )
    md, outline = parse_outline_json(body)
    assert "## 视频概述" in md
    assert "```json" not in md
    assert len(outline) == 2
    assert outline[0]["title"] == "开场"
    assert outline[0]["timestamp"] == 0
    assert outline[0]["part_outline"] == [{"timestamp": 5, "content": "要点1"}]
    assert outline[1]["title"] == "中段"
    assert outline[1]["timestamp"] == 90


def test_parse_outline_json_no_json_block():
    body = "## 视频概述\nno outline here"
    md, outline = parse_outline_json(body)
    assert md == body
    assert outline == []


def test_parse_outline_json_invalid_returns_empty(caplog):
    import logging
    body = "## 视频概述\n```json\n{this is not valid json}\n```\n"
    with caplog.at_level(logging.WARNING):
        md, outline = parse_outline_json(body)
    assert "## 视频概述" in md
    assert outline == []
    assert "parse_outline_json" in caplog.text  # locks in the WARNING contract


def test_parse_outline_json_strips_preceding_markdown():
    body = (
        "Some intro\n```json\n"
        + json.dumps({"outline": [{"title": "x", "timestamp": 5, "part_outline": [{"timestamp": 5, "content": "a"}]}]})
        + "\n```"
    )
    md, outline = parse_outline_json(body)
    assert "Some intro" in md
    assert len(outline) == 1
    assert outline[0]["title"] == "x"


def test_parse_outline_json_coerces_types():
    """String timestamps from a sloppy LLM should be coerced to int."""
    body = (
        "```json\n"
        '{"outline": [{"title": "x", "timestamp": "30", "part_outline": '
        '[{"timestamp": "35", "content": "c"}, {"timestamp": "40", "content": "d"}]}]}\n'
        "```\n"
    )
    _, outline = parse_outline_json(body)
    assert len(outline) == 1
    assert outline[0]["timestamp"] == 30
    assert outline[0]["part_outline"][0]["timestamp"] == 35


def test_parse_outline_json_drops_empty_part_outline():
    """Sections with empty or missing part_outline are dropped (avoids empty
    chapter rows in the UI)."""
    body = (
        "```json\n"
        '{"outline": [\n'
        '  {"title": "ok", "timestamp": 0, "part_outline": [{"timestamp": 0, "content": "a"}]},\n'
        '  {"title": "empty_parts", "timestamp": 90, "part_outline": []},\n'
        '  {"title": "no_parts_key", "timestamp": 180}\n'
        ']}\n'
        "```\n"
    )
    _, outline = parse_outline_json(body)
    assert len(outline) == 1
    assert outline[0]["title"] == "ok"


def test_parse_outline_json_drops_malformed_sections():
    """Sections missing required fields (title, timestamp) are silently dropped."""
    body = (
        "```json\n"
        '{"outline": [\n'
        '  {"title": "ok", "timestamp": 0, "part_outline": [{"timestamp": 0, "content": "a"}]},\n'
        '  {"timestamp": 90, "part_outline": [{"timestamp": 90, "content": "b"}]},\n'
        '  {"title": "no_timestamp", "part_outline": [{"timestamp": 0, "content": "c"}]},\n'
        '  "not a dict"\n'
        ']}\n'
        "```\n"
    )
    _, outline = parse_outline_json(body)
    assert len(outline) == 1
    assert outline[0]["title"] == "ok"


def test_parse_outline_json_lenient_no_code_fence():
    """Lenient extraction finds outline JSON without a code fence."""
    body = (
        "## Overview\n"
        "This is a test video.\n\n"
        '{"outline": [{"title": "Intro", "timestamp": 0, "part_outline": '
        '[{"timestamp": 0, "content": "Point 1"}]}]}\n'
    )
    md, outline = parse_outline_json(body)
    assert "## Overview" in md
    assert '{"outline"' not in md  # JSON removed from markdown
    assert len(outline) == 1
    assert outline[0]["title"] == "Intro"
    assert outline[0]["part_outline"][0]["content"] == "Point 1"


def test_parse_outline_json_lenient_nested_braces():
    """Lenient extraction handles nested JSON objects."""
    body = (
        "## Overview\n"
        "Test.\n\n"
        '{"outline": [{"title": "A", "timestamp": 0, "part_outline": '
        '[{"timestamp": 10, "content": "Feature demo"}]}]}\n'
    )
    md, outline = parse_outline_json(body)
    assert '{"outline"' not in md
    assert len(outline) == 1
    assert outline[0]["title"] == "A"
    assert outline[0]["part_outline"][0]["content"] == "Feature demo"


def test_parse_outline_json_lenient_invalid_json_warns(caplog):
    """Lenient extraction finds a JSON-like block but its not valid JSON.
    Should strip it from markdown and return empty outline with WARNING."""
    body = (
        "## Overview\n"
        "Test.\n\n"
        '{"outline": [NOT VALID JSON]}\n'
    )
    with caplog.at_level("WARNING"):
        md, outline = parse_outline_json(body)
    assert '{"outline"' not in md
    assert outline == []
    assert "parse_outline_json" in caplog.text


def test_parse_outline_json_strips_tail_section_when_no_json_found(caplog):
    """When the LLM produces a 视频大纲 heading but no parseable JSON, the
    final defensive pass must still strip the section so users never see
    a trailing JSON blob."""
    import logging
    body = (
        "## 视频概述\n这是概述。\n\n"
        "## 总结\n这是总结。\n\n"
        "## 视频大纲\n"
        '{"title": "未闭合的 JSON 残留..."}\n'
    )
    with caplog.at_level(logging.WARNING):
        md, outline = parse_outline_json(body)
    assert "## 视频概述" in md
    assert "## 总结" in md
    assert "## 视频大纲" not in md
    assert "未闭合" not in md
    assert "{" not in md  # leftover JSON brace is gone
    assert outline == []


def test_parse_outline_json_strips_lenient_heading_no_h2_prefix():
    """Lenient match: a light LLM may drop the `##` prefix on 视频大纲
    (e.g. output `视频大纲` or `### 视频大纲`). The defensive pass must
    still strip the trailing section."""
    body = (
        "## 视频概述\nhi\n\n"
        "视频大纲\n"
        '{"outline": [{"title": "x", "timestamp": 0, "part_outline": [{"timestamp": 0, "content": "a"}]}]}\n'
    )
    md, outline = parse_outline_json(body)
    # Outline was successfully extracted; section removed by strategy 2.
    assert len(outline) == 1
    assert "视频大纲" not in md
    assert "{" not in md


def test_parse_outline_json_strips_corrupted_heading_keeps_body():
    """Real-world corruption: light LLM sometimes garbles the section
    header (e.g. `频大纲json": [...]` — the leading `## 视` was eaten and
    the JSON starts inline). Both the corrupted header and the JSON
    must be removed from the markdown body."""
    body = (
        "## 视频概述\n"
        "故事化的叙述，从单机架构开始...\n\n"
        "## 总结\n"
        "以生动故事串联起核心概念。\n\n"
        '频大纲json": [{"title": "架构演进起点", "timestamp": 0, '
        '"part_outline": [{"timestamp": 0, "content": "单机"}]}]\n'
    )
    md, outline = parse_outline_json(body)
    assert "## 视频概述" in md
    assert "## 总结" in md
    assert "频大纲" not in md
    assert "架构演进起点" not in md
    assert '"outline"' not in md
    assert "{" not in md
    assert outline == []  # JSON was too corrupted for balanced extraction


# --- fix_outline_timestamps ----------------------------------------------------

from services.summarizer import fix_outline_timestamps


def test_fix_outline_timestamps_grounds_to_keyword_match():
    """Keyword search always grounds timestamps to the actual subtitle
    timeline, even when the LLM's guess is close."""
    outline = [
        {"title": "项目介绍", "timestamp": 0, "part_outline": [
            {"timestamp": 3, "content": "开头介绍项目"},
        ]},
    ]
    segments = [
        {"start": 3.0, "end": 5.0, "text": "这是项目介绍的开头"},
    ]
    fix_outline_timestamps(outline, segments, 100)
    # Chapter: keyword "项目" matches at 3.0s
    assert outline[0]["timestamp"] == 3
    assert outline[0]["part_outline"][0]["timestamp"] == 3


def test_fix_outline_timestamps_overrides_incorrect_llm_guesses():
    """Light LLMs (mimo-v2-flash) hand out evenly-spaced guesses that
    don't correspond to actual content. Keyword search in the subtitle
    timeline must override those guesses."""
    outline = [
        {"title": "项目介绍", "timestamp": 0, "part_outline": [
            {"timestamp": 30, "content": "介绍项目背景"},  # LLM guess: 30s
            {"timestamp": 60, "content": "介绍项目背景"},  # LLM guess: 60s
        ]},
        {"title": "AI 驱动开发", "timestamp": 90, "part_outline": [
            {"timestamp": 120, "content": "Cursor 工具"},   # LLM guess: 120s, actual 86s
        ]},
    ]
    segments = [
        {"start": 3.0, "end": 5.0, "text": "我做了个项目介绍"},
        {"start": 86.0, "end": 88.0, "text": "使用 Cursor 工具开发"},
    ]
    fix_outline_timestamps(outline, segments, 200)
    # Chapter 1: "项目介绍" should be grounded to 3.0 (where 项目介绍 appears)
    assert outline[0]["timestamp"] == 3
    # Part 1: "介绍项目背景" — keywords "项目" and "介绍" match the [3.0] segment
    assert outline[0]["part_outline"][0]["timestamp"] == 3
    # Part 2: same content — keyword match is also 3, but "ensure increasing"
    # bumps it to 4 since part 1 already occupies 3
    assert outline[0]["part_outline"][1]["timestamp"] == 4
    # Chapter 2: "AI 驱动开发" — keywords "AI" + "驱动" + "开发" — first match
    # is the 3s segment (has "项目" but not "AI" or "驱动"). "AI" is in 86s seg.
    # Use the matching segment for "AI" (86s) or "开发" (also 86s).
    assert outline[1]["timestamp"] == 86  # keyword hit: "AI" + "驱动" + "开发" all match at 86s
    # Part 1: "Cursor 工具" → 86s (where Cursor appears)
    assert outline[1]["part_outline"][0]["timestamp"] == 86


def test_fix_outline_timestamps_clamps_out_of_bounds_llm_guesses():
    """LLM guesses beyond video duration must be clamped, not shipped as-is."""
    outline = [
        {"title": "项目部署", "timestamp": 1000, "part_outline": [  # 1000s in a 200s video
            {"timestamp": 240, "content": "推广教程"},  # 240s in a 200s video
        ]},
    ]
    segments = [
        {"start": 0.0, "end": 2.0, "text": "项目"},
    ]
    fix_outline_timestamps(outline, segments, 200)
    # Chapter: keyword "项目" matches the 0.0 segment, so it goes to 0
    # (LLM guess 1000 is discarded as out of bounds)
    assert outline[0]["timestamp"] == 0
    # Part: no keyword "推广" or "教程" in segments; LLM guess 240 is
    # out of bounds → fallback to even distribution within chapter window
    part_ts = outline[0]["part_outline"][0]["timestamp"]
    assert 0 <= part_ts < 200


def test_fix_outline_timestamps_uses_llm_when_keyword_misses():
    """When keyword search finds nothing, the LLM's guess is the next-best
    signal — use it as long as it's in range."""
    outline = [
        {"title": "模糊章节", "timestamp": 75, "part_outline": [
            {"timestamp": 80, "content": "模糊要点"},
        ]},
    ]
    # Subtitle text deliberately does NOT contain any keyword from "模糊章节" or "模糊要点"
    segments = [
        {"start": 0.0, "end": 2.0, "text": "完全无关的内容"},
        {"start": 60.0, "end": 62.0, "text": "另一段无关内容"},
        {"start": 90.0, "end": 92.0, "text": "再来一段"},
    ]
    fix_outline_timestamps(outline, segments, 200)
    # LLM guesses (75, 80) are in range, no keyword hit → use them
    assert outline[0]["timestamp"] == 75
    assert outline[0]["part_outline"][0]["timestamp"] == 80


def test_fix_outline_timestamps_real_case_github_docs_video():
    """The GitHub 文档翻译平台 video (BV1mAAmzqEfP, 210s). The LLM produced
    evenly-spaced guesses (0/30/60/90/120/150/180/210/240) — the last
    timestamp is BEYOND the video duration, and most are at the wrong
    positions. Keyword search in the actual subtitle must ground them."""
    segments = [
        # Chapter 1: 项目介绍与核心功能 (covers GitHub/文档/翻译/AI)
        {"start": 3.0, "end": 5.0, "text": "我做了个帮开发者出海的新项目 GitHub 文档翻译平台"},
        {"start": 27.0, "end": 30.0, "text": "自由选择要翻译哪些文档"},
        {"start": 51.0, "end": 53.0, "text": "可以选 GPT Claude 等大模型 API"},
        # Chapter 2: AI 驱动开发流程
        {"start": 80.0, "end": 83.0, "text": "这个项目我是全程直播开发的 99% 代码由 AI 编写"},
        {"start": 86.0, "end": 88.0, "text": "使用 Cursor 工具配合 MCP 扩展"},
        # Chapter 3: 项目部署与资源分享
        {"start": 159.0, "end": 162.0, "text": "通过 Vercel 一键部署上线"},
        {"start": 168.0, "end": 171.0, "text": "项目代码我已经开源在 GitHub"},
        {"start": 172.0, "end": 174.0, "text": "完整开发录屏、教程文档在编程导航里"},
    ]
    outline = [
        # LLM's guess: 0, 30, 60, 90, 120, 150, 180, 210, 240
        {"title": "项目介绍与核心功能", "timestamp": 0, "part_outline": [
            {"timestamp": 0, "content": "GitHub 文档翻译平台项目介绍"},
            {"timestamp": 30, "content": "核心功能演示"},
            {"timestamp": 60, "content": "支持自动增量翻译"},
        ]},
        {"title": "AI 驱动开发流程", "timestamp": 90, "part_outline": [
            {"timestamp": 90, "content": "Cursor 工具和 MCP 扩展"},
            {"timestamp": 120, "content": "开发步骤与最佳实践"},
        ]},
        {"title": "项目部署与资源分享", "timestamp": 180, "part_outline": [
            {"timestamp": 180, "content": "Vercel 一键部署"},
            {"timestamp": 210, "content": "开源教程资源分享"},
            {"timestamp": 240, "content": "推广 AI 编程零基础入门教程"},  # beyond 210s!
        ]},
    ]
    fix_outline_timestamps(outline, segments, 210)

    # Chapter 1: "项目" matches at 3.0; "核心" / "功能" don't appear, but
    # "项目" / "介绍" do — 3.0
    assert outline[0]["timestamp"] == 3
    # Part 1: "GitHub" / "文档" / "翻译平台" / "项目" / "介绍" — first match is 3.0
    assert outline[0]["part_outline"][0]["timestamp"] == 3
    # Part 2: "核心" / "功能" / "演示" — none in segments. LLM guess 30 is
    # in range → use it
    assert outline[0]["part_outline"][1]["timestamp"] == 30
    # Part 3: with max_kw=8, "翻译" is extracted — matches 27.0 (自由选择要翻译),
    # then ensure-increasing bumps to 31 (Part 2 at 30)
    assert outline[0]["part_outline"][2]["timestamp"] == 31

    # Chapter 2: "AI" + "驱动" + "开发" — first match is 80.0 (全程直播开发)
    assert outline[1]["timestamp"] == 80
    # Part 1: "Cursor" / "MCP" — both at 86.0
    assert outline[1]["part_outline"][0]["timestamp"] == 86
    # Part 2: "开发" / "步骤" / "最佳" / "实践" — "开发" matches at 80.0,
    # but Part 1 already at 86, so "ensure increasing" bumps to 87
    assert outline[1]["part_outline"][1]["timestamp"] == 87

    # Chapter 3: "项目" / "部署" / "资源" / "分享" — "项目" matches at 3.0,
    # 168.0; "部署" matches at 159.0. Search from 80 (ch_start) — first
    # hit is 159.0 (部署 in Vercel segment)
    assert outline[2]["timestamp"] == 159
    # Part 1: "Vercel" / "一键" / "部署" — match at 159.0
    assert outline[2]["part_outline"][0]["timestamp"] == 159
    # Part 2: "开源" / "教程" / "资源" / "分享" — match at 168.0 or 172.0
    assert outline[2]["part_outline"][1]["timestamp"] in (168, 172)
    # Part 3: keywords ["推广","广A","AI ","AI编","编程"] — "编程" matches
    # at 172.0 (教程文档在编程导航里). LLM guess 240 is out of range.
    assert outline[2]["part_outline"][2]["timestamp"] == 172


# ---------------------------------------------------------------------------
# Mindmap (Stage 2 sibling — runs in parallel with executive summary)
# ---------------------------------------------------------------------------


def _sample_outline():
    """Three-chapter outline used by the mindmap parser tests."""
    return [
        {"title": "开场介绍", "timestamp": 0, "summary": ["背景", "目标"]},
        {"title": "核心讲解", "timestamp": 120, "summary": ["要点A", "要点B"]},
        {"title": "总结回顾", "timestamp": 300, "summary": ["回顾"]},
    ]


def _sample_mindmap_json(n_chapters: int = 3, with_fence: bool = False) -> str:
    """Build a valid mindmap JSON payload matching `_sample_outline`."""
    children = ",".join(
        f'{{"title":"章节{i+1}","timestamp":0,'
        f'"children":[{{"title":"要点{i+1}-1","timestamp":0,"children":[]}},'
        f'{{"title":"要点{i+1}-2","timestamp":0,"children":[]}}]}}'
        for i in range(n_chapters)
    )
    body = f'{{"root":"视频核心主题示例","children":[{children}]}}'
    return f"```json\n{body}\n```" if with_fence else body


def test_mindmap_prompt_contains_required_markers():
    """The prompt must show the LLM the exact JSON shape and ban Mermaid /
    markdown / extra fields so failures don't leak as 'plausible' garbage."""
    from services.summarizer import MINDMAP_PROMPT

    # Required structural keys
    assert '"root"' in MINDMAP_PROMPT
    assert '"children"' in MINDMAP_PROMPT
    assert '"title"' in MINDMAP_PROMPT
    assert '"timestamp"' in MINDMAP_PROMPT
    # Bans
    assert "Mermaid" in MINDMAP_PROMPT or "mermaid" in MINDMAP_PROMPT
    assert "markdown" in MINDMAP_PROMPT.lower() or "Markdown" in MINDMAP_PROMPT
    assert "额外字段" in MINDMAP_PROMPT or "其它字段" in MINDMAP_PROMPT or "其他字段" in MINDMAP_PROMPT
    # Format placeholders
    assert "{n_chapters}" in MINDMAP_PROMPT
    assert "{chapters_text}" in MINDMAP_PROMPT
    assert "{language}" in MINDMAP_PROMPT


def test_parse_mindmap_valid_bare_json():
    """Bare JSON (no code fence) should parse and graft timestamps from outline."""
    from services.summarizer import parse_mindmap

    outline = _sample_outline()
    raw = _sample_mindmap_json(n_chapters=3, with_fence=False)
    result = parse_mindmap(raw, outline)

    assert result is not None
    assert result["root"] == "视频核心主题示例"
    assert len(result["children"]) == 3
    # Chapter timestamps must come from outline, NOT from LLM (which sent 0)
    assert result["children"][0]["timestamp"] == 0
    assert result["children"][1]["timestamp"] == 120
    assert result["children"][2]["timestamp"] == 300
    # Each chapter has its 2 leaves
    for i, ch in enumerate(result["children"]):
        assert ch["title"] == f"章节{i+1}"
        assert len(ch["children"]) == 2
        # Leaves inherit parent chapter timestamp (per plan decision)
        for leaf in ch["children"]:
            assert leaf["timestamp"] == outline[i]["timestamp"]
            assert leaf["children"] == []


def test_parse_mindmap_code_fence_extraction():
    """JSON inside a ```json ... ``` fence must extract cleanly."""
    from services.summarizer import parse_mindmap

    outline = _sample_outline()
    raw = _sample_mindmap_json(n_chapters=3, with_fence=True)
    result = parse_mindmap(raw, outline)

    assert result is not None
    assert result["root"] == "视频核心主题示例"
    assert len(result["children"]) == 3


def test_parse_mindmap_lenient_extraction_with_prose_around():
    """LLM may pad JSON with prose — balanced-brace scan should still find it."""
    from services.summarizer import parse_mindmap

    outline = _sample_outline()
    body = _sample_mindmap_json(n_chapters=3, with_fence=False)
    raw = f"好的，下面是思维导图：\n\n{body}\n\n以上即为输出。"
    result = parse_mindmap(raw, outline)

    assert result is not None
    assert result["root"] == "视频核心主题示例"
    assert len(result["children"]) == 3


def test_parse_mindmap_chapter_count_mismatch_returns_none():
    """If the LLM emits a different number of chapters than the outline,
    the entire parse must fail — no partial mindmap with missing branches."""
    from services.summarizer import parse_mindmap

    outline = _sample_outline()  # 3 chapters
    raw = _sample_mindmap_json(n_chapters=2)  # only 2
    assert parse_mindmap(raw, outline) is None


def test_parse_mindmap_missing_root_returns_none():
    from services.summarizer import parse_mindmap

    outline = _sample_outline()
    raw = '{"children":[{"title":"x","timestamp":0,"children":[{"title":"y","timestamp":0,"children":[]}]}]}'
    assert parse_mindmap(raw, outline[:1]) is None


def test_parse_mindmap_root_too_short_returns_none():
    from services.summarizer import parse_mindmap

    outline = _sample_outline()
    raw = (
        '{"root":"a","children":[{"title":"x","timestamp":0,'
        '"children":[{"title":"y","timestamp":0,"children":[]}]}]}'
    )
    assert parse_mindmap(raw, outline[:1]) is None


def test_parse_mindmap_chapter_with_no_leaves_returns_none():
    """A chapter with 0 valid leaves would render as a dead branch — reject."""
    from services.summarizer import parse_mindmap

    outline = _sample_outline()[:1]
    raw = '{"root":"主题示例","children":[{"title":"章节A","timestamp":0,"children":[]}]}'
    assert parse_mindmap(raw, outline) is None


def test_parse_mindmap_skips_invalid_leaves():
    """Empty / non-dict leaves should be filtered, but the chapter survives
    as long as at least one valid leaf remains."""
    from services.summarizer import parse_mindmap

    outline = _sample_outline()[:1]
    raw = (
        '{"root":"主题示例","children":[{"title":"章节A","timestamp":0,'
        '"children":[{"title":"","timestamp":0,"children":[]},'
        '"not_a_dict",'
        '{"title":"有效要点","timestamp":0,"children":[]}]}]}'
    )
    result = parse_mindmap(raw, outline)
    assert result is not None
    assert len(result["children"][0]["children"]) == 1
    assert result["children"][0]["children"][0]["title"] == "有效要点"


def test_parse_mindmap_invalid_json_returns_none():
    from services.summarizer import parse_mindmap

    assert parse_mindmap("not json at all", _sample_outline()) is None
    assert parse_mindmap("", _sample_outline()) is None
    assert parse_mindmap("   \n   ", _sample_outline()) is None


def test_parse_mindmap_children_not_a_list_returns_none():
    from services.summarizer import parse_mindmap

    raw = '{"root":"测试主题","children":"not a list"}'
    assert parse_mindmap(raw, _sample_outline()[:1]) is None


def test_parse_mindmap_trims_long_titles():
    """Defensive trim so a chatty LLM can't blow up the mindmap layout."""
    from services.summarizer import parse_mindmap

    outline = _sample_outline()[:1]
    long_title = "超长" * 100  # 200 chars
    raw = (
        f'{{"root":"{long_title}","children":[{{"title":"{long_title}",'
        f'"timestamp":0,"children":[{{"title":"{long_title}",'
        f'"timestamp":0,"children":[]}}]}}]}}'
    )
    result = parse_mindmap(raw, outline)
    assert result is not None
    assert len(result["root"]) <= 60
    assert len(result["children"][0]["title"]) <= 40
    assert len(result["children"][0]["children"][0]["title"]) <= 80


class _FakeMindmapResponse:
    """Mock the OpenAI ChatCompletion response object structure."""

    def __init__(self, content: str):
        msg = type("Msg", (), {"content": content})()
        choice = type("Choice", (), {"message": msg})()
        self.choices = [choice]


def _fake_openai_factory(responses: list[str], call_log: list[int]):
    """Return a fake OpenAI class that emits the given responses in order."""

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.chat = type("Chat", (), {"completions": type("Completions", (), {})()})()
            self.chat.completions.create = self._create

        def _create(self, **kwargs):
            i = call_log[0]
            call_log[0] += 1
            content = responses[min(i, len(responses) - 1)]
            return _FakeMindmapResponse(content)

    return FakeOpenAI


def test_generate_mindmap_returns_none_on_empty_outline():
    from services.summarizer import generate_mindmap

    assert generate_mindmap([], "zh") is None


def test_generate_mindmap_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from services.summarizer import generate_mindmap

    assert generate_mindmap(_sample_outline(), "zh") is None


def test_generate_mindmap_retries_on_invalid_then_succeeds(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MINDMAP_MODEL", "fake-model")
    monkeypatch.setenv("MINDMAP_TIMEOUT", "10")

    valid = _sample_mindmap_json(n_chapters=3, with_fence=False)
    call_log = [0]
    fake_cls = _fake_openai_factory(["not json", valid], call_log)
    monkeypatch.setattr("openai.OpenAI", fake_cls)

    from services.summarizer import generate_mindmap
    result = generate_mindmap(_sample_outline(), "zh")

    assert result is not None
    assert result["root"] == "视频核心主题示例"
    assert call_log[0] == 2  # one retry


def test_generate_mindmap_returns_none_after_max_retries(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MINDMAP_MODEL", "fake-model")
    monkeypatch.setenv("MINDMAP_TIMEOUT", "10")

    call_log = [0]
    fake_cls = _fake_openai_factory(["garbage"] * 5, call_log)
    monkeypatch.setattr("openai.OpenAI", fake_cls)

    from services.summarizer import generate_mindmap
    assert generate_mindmap(_sample_outline(), "zh") is None
    # 3 attempts (max_retries=3 in the source)
    assert call_log[0] == 3


def test_generate_mindmap_swallows_api_errors(monkeypatch):
    """An OpenAI client exception must not propagate — the caller (SSE
    router) relies on a clean None to skip the mindmap event."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MINDMAP_MODEL", "fake-model")

    class BoomOpenAI:
        def __init__(self, api_key=None, base_url=None):
            raise RuntimeError("simulated API failure")

    monkeypatch.setattr("openai.OpenAI", BoomOpenAI)

    from services.summarizer import generate_mindmap
    assert generate_mindmap(_sample_outline(), "zh") is None


def test_generate_mindmap_uses_mindmap_model_env(monkeypatch):
    """MINDMAP_MODEL takes precedence over EXECUTIVE_SUMMARY_MODEL / SUMMARY_MODEL."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_MODEL", "should-not-use")
    monkeypatch.setenv("EXECUTIVE_SUMMARY_MODEL", "also-not-this")
    monkeypatch.setenv("MINDMAP_MODEL", "the-right-one")
    monkeypatch.setenv("MINDMAP_TIMEOUT", "10")

    valid = _sample_mindmap_json(n_chapters=3, with_fence=False)
    captured = {}

    class CapturingOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.chat = type("Chat", (), {"completions": type("Completions", (), {})()})()
            self.chat.completions.create = self._create

        def _create(self, **kwargs):
            captured["model"] = kwargs.get("model")
            return _FakeMindmapResponse(valid)

    monkeypatch.setattr("openai.OpenAI", CapturingOpenAI)

    from services.summarizer import generate_mindmap
    generate_mindmap(_sample_outline(), "zh")
    assert captured["model"] == "the-right-one"


# ---------------------------------------------------------------------------
# Chat with Video (retrieval + citation)
# ---------------------------------------------------------------------------


def _chat_segments():
    """Sample segments for chat retrieval tests."""
    return [
        {"start": 0, "end": 3, "text": "我做了个帮开发者出海的新项目"},
        {"start": 3, "end": 5, "text": "GitHub 文档自动翻译平台"},
        {"start": 12, "end": 14, "text": "用 Cursor 工具配合 MCP 扩展"},
        {"start": 14, "end": 16, "text": "AI 编程效率非常高"},
        {"start": 30, "end": 32, "text": "通过 Vercel 一键部署上线"},
        {"start": 32, "end": 34, "text": "免费额度足够个人项目"},
    ]


def _chat_outline():
    """Outline matching _chat_segments source_segments mapping."""
    return [
        {"title": "项目介绍", "timestamp": 0, "summary": ["开源项目", "GitHub翻译平台"],
         "source_segments": [0, 1]},
        {"title": "AI开发流程", "timestamp": 12, "summary": ["Cursor工具", "MCP扩展"],
         "source_segments": [2, 3]},
        {"title": "部署与资源", "timestamp": 30, "summary": ["Vercel部署", "免费额度"],
         "source_segments": [4, 5]},
    ]


def test_retrieve_by_chapter_basic():
    """Basic retrieval: query matches segments in the right chapters."""
    from services.summarizer import _retrieve_by_chapter

    hits = _retrieve_by_chapter("Cursor", _chat_segments(), _chat_outline())
    assert len(hits) > 0
    # Cursor appears in ch[1] (seg 2)
    assert 1 in hits
    assert any(h["idx"] == 2 for h in hits[1])


def test_retrieve_by_chapter_diversification():
    """A query matching segments in multiple chapters should return
    chapters ranked by score, not all segments from one chapter."""
    from services.summarizer import _retrieve_by_chapter

    # "Vercel" matches ch[2], "Cursor" matches ch[1]
    hits = _retrieve_by_chapter("Vercel Cursor", _chat_segments(), _chat_outline(),
                                top_k_chapters=3, max_seg_per_chapter=2)
    # Both chapters should appear
    assert 1 in hits or 2 in hits  # at least one of them
    # Each chapter capped at 2
    for ch_idx, segs in hits.items():
        assert len(segs) <= 2


def test_retrieve_by_chapter_per_chapter_cap():
    """Even if one chapter has many matching segments, it's capped."""
    from services.summarizer import _retrieve_by_chapter

    # "项目" matches ch[0] segments 0 and 1
    hits = _retrieve_by_chapter("项目", _chat_segments(), _chat_outline(),
                                max_seg_per_chapter=1)
    for ch_idx, segs in hits.items():
        assert len(segs) <= 1


def test_retrieve_by_chapter_empty_query():
    from services.summarizer import _retrieve_by_chapter
    hits = _retrieve_by_chapter("", _chat_segments(), _chat_outline())
    assert hits == {}


def test_retrieve_by_chapter_no_match():
    from services.summarizer import _retrieve_by_chapter
    hits = _retrieve_by_chapter("量子纠缠", _chat_segments(), _chat_outline())
    assert hits == {}


def test_parse_chat_citations_valid():
    """Valid [[CH_N]] references are parsed correctly."""
    from services.summarizer import _parse_chat_citations

    outline = _chat_outline()
    valid = {1, 2}
    answer = "Cursor 配合 MCP 使用 [[CH_1]]，部署在 Vercel 上 [[CH_2]]。"
    clean, citations = _parse_chat_citations(answer, outline, valid)

    assert "[[CH_" not in clean
    assert "Cursor" in clean
    assert len(citations) == 2
    assert citations[0]["chapter_title"] == "AI开发流程"
    assert citations[0]["timestamp"] == 12
    assert citations[1]["chapter_title"] == "部署与资源"
    assert citations[1]["timestamp"] == 30


def test_parse_chat_citations_invalid_chapter_filtered():
    """References to chapters not in valid_chapters are dropped."""
    from services.summarizer import _parse_chat_citations

    outline = _chat_outline()
    valid = {1}  # only ch[1] is valid
    answer = "Cursor 使用 [[CH_1]]，部署在 Vercel [[CH_2]]。"
    clean, citations = _parse_chat_citations(answer, outline, valid)

    assert len(citations) == 1
    assert citations[0]["chapter_title"] == "AI开发流程"
    # [[CH_2]] removed from text even though it was invalid
    assert "[[CH_" not in clean


def test_parse_chat_citations_out_of_range():
    """References with N >= len(outline) are dropped."""
    from services.summarizer import _parse_chat_citations

    outline = _chat_outline()
    valid = {0, 1, 2, 99}  # 99 is out of range
    answer = "Something [[CH_99]] and [[CH_1]]."
    clean, citations = _parse_chat_citations(answer, outline, valid)

    assert len(citations) == 1
    assert citations[0]["chapter_title"] == "AI开发流程"


def test_parse_chat_citations_dedup():
    """Duplicate [[CH_N]] references are deduplicated."""
    from services.summarizer import _parse_chat_citations

    outline = _chat_outline()
    valid = {1}
    answer = "A [[CH_1]] B [[CH_1]] C."
    clean, citations = _parse_chat_citations(answer, outline, valid)

    assert len(citations) == 1


def test_parse_chat_citations_empty():
    """No [[CH_N]] in answer → empty citations, text unchanged."""
    from services.summarizer import _parse_chat_citations

    outline = _chat_outline()
    answer = "视频中没有提到这个问题。"
    clean, citations = _parse_chat_citations(answer, outline, set())

    assert citations == []
    assert clean == answer


def test_chat_system_prompt_contains_rules():
    """System prompt must enforce citation rules and restrict chapter range."""
    from services.summarizer import CHAT_SYSTEM_PROMPT

    assert "[[CH_N]]" in CHAT_SYSTEM_PROMPT
    assert "从 0 开始" in CHAT_SYSTEM_PROMPT
    assert "禁止引用" in CHAT_SYSTEM_PROMPT or "只能引用" in CHAT_SYSTEM_PROMPT
    assert "没有提到" in CHAT_SYSTEM_PROMPT


def test_chat_prompt_contains_outline_and_segments():
    """The user prompt must include outline chapters and retrieved segments."""
    from services.summarizer import _build_chat_prompt

    outline = _chat_outline()
    segments = _chat_segments()
    exec_summary = {"core_topic": "开源文档翻译平台开发全流程"}
    chapter_hits = {
        1: [{"idx": 2, "text": "用 Cursor 工具配合 MCP 扩展", "start": 12, "score": 0.5}],
    }
    prompt = _build_chat_prompt("Cursor 怎么用的", outline, chapter_hits, segments, exec_summary)

    assert "开源文档翻译平台开发全流程" in prompt
    assert "第 0 章" in prompt
    assert "第 1 章" in prompt
    assert "来自「AI开发流程」" in prompt
    assert "Cursor 怎么用的" in prompt
    assert "SEG_2" in prompt


def test_chat_prompt_respects_token_limit():
    """Prompt must not exceed _CHAT_PROMPT_MAX_CHARS."""
    from services.summarizer import _build_chat_prompt, _CHAT_PROMPT_MAX_CHARS

    # Build with a large outline to stress the limit
    big_outline = [
        {"title": f"章节{i}", "timestamp": i * 100,
         "summary": [f"要点{j}" * 20 for j in range(5)],
         "source_segments": list(range(i * 10, i * 10 + 10))}
        for i in range(20)
    ]
    big_segments = [
        {"start": i * 2, "end": i * 2 + 2, "text": f"字幕内容{i}" * 10}
        for i in range(200)
    ]
    chapter_hits = {i: [{"idx": i * 10, "text": "x", "start": 0, "score": 0.3}]
                    for i in range(10)}
    prompt = _build_chat_prompt("测试问题", big_outline, chapter_hits, big_segments, None)
    assert len(prompt) <= _CHAT_PROMPT_MAX_CHARS


def test_generate_chat_answer_returns_error_when_no_match(monkeypatch):
    """generate_chat_answer should yield error when retrieval is empty."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CHAT_MODEL", "fake")

    from services.summarizer import generate_chat_answer
    events = list(generate_chat_answer(
        "量子纠缠", _chat_outline(), _chat_segments(), None, "zh",
    ))
    # Should yield exactly one error event, no LLM call
    assert len(events) == 1
    assert events[0][0] == "error"
    assert "没有提到" in events[0][1]



