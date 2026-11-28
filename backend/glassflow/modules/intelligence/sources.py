"""Where the intelligence module gets a dataset's KB and materials.

GPT Pro's dataset repository implements ``IntelligenceSources`` over immutable snapshots.
Until it is wired, the router composes ``PackDirectorySources`` — the *original* organisers'
open pack (KB + materials.csv only) exposed as one explicitly named bootstrap dataset. It
never opens ``*_KEY`` files and is reported as ``dev_pack_bootstrap`` in evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DEV_PACK_DATASET_ID = "open-pack"
KB_RELATIVE = Path("2_assistant_crm") / "ksm_knowledge_base.json"
MATERIALS_RELATIVE = Path("1_ostatki") / "materials.csv"


class DatasetNotFound(LookupError):
    def __init__(self, dataset_id: str):
        super().__init__(dataset_id)
        self.dataset_id = dataset_id


class SourceVersionNotFound(LookupError):
    pass


@dataclass(frozen=True)
class SourceDocument:
    dataset_id: str
    kind: str  # kb | materials
    name: str
    content: bytes
    origin: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


class IntelligenceSources(Protocol):
    def knowledge_base(self, dataset_id: str, version: str | None = None) -> SourceDocument: ...

    def kb_history(self, dataset_id: str) -> list[SourceDocument]: ...

    def materials(self, dataset_id: str) -> SourceDocument | None: ...


class InMemorySources:
    """Explicit in-process sources (tests, Pro adapters, working-copy price edits)."""

    def __init__(self) -> None:
        self._kb: dict[str, list[SourceDocument]] = {}
        self._materials: dict[str, SourceDocument] = {}

    def add_kb(self, dataset_id: str, content: bytes, name: str = "ksm_knowledge_base.json", origin: str = "memory") -> SourceDocument:
        document = SourceDocument(dataset_id, "kb", name, content, origin)
        self._kb.setdefault(dataset_id, []).append(document)
        return document

    def set_materials(self, dataset_id: str, content: bytes, origin: str = "memory") -> None:
        self._materials[dataset_id] = SourceDocument(dataset_id, "materials", "materials.csv", content, origin)

    def knowledge_base(self, dataset_id: str, version: str | None = None) -> SourceDocument:
        history = self._kb.get(dataset_id)
        if not history:
            raise DatasetNotFound(dataset_id)
        if version is None:
            return history[-1]
        from .catalog.kb import kb_version_for

        for document in history:
            if kb_version_for(document.content)[0] == version:
                return document
        raise SourceVersionNotFound(version)

    def kb_history(self, dataset_id: str) -> list[SourceDocument]:
        if dataset_id not in self._kb:
            raise DatasetNotFound(dataset_id)
        return list(self._kb[dataset_id])

    def materials(self, dataset_id: str) -> SourceDocument | None:
        if dataset_id not in self._kb:
            raise DatasetNotFound(dataset_id)
        return self._materials.get(dataset_id)


class PackDirectorySources(InMemorySources):
    """Bootstrap: the unmodified open pack as dataset ``open-pack`` (KB/materials only)."""

    def __init__(self, pack_dir: Path, dataset_id: str = DEV_PACK_DATASET_ID):
        super().__init__()
        kb_path = pack_dir / KB_RELATIVE
        materials_path = pack_dir / MATERIALS_RELATIVE
        if kb_path.is_file():
            self.add_kb(dataset_id, kb_path.read_bytes(), kb_path.name, "dev_pack_bootstrap")
            if materials_path.is_file():
                self.set_materials(dataset_id, materials_path.read_bytes(), "dev_pack_bootstrap")


def default_pack_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "inputs" / "PACK_for_teams"
