from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest
from fastapi.testclient import TestClient

import backend.agents.decision as decision_module
import backend.main as main_module
from backend.main import app
from backend.agents.i_safe import quick_keyword_check
from backend.agents.magic_ai import MagicAI
import backend.memory.json_store as json_store_module
from backend.memory.json_store import JsonMemoryStore
from backend.services.llm_service import LLMService
from backend.services.tts_service import TTSService


client = TestClient(app)


def test_chat_requires_elder_token():
    response = client.post(
        "/api/chat",
        json={"message": "hello"},
    )

    assert response.status_code == 401


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
    assert quick_keyword_check("the helper arrived") == 0


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
