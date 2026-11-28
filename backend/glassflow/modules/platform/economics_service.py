from sqlalchemy import select

from glassflow.contracts.economics import EconomicsScenario
from glassflow.core.errors import AppError
from glassflow.core.models import AuditRow, ObjectRow, now, uid
from glassflow.core.uow import audit, canonical_hash, get_object
from glassflow.modules.platform.economics import serialized_result
from glassflow.modules.platform.imports import dataset


def calculate(session, body, correlation, scenario_id=None):
    source = dataset(session, body.dataset_id)
    if scenario_id:
        row = get_object(session, source.id, "economics_scenario", scenario_id, body.expected_version)
        name, version = row.data["name"], row.version + 1
    else:
        scenario_id, name, version = uid(), body.name, 0
        row = ObjectRow(dataset_id=source.id, kind="economics_scenario", id=scenario_id, version=0, data={})
        session.add(row)
    inputs = body.inputs.model_dump(mode="json")
    results = serialized_result(inputs)
    scenario = EconomicsScenario(dataset_id=source.id, name=name, scenario_id=scenario_id, version=version,
                                  inputs=inputs, source_hashes=source.source_hashes,
                                  input_hash=canonical_hash(inputs), result_hash=canonical_hash(results),
                                  results=results, created_at=now())
    row.version, row.data = version, scenario.model_dump(mode="json")
    audit(session, source.id, "economics.calculate", scenario_id, correlation, scenario=row.data)
    return row.data


def load(session, dataset_id, scenario_id, version=None):
    row = get_object(session, dataset_id, "economics_scenario", scenario_id)
    if version is None or row.version == version:
        return EconomicsScenario.model_validate(row.data)
    for event in session.scalars(select(AuditRow).where(AuditRow.dataset_id == dataset_id,
                            AuditRow.object_id == scenario_id, AuditRow.action == "economics.calculate")):
        snapshot = event.versions["scenario"]
        if snapshot["version"] == version:
            return EconomicsScenario.model_validate(snapshot)
    raise AppError(404, "SCENARIO_VERSION_NOT_FOUND", "Такой версии сценария нет.")


def pdf_evidence(scenario):
    data = scenario.model_dump(mode="json")
    if (canonical_hash(data["inputs"]) != scenario.input_hash
            or canonical_hash(serialized_result(data["inputs"])) != scenario.result_hash):
        raise AppError(409, "SCENARIO_INTEGRITY", "Снимок сценария не прошел повторную проверку.")
    return {"synthetic": scenario.inputs.measurement_status == "synthetic", "economics": data["inputs"],
            "scenario_identity": data,
            "manifest": {"run_id": f"scenario:{scenario.scenario_id}", "dataset_id": scenario.dataset_id,
                         "input_hash": scenario.input_hash, "source_hashes": scenario.source_hashes}}
