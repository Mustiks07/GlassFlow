"""Shared fixtures. The open organisers' pack is read as *source data* (KB, materials) only;
evaluation KEY files are never loaded by runtime tests (see test_no_key_in_runtime.py)."""

from pathlib import Path

import pytest

from glassflow.modules.intelligence.assistant.local import LocalEngine
from glassflow.modules.intelligence.catalog.kb import parse_knowledge_base
from glassflow.modules.intelligence.catalog.mapping import derive_all
from glassflow.modules.intelligence.catalog.materials import parse_materials

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "inputs" / "PACK_for_teams"
KB_PATH = PACK / "2_assistant_crm" / "ksm_knowledge_base.json"
MATERIALS_PATH = PACK / "1_ostatki" / "materials.csv"


@pytest.fixture(scope="session")
def kb_bytes() -> bytes:
    return KB_PATH.read_bytes()


@pytest.fixture(scope="session")
def kb(kb_bytes):
    return parse_knowledge_base(kb_bytes)


@pytest.fixture(scope="session")
def materials():
    return parse_materials(MATERIALS_PATH.read_bytes())


@pytest.fixture(scope="session")
def mappings(kb, materials):
    return derive_all(kb, materials)


@pytest.fixture()
def engine(kb, mappings):
    return LocalEngine(kb, mappings, dataset_id="test-dataset")


def numbers_in(text: str) -> set[float]:
    """Same number reading as the organisers' selfcheck (spaces/NBSP grouped, comma decimal)."""
    import re

    text = text.replace(" ", " ")
    found = set()
    for match in re.finditer(r"\d[\d  ]*(?:[.,]\d+)?", text):
        try:
            found.add(float(re.sub(r"[  ]", "", match.group()).replace(",", ".")))
        except ValueError:
            pass
    return found
