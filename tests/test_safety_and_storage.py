import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest
from fastapi.testclient import TestClient

import backend.agents.decision as decision_module
import backend.agents.i_safe as i_safe_module
import backend.agents.magic_ai as magic_ai_module
import backend.main as main_module
import backend.services.llm_service as llm_service_module
from backend.main import app
from backend.agents.i_safe import quick_keyword_check
from backend.agents.magic_ai import MagicAI
import backend.memory.json_store as json_store_module
from backend.memory.json_store import JsonMemoryStore
from backend.services.llm_service import LLMService
from backend.services.tts_service import TTSService


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_admin_auth(monkeypatch):
    monkeypatch.setattr(main_module, "CARE4U_DEMO_MODE", True)
    monkeypatch.setattr(main_module, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(main_module, "ADMIN_USERS", "")
    with main_module.admin_auth_fail_lock:
        main_module.admin_auth_fail_counts.clear()
    yield
    with main_module.admin_auth_fail_lock:
        main_module.admin_auth_fail_counts.clear()


def test_chat_requires_elder_id():
    response = client.post(
        "/api/chat",
        json={"message": "hello"},
    )

    assert response.status_code == 422


def _timed_decision():
    decision = decision_module.Decision.__new__(decision_module.Decision)
    decision.chat_count = 0
    decision.elder_id = "T001"
    decision.session_id = "default"
    decision.persona_id = None
    decision.active_persona = {"name": "AI 助理"}
    decision.last_seen = None

    class FakeMagic:
        def __init__(self):
            self.history = []

        def chat(self, message):
            time.sleep(0.03)
            self.history.append({"role": "model", "content": message})
            return "好的，我陪你聊聊。"

        def get_history(self):
            return self.history

    class FakeISafe:
        def analyze(self, message, speed_emotion):
            time.sleep(0.03)
            return {
                "emotion": "normal",
                "is_urgent": False,
                "sentiment": "neutral",
                "should_record": False,
                "escalation_level": 0,
            }

    decision.magic = FakeMagic()
    decision.isafe = FakeISafe()
    return decision


def test_decision_chat_returns_timing_metrics():
    decision = _timed_decision()
    response = decision.chat("hello")

    assert response["message"] == "好的，我陪你聊聊。"
    assert isinstance(response["_isafe_ms"], int)
    assert isinstance(response["_magic_ms"], int)
    assert isinstance(response["_chat_total_ms"], int)
    assert response["_isafe_ms"] >= 1
    assert response["_magic_ms"] >= 1


def test_decision_emergency_fast_path_reports_total_only():
    decision = _timed_decision()
    response = decision.chat("我跌倒了，help")

    assert response["escalation_level"] == 3
    assert response["_isafe_ms"] is None
    assert response["_magic_ms"] is None
    assert isinstance(response["_chat_total_ms"], int)


def test_concurrent_family_note_mutations_preserve_both_notes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(json_store_module, "DATA_DIR", tmp_path)
    store = JsonMemoryStore()
    assert store.update_basic_fields("T001", {"name": "Test"})
    barrier = threading.Barrier(2)

    def append(note):
        barrier.wait()
        return store.append_family_note("T001", {"note": note})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, ["one", "two"]))

    assert all(results)
    notes = {
        item["note"]
        for item in store.get_profile("T001")["family_notes"]
    }
    assert notes == {"one", "two"}


def test_non_demo_without_admin_credentials_fails_closed(monkeypatch):
    monkeypatch.setattr(main_module, "CARE4U_DEMO_MODE", False)
    monkeypatch.setattr(main_module, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(main_module, "ADMIN_USERS", "")

    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        response = local_client.get("/admin")

    assert response.status_code == 401


def test_emergency_keywords_reach_level_three():
    assert quick_keyword_check("我跌倒了") == 3
    assert quick_keyword_check("please help me") == 3
    assert quick_keyword_check("the helper arrived") is None


def test_safe_keyword_fast_path_keeps_dangerous_terms_first():
    assert quick_keyword_check("早安，今天天氣很好") == 0
    assert quick_keyword_check("散步時跌倒了") == 3


def test_isafe_safe_keyword_skips_llm(monkeypatch):
    calls = {"count": 0}

    class FakeLLMService:
        def __init__(self, model_name):
            pass

        def analyze_emotion(self, message):
            calls["count"] += 1
            raise AssertionError("safe keyword fast path should skip the LLM")

    class FakeStore:
        def get_profile(self, elder_id):
            return {"active_persona": "ai", "recent_events": []}

    monkeypatch.setattr(i_safe_module, "LLMService", FakeLLMService)
    monkeypatch.setattr(i_safe_module, "VectorMemoryStore", lambda: FakeStore())
    monkeypatch.setattr(i_safe_module, "EmbeddingService", lambda: object())

    result = i_safe_module.ISafe("T001").analyze("早安，今天天氣很好")

    assert calls["count"] == 0
    assert result["escalation_level"] == 0
    assert result["_llm_used"] is False
    assert result["_isafe_path"] == "safe_keyword"


def test_isafe_uses_configured_model(monkeypatch):
    captured = {}

    class FakeLLMService:
        def __init__(self, model_name):
            captured["model_name"] = model_name

    class FakeStore:
        def get_profile(self, elder_id):
            return {"active_persona": "ai"}

    monkeypatch.setenv("ISAFE_MODEL", "gemini-test-isafe")
    monkeypatch.setattr(i_safe_module, "LLMService", FakeLLMService)
    monkeypatch.setattr(i_safe_module, "VectorMemoryStore", lambda: FakeStore())
    monkeypatch.setattr(i_safe_module, "EmbeddingService", lambda: object())

    i_safe_module.ISafe("T001")

    assert captured["model_name"] == "gemini-test-isafe"


def test_safety_status_counts_only_unacknowledged_alerts():
    agent = i_safe_module.ISafe.__new__(i_safe_module.ISafe)
    agent.elder_id = "T001"

    class FakeMemory:
        def get_recent_events(self, elder_id, limit=10):
            return [
                {"topic_tags": ["安全警報"], "acknowledged": True},
                {"topic_tags": ["安全警報"], "acknowledged": False},
                {"topic_tags": ["趨勢警報"]},
                {"topic_tags": ["情緒"], "sentiment": "negative", "acknowledged": True},
            ]

    agent.memory = FakeMemory()

    status = agent.get_safety_status()

    assert status["urgent_count"] == 1
    assert status["trend_alerts"] == 1
    assert status["negative_count"] == 1
    assert status["hazard_level"] == "high"


def test_acknowledge_safety_event_endpoint_marks_event(monkeypatch):
    calls = []

    class FakeStore:
        def acknowledge_event_at(self, elder_id, index):
            calls.append((elder_id, index))
            return True

    monkeypatch.setattr(
        main_module,
        "VectorMemoryStore",
        lambda: FakeStore(),
    )
    monkeypatch.setattr(main_module, "_reset_elder_state", lambda elder_id: None)

    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        response = local_client.patch("/api/isafe/T001/events/2/acknowledge")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert calls == [("T001", 2)]


def test_magic_ai_uses_configured_model(monkeypatch):
    captured = {}

    class FakeLLMService:
        def __init__(self, model_name):
            captured["model_name"] = model_name

    class FakeStore:
        def get_profile(self, elder_id):
            return {
                "name": "Test",
                "active_persona": "ai",
                "personas": {"ai": {"name": "AI"}},
            }

        def load_conversation(self, elder_id, persona_id):
            return []

    monkeypatch.setenv("MAGIC_MODEL", "gemini-test-magic")
    monkeypatch.setattr(magic_ai_module, "LLMService", FakeLLMService)
    monkeypatch.setattr(magic_ai_module, "VectorMemoryStore", lambda: FakeStore())
    monkeypatch.setattr(magic_ai_module, "EmbeddingService", lambda: object())

    magic_ai_module.MagicAI("T001")

    assert captured["model_name"] == "gemini-test-magic"


def test_llm_stream_chat_yields_sdk_chunks(monkeypatch):
    captured = {}

    class FakeResponse:
        def __init__(self, text):
            self.text = text

    def fake_stream(client, **kwargs):
        captured["contents"] = kwargs["contents"]
        return iter([FakeResponse("第一段"), FakeResponse("第二段")])

    monkeypatch.setattr(llm_service_module, "_get_client", lambda: object())
    monkeypatch.setattr(
        llm_service_module,
        "_generate_content_stream",
        fake_stream,
    )
    service = llm_service_module.LLMService("test-model")
    monkeypatch.setattr(service, "build_system_prompt", lambda *args, **kwargs: "prompt")

    chunks = list(service.stream_chat(
        profile={},
        conversation_history=[
            {"role": "user", "content": str(index)}
            for index in range(8)
        ],
        user_message="hello",
        recent_messages=[
            {"role": "user", "content": str(index)}
            for index in range(4)
        ],
    ))

    assert chunks == ["第一段", "第二段"]
    assert len(captured["contents"]) == 5


def test_compact_isafe_schema_derives_compatibility_fields(monkeypatch):
    class FakeResponse:
        text = (
            '{"escalation_level":2,"emotion":"urgent",'
            '"sentiment":"negative","is_urgent":true}'
        )

    monkeypatch.setattr(llm_service_module, "_get_client", lambda: object())
    monkeypatch.setattr(
        llm_service_module,
        "_generate_content",
        lambda client, **kwargs: FakeResponse(),
    )

    result = llm_service_module.LLMService("test-model").analyze_emotion(
        "我站不穩"
    )

    assert result["escalation_level"] == 2
    assert result["importance"] == 0.8
    assert result["emotion_score"] == -0.6
    assert result["should_record"] is True


def test_magic_ai_stream_records_only_after_generator_finishes():
    magic = magic_ai_module.MagicAI.__new__(magic_ai_module.MagicAI)
    magic.elder_id = "T001"
    magic.persona_id = None
    magic._persona_key = "ai"
    magic.profile = {"active_persona": "ai", "personas": {"ai": {}}}
    magic.conversation_history = [
        {"role": "user", "content": str(index)}
        for index in range(6)
    ]
    magic._chat_count = 0

    class FakeEmbedding:
        def embed(self, message):
            return []

    class FakeMemory:
        def search_similar_memories(self, *args, **kwargs):
            return []

        def get_important_memories(self, *args, **kwargs):
            return []

    class FakeLLM:
        def stream_chat(self, **kwargs):
            assert len(kwargs["recent_messages"]) == 4
            yield "你好"
            yield "呀"

    magic.embedding = FakeEmbedding()
    magic.memory = FakeMemory()
    magic.llm = FakeLLM()

    stream = magic.stream_chat("早安")
    assert next(stream) == "你好"
    assert len(magic.conversation_history) == 6
    assert list(stream) == ["呀"]
    assert magic.conversation_history[-2]["content"] == "早安"
    assert magic.conversation_history[-1]["content"] == "你好呀"


def test_decision_stream_appends_safety_warning():
    decision = decision_module.Decision.__new__(decision_module.Decision)
    decision.chat_count = 0
    decision.elder_id = "T001"
    decision.session_id = "stream"
    decision.persona_id = None
    decision.active_persona = {"name": "AI"}
    decision.last_seen = None

    class FakeMagic:
        def stream_chat(self, message):
            yield "先坐下休息"

        def get_history(self):
            return []

    class FakeISafe:
        def analyze(self, message, speed_emotion):
            return {
                "emotion": "urgent",
                "is_urgent": True,
                "sentiment": "negative",
                "should_record": False,
                "escalation_level": 2,
                "_llm_used": True,
                "_isafe_path": "llm",
            }

    decision.magic = FakeMagic()
    decision.isafe = FakeISafe()

    events = list(decision.stream_chat("我站不穩"))

    assert events[0] == {"type": "chunk", "chunk": "先坐下休息"}
    assert "通知照護人員" in events[-2]["chunk"]
    assert events[-1]["type"] == "done"
    assert events[-1]["escalation_level"] == 2
    assert isinstance(events[-1]["_first_chunk_ms"], int)


def test_chat_stream_returns_sse(monkeypatch):
    class FakeDecision:
        def __init__(self):
            self._lock = asyncio.Lock()

        def stream_chat(self, message, speed_emotion):
            yield {"type": "chunk", "chunk": "您好"}
            yield {
                "type": "done",
                "message": "您好",
                "emotion": "normal",
                "is_urgent": False,
                "sentiment": "neutral",
                "trend_alert": None,
                "escalation_level": 2,
            }

    monkeypatch.setattr(main_module, "get_decision", lambda *args: FakeDecision())
    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        response = local_client.post(
            "/api/chat?stream=true",
            json={
                "elder_id": "W001",
                "message": "hello",
                "session_id": "stream-test",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"chunk": "您好", "done": false' in response.text
    assert '"done": true' in response.text


def test_same_persona_sessions_have_isolated_conversation_history(monkeypatch):
    class FakeMagicAI:
        def __init__(self, elder_id, persona_id=None):
            self.elder_id = elder_id
            self.persona_id = persona_id
            self.conversation_history = []

    monkeypatch.setattr(decision_module, "MagicAI", FakeMagicAI)
    decision_module._magic_agents.clear()

    first = decision_module._get_magic("T001", "session-a", "daughter")
    second = decision_module._get_magic("T001", "session-b", "daughter")
    first.conversation_history.append({"role": "user", "content": "private"})

    assert first is not second
    assert second.conversation_history == []
    decision_module._magic_agents.clear()


def test_profile_handlers_preserve_expected_http_errors(monkeypatch):
    class MissingProfileStore:
        def get_profile(self, elder_id):
            return {}

    monkeypatch.setattr(
        main_module,
        "VectorMemoryStore",
        lambda: MissingProfileStore(),
    )
    requests = [
        (
            "/api/profile/persona/add",
            {
                "elder_id": "T001",
                "name": "Test",
                "relation": "daughter",
                "honorific": "Dad",
            },
        ),
        (
            "/api/profile/persona/delete",
            {"elder_id": "T001", "persona_id": "persona_1"},
        ),
        (
            "/api/profile/persona/switch",
            {"elder_id": "T001", "persona_id": "persona_1"},
        ),
        (
            "/api/profile/family-note/add",
            {"elder_id": "T001", "note": "note"},
        ),
        (
            "/api/profile/family-note/delete",
            {"elder_id": "T001", "index": 0},
        ),
    ]

    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        for path, payload in requests:
            assert local_client.post(path, json=payload).status_code == 404


def test_delete_ai_persona_returns_400(monkeypatch):
    class ExistingProfileStore:
        def get_profile(self, elder_id):
            return {"personas": {"ai": {"name": "AI"}}}

    monkeypatch.setattr(
        main_module,
        "VectorMemoryStore",
        lambda: ExistingProfileStore(),
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        response = local_client.post(
            "/api/profile/persona/delete",
            json={"elder_id": "T001", "persona_id": "ai"},
        )

    assert response.status_code == 400


def test_delete_missing_persona_returns_404(monkeypatch):
    class ExistingProfileStore:
        def get_profile(self, elder_id):
            return {"personas": {"ai": {"name": "AI"}}}

        def delete_persona(self, elder_id, persona_id):
            raise AssertionError("missing persona should be rejected before delete")

    monkeypatch.setattr(
        main_module,
        "VectorMemoryStore",
        lambda: ExistingProfileStore(),
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        response = local_client.post(
            "/api/profile/persona/delete",
            json={"elder_id": "T001", "persona_id": "persona_99"},
        )

    assert response.status_code == 404


def test_store_delete_missing_persona_raises_key_error(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(json_store_module, "DATA_DIR", tmp_path)
    store = JsonMemoryStore()
    assert store.update_basic_fields("T001", {"name": "Test"})
    assert store.set_persona("T001", "persona_1", {"name": "one"})

    try:
        store.delete_persona("T001", "persona_2")
    except KeyError as error:
        assert error.args == ("persona_2",)
    else:
        raise AssertionError("missing persona should raise KeyError")


def test_manual_biography_is_not_overwritten_by_background_update(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(json_store_module, "DATA_DIR", tmp_path)
    store = JsonMemoryStore()
    assert store.update_basic_fields("T001", {"name": "Test"})
    assert store.set_biography(
        "T001",
        {"content": "manual", "manually_edited": True, "sources": []},
    ) == "updated"

    result = store.set_biography(
        "T001",
        {"content": "generated", "manually_edited": False, "sources": []},
        skip_if_manual=True,
    )

    assert result == "skipped"
    assert store.get_profile("T001")["elder_biography"]["content"] == "manual"


def test_concurrent_persona_ids_are_unique_and_do_not_reuse_existing(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(json_store_module, "DATA_DIR", tmp_path)
    store = JsonMemoryStore()
    assert store.update_basic_fields("T001", {"name": "Test"})
    assert store.set_persona("T001", "persona_1", {"name": "one"})
    assert store.set_persona("T001", "persona_3", {"name": "three"})
    barrier = threading.Barrier(2)

    def add(name):
        barrier.wait()
        return store.add_persona_auto("T001", {"name": name})

    with ThreadPoolExecutor(max_workers=2) as pool:
        allocated = set(pool.map(add, ["four", "five"]))

    assert allocated == {"persona_4", "persona_5"}
    personas = store.get_profile("T001")["personas"]
    assert personas["persona_3"]["name"] == "three"


def test_uploads_validate_persona_before_creating_files(
    tmp_path,
    monkeypatch,
):
    class MissingProfileStore:
        def get_profile(self, elder_id):
            return {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        main_module,
        "VectorMemoryStore",
        lambda: MissingProfileStore(),
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        voice_response = local_client.post(
            "/api/profile/persona/upload-voice",
            data={"elder_id": "T001", "persona_id": "persona_1"},
            files={"voice": ("voice.wav", b"voice", "audio/wav")},
        )
        avatar_response = local_client.post(
            "/api/profile/persona/upload-avatar",
            data={"elder_id": "T001", "persona_id": "persona_1"},
            files={"avatar": ("avatar.png", b"image", "image/png")},
        )

    assert voice_response.status_code == 404
    assert avatar_response.status_code == 404
    assert not (tmp_path / "backend").exists()
    assert not (tmp_path / "frontend").exists()


def test_upload_metadata_failure_leaves_no_orphan_files(
    tmp_path,
    monkeypatch,
):
    class FailingMetadataStore:
        def get_profile(self, elder_id):
            return {
                "personas": {
                    "persona_1": {
                        "voice_path": None,
                        "voice_engine": "edge",
                        "avatar_path": None,
                    }
                }
            }

        def set_persona_field(self, elder_id, persona_id, field, value):
            return False

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        main_module,
        "VectorMemoryStore",
        lambda: FailingMetadataStore(),
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        voice_response = local_client.post(
            "/api/profile/persona/upload-voice",
            data={"elder_id": "T001", "persona_id": "persona_1"},
            files={"voice": ("voice.wav", b"voice", "audio/wav")},
        )
        avatar_response = local_client.post(
            "/api/profile/persona/upload-avatar",
            data={"elder_id": "T001", "persona_id": "persona_1"},
            files={"avatar": ("avatar.png", b"image", "image/png")},
        )

    assert voice_response.status_code == 500
    assert avatar_response.status_code == 500
    assert list(tmp_path.rglob("*.*")) == []


def test_clear_memory_removes_in_memory_and_disk_history(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(json_store_module, "DATA_DIR", tmp_path)
    store = JsonMemoryStore()
    history = [{"role": "user", "content": "private"}]
    assert store.save_conversation("T001", history, "daughter")

    agent = MagicAI.__new__(MagicAI)
    agent.elder_id = "T001"
    agent._persona_key = "daughter"
    agent.memory = store
    agent.conversation_history = list(history)
    agent.clear_memory()

    assert agent.conversation_history == []
    assert store.load_conversation("T001", "daughter") == []


def test_family_note_index_out_of_range_returns_400(monkeypatch):
    class OutOfRangeStore:
        def get_profile(self, elder_id):
            return {"family_notes": []}

        def delete_family_note_at(self, elder_id, index):
            raise IndexError("family note index out of range")

    monkeypatch.setattr(
        main_module,
        "VectorMemoryStore",
        lambda: OutOfRangeStore(),
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        response = local_client.post(
            "/api/profile/family-note/delete",
            json={"elder_id": "T001", "index": 2},
        )

    assert response.status_code == 400


def test_background_results_are_consumed_only_when_all_done():
    with main_module.chat_background_results_lock:
        main_module.chat_background_results.clear()

    task_id = main_module._reserve_background_result("caregiver-test")
    pending = main_module._consume_background_result(task_id)
    assert pending["all_done"] is False

    main_module._update_background_result(
        task_id,
        {"image_status": "complete", "image": "image"},
    )
    main_module._update_background_result(
        task_id,
        {"health_status": "failed", "health_error": "offline"},
    )
    completed = main_module._consume_background_result(task_id)

    assert completed["all_done"] is True
    with pytest.raises(main_module.HTTPException) as error:
        main_module._consume_background_result(task_id)
    assert error.value.status_code == 404


def test_background_capacity_does_not_evict_pending_tasks(monkeypatch):
    monkeypatch.setattr(main_module, "BACKGROUND_RESULTS_MAX", 2)
    with main_module.chat_background_results_lock:
        main_module.chat_background_results.clear()

    first = main_module._reserve_background_result("test-1")
    second = main_module._reserve_background_result("test-2")
    third = main_module._reserve_background_result("test-3")

    assert first
    assert second
    assert third is None
    with main_module.chat_background_results_lock:
        main_module.chat_background_results.clear()


def test_recent_conversation_context_includes_role_labels():
    service = LLMService.__new__(LLMService)
    context = service._build_memory_context(
        {},
        [
            {"role": "user", "content": "hello"},
            {"role": "model", "content": "hi"},
        ],
        [],
        [],
    )

    assert "[長者]：hello" in context["recent_conv_text"]
    assert "[你]：hi" in context["recent_conv_text"]


def test_tts_engine_normalization_uses_supported_whitelist():
    assert TTSService.normalize_engine("XTTS") == "xtts"
    assert TTSService.normalize_engine("luxtts") == "luxtts"
    assert TTSService.normalize_engine("azure") == "edge"
    assert TTSService.normalize_engine(None) == "edge"


def test_biography_sources_distinguish_omitted_from_empty(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(json_store_module, "DATA_DIR", tmp_path)
    store = JsonMemoryStore()
    assert store.update_basic_fields("T001", {"name": "Test"})
    assert store.set_biography(
        "T001",
        {"content": "old", "sources": [{"title": "source"}]},
    ) == "updated"

    assert store.set_biography(
        "T001",
        {"content": "preserved", "sources": []},
        preserve_sources=True,
    ) == "updated"
    assert store.get_profile("T001")["elder_biography"]["sources"] == [
        {"title": "source"}
    ]

    assert store.set_biography(
        "T001",
        {"content": "cleared", "sources": []},
    ) == "updated"
    assert store.get_profile("T001")["elder_biography"]["sources"] == []
    assert main_module.BiographyUpdateRequest(
        elder_id="T001",
        biography="bio",
    ).sources is None


def test_get_personas_returns_404_for_missing_profile(monkeypatch):
    class MissingProfileStore:
        def get_profile(self, elder_id):
            return {}

    monkeypatch.setattr(
        main_module,
        "VectorMemoryStore",
        lambda: MissingProfileStore(),
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        response = local_client.get("/api/profile/T001/personas")

    assert response.status_code == 404
