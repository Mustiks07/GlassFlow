import hashlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select

from glassflow.core.models import DatasetRow, SourceRow
from glassflow.modules.intelligence.migrations import intelligence_reviews_0007
from glassflow.modules.intelligence.models import POST_INTELLIGENCE_TABLES, QualityCheckRow, TurnRow
from glassflow.modules.intelligence.providers.base import ProviderError
from glassflow.modules.intelligence.reviews import record_accepted_batch_reviews
from glassflow.modules.intelligence.service import IntelligenceService

from .conftest import KB_PATH
from .test_api import app_client as _app_client
from .test_api import kb_version, modified_kb
from .test_post_p0 import turn
from .test_post_provenance import call, set_runtime

app_client = _app_client


def items(client, **params):
    response = client.get("/api/v1/assistant/review-items", params={"dataset_id": "ds-a", **params})
    assert response.status_code == 200, response.text
    return response.json()


def seed_workspace(client, mode="workspace"):
    raw = KB_PATH.read_bytes()
    with client.app.state.session_factory.begin() as session:
        session.add(DatasetRow(id="ds-a", name="Review test", mode=mode, fingerprint="review-test",
                               source_hashes={}, row_counts={}))
        session.add(SourceRow(dataset_id="ds-a", kind="kb", filename=KB_PATH.name, content=raw,
                              sha256=hashlib.sha256(raw).hexdigest(), row_count=1))


def test_queue_classifies_policy_missing_kb_and_persists_restart(app_client):
    turn(app_client, "Нужна установка стекла 4 мм")
    turn(app_client, "Стекло 6 мм прозрачное 450×370 мм с кромкой по выбранным сторонам")
    turn(app_client, "Рифленое прозрачное 8 мм 400×300 мм 2 шт.")
    queued = items(app_client)
    assert {item["category"] for item in queued} == {"correct_policy", "missing_parameter", "kb_fact"}
    assert next(item for item in queued if item["category"] == "missing_parameter")["reason_codes"] == ["edge_sides"]
    app_client.app.state.intelligence_service = IntelligenceService(app_client.sources, app_client.app.state.session_factory)
    assert items(app_client) == queued
    app_client.sources.add_kb("other", KB_PATH.read_bytes())
    other = app_client.get("/api/v1/assistant/review-items", params={"dataset_id": "other"})
    assert other.status_code == 200 and other.json() == []


def test_provider_and_verifier_failures_are_separate_review_classes(app_client):
    set_runtime(app_client, [ProviderError("auth", "mock auth failure")], max_retries=0)
    assert call(app_client, execution_mode="model_first").json()["origin"] == "fallback"
    assert items(app_client, category="provider_error")[0]["reason_codes"] == ["auth"]
    from .fakes import reply
    set_runtime(app_client, [reply(text="Цена стекла 6 мм прозрачного — 999999 тенге за квадратный метр.")], max_retries=0)
    response = call(app_client, execution_mode="model_first").json()
    assert response["verifier_reject_count"] == 1
    assert len(items(app_client, category="verifier_reject")) == 1


def test_review_resolution_requires_expected_version_and_cannot_cross_dataset(app_client):
    turn(app_client, "Рифленое прозрачное 8 мм 400×300 мм 2 шт.")
    item = items(app_client)[0]
    path = f"/api/v1/assistant/review-items/{item['item_id']}/resolve"
    body = {"dataset_id": "ds-a", "expected_version": item["version"], "resolved_by": "Manager 1",
            "resolution_note": "Запрос передан ответственному; цена не добавлена в KB."}
    response = app_client.post(path, json=body)
    assert response.status_code == 200 and response.json()["status"] == "resolved"
    assert app_client.post(path, json=body).status_code == 409
    assert items(app_client, status="open") == []
    app_client.sources.add_kb("other", KB_PATH.read_bytes())
    assert app_client.post(path, json={**body, "dataset_id": "other"}).status_code == 404


def test_workspace_preview_is_read_only_then_existing_versioned_api_applies_exact_bytes(app_client):
    seed_workspace(app_client)
    turn(app_client, "Нужна установка стекла 4 мм")
    item = items(app_client)[0]
    raw = modified_kb(9000)
    original_head = app_client.get("/api/v1/datasets/ds-a/kb").json()
    path = f"/api/v1/assistant/review-items/{item['item_id']}/kb-preview"
    body = {"dataset_id": "ds-a", "expected_kb_version": kb_version(app_client), "proposed_content": raw.decode()}
    response = app_client.post(path, json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["changed_products"] == ["steklo-6-prozrachnoe"]
    assert preview["requires_explicit_human_confirmation"] is True
    assert preview["proposed_sha256"] == hashlib.sha256(raw).hexdigest()
    assert app_client.get("/api/v1/datasets/ds-a/kb").json() == original_head
    applied = app_client.post(preview["apply_path"], data={"expected_version": preview["expected_platform_version"]},
                              files={"file": ("ksm_knowledge_base.json", raw, "application/json")},
                              headers={"Idempotency-Key": "preview-apply-1"})
    assert applied.status_code == 200, applied.text
    assert applied.json()["sha256"] == preview["proposed_sha256"]
    conflict = app_client.post(preview["apply_path"], data={"expected_version": preview["expected_platform_version"]},
                               files={"file": ("ksm_knowledge_base.json", raw, "application/json")},
                               headers={"Idempotency-Key": "preview-apply-2"})
    assert conflict.status_code == 409


def test_contest_preview_blocked(app_client):
    seed_workspace(app_client, "contest")
    turn(app_client, "Нужна установка стекла 4 мм")
    item = items(app_client)[0]
    path = f"/api/v1/assistant/review-items/{item['item_id']}/kb-preview"
    body = {"dataset_id": "ds-a", "expected_kb_version": kb_version(app_client), "proposed_content": modified_kb(9000).decode()}
    assert app_client.post(path, json=body).status_code == 409


def test_invalid_or_stale_preview_cannot_mutate_workspace(app_client):
    seed_workspace(app_client)
    turn(app_client, "Нужна установка стекла 4 мм")
    item = items(app_client)[0]
    path = f"/api/v1/assistant/review-items/{item['item_id']}/kb-preview"
    body = {"dataset_id": "ds-a", "expected_kb_version": kb_version(app_client), "proposed_content": modified_kb(9000).decode()}
    assert app_client.post(path, json={**body, "expected_kb_version": "stale"}).status_code == 409
    assert app_client.post(path, json={**body, "proposed_content": "{}"}).status_code == 422
    assert app_client.get("/api/v1/datasets/ds-a/kb").json()["version"] == 0


def correction(client, client_text, manager_text, dialog_id="dialog"):
    response = client.post("/api/v1/dialogs/corrections", json={"dataset_id": "ds-a", "kb_version": kb_version(client),
        "id": dialog_id, "client": client_text, "manager": manager_text})
    assert response.status_code == 200, response.text
    return response.json()


def test_verified_manager_draft_binds_canonical_product_price_unit_and_source_without_history_changes(app_client):
    original = turn(app_client, "Стекло 6 мм прозрачное 450×370 мм с евро-кромкой по всем сторонам")
    before = app_client.get(f"/api/v1/assistant/conversations/{original['conversation_id']}", params={"dataset_id": "ds-a"}).json()
    draft = correction(app_client, "Сколько стоит стекло 6 мм прозрачное за м²?", "Цена 1000 тг за м².")
    assert draft["status"] == "DRAFT_VERIFIED"
    assert draft["applicable_price_tg"] == "8000" and draft["unit"] == "за м²"
    assert draft["catalog_product_id"] == "steklo-6-prozrachnoe" and draft["price_meaning"] == "per_m2"
    assert draft["source_ref"] and draft["evidence"] and draft["requires_human_review"] is True
    assert correction(app_client, "Сколько стоит стекло 6 мм прозрачное за м²?", "Цена 1000 тг за м².") == draft
    after = app_client.get(f"/api/v1/assistant/conversations/{original['conversation_id']}", params={"dataset_id": "ds-a"}).json()
    assert after == before
    with app_client.app.state.session_factory() as session:
        assert len(session.scalars(select(TurnRow)).all()) == 1
        assert len(session.scalars(select(QualityCheckRow)).all()) == 0
    saved = app_client.get(f"/api/v1/dialogs/corrections/{draft['draft_id']}", params={"dataset_id": "ds-a"})
    assert saved.status_code == 200 and saved.json() == draft


def test_ambiguous_unknown_or_already_correct_manager_reply_is_not_invented(app_client):
    ambiguous = correction(app_client, "Нужно зеркало 4 мм за квадратный метр", "Цена 1000 тг за м².", "ambiguous")
    assert ambiguous["status"] == "NEEDS_REVIEW" and ambiguous["answer"] is None
    assert ambiguous["applicable_price_tg"] is None
    unknown = correction(app_client, "Рифленое прозрачное 8 мм 400×300 мм 2 шт.", "Итого 1000 тг.", "unknown")
    assert unknown["status"] == "NEEDS_REVIEW" and unknown["answer"] is None
    correct = correction(app_client, "Стекло 6 мм прозрачное за м²", "Цена 8000 тг за м².", "correct")
    assert correct["status"] == "NOT_NEEDED" and correct["answer"] is None


def test_batch_accepted_review_metadata_deduplicates_without_engine(app_client):
    result = {"provenance": {"kb_version": kb_version(app_client), "answer_paths": [
        {"id": "new-id", "review_user_text": "Нужен неизвестный материал", "review_reasons": {"kb_fact": ["product_not_in_kb"]}},
    ]}}
    with app_client.app.state.session_factory.begin() as session:
        record_accepted_batch_reviews(session, "ds-a", result)
    with app_client.app.state.session_factory.begin() as session:
        record_accepted_batch_reviews(session, "ds-a", result)
    queued = items(app_client)
    assert len(queued) == 1 and queued[0]["occurrences"] == 2
    assert queued[0]["conversation_id"] == "batch:new-id"


def test_http_batch_preserves_uncertainty_without_inventing_a_customer_turn(app_client):
    text = "Стекло 6 мм прозрачное 450×370 мм с кромкой по выбранным сторонам"
    response = app_client.post("/api/v1/assistant/batch", json={
        "dataset_id": "ds-a", "kb_version": kb_version(app_client), "allow_ai": False,
        "questions": [{"id": "new-input-id", "question": text}],
    })
    assert response.status_code == 200, response.text
    rows = response.json()["answers"]
    assert len(rows) == 1 and rows[0]["id"] == "new-input-id"
    assert rows[0]["status"] == "clarification" and rows[0]["clarification"]
    queued = items(app_client, category="missing_parameter")
    assert len(queued) == 1 and queued[0]["user_text"] == text
    with app_client.app.state.session_factory() as session:
        assert session.scalars(select(TurnRow)).all() == []


def test_review_snippet_matches_shared_orm_and_downgrades(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.db'}")
    with engine.begin() as connection:
        intelligence_reviews_0007.upgrade(Operations(MigrationContext.configure(connection)))
    inspector = inspect(engine)
    for table in POST_INTELLIGENCE_TABLES:
        assert {c["name"]: c["nullable"] for c in inspector.get_columns(table.name)} == {c.name: c.nullable for c in table.columns}
    with engine.begin() as connection:
        intelligence_reviews_0007.downgrade(Operations(MigrationContext.configure(connection)))
    assert not set(inspect(engine).get_table_names())
