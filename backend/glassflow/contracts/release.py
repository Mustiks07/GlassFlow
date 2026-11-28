from typing import Literal

from .common import DTO


class ReleaseCheckItem(DTO):
    name: str
    status: Literal["ready", "missing", "mismatch", "needs_review"]
    message: str


class ReleaseCheck(DTO):
    run_id: str
    items: list[ReleaseCheckItem]
    files_coherent: bool
    contest_accepted: Literal[False] = False
