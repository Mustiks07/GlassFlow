"""Rectangle packing heuristics (MaxRects and Guillotine) in *inflated* coordinates.

Exact reduction used everywhere: inflate each part by GAP on width and height and the trimmed working
area by GAP too. Then two inflated rectangles do not overlap <=> the real parts are separated by
>= GAP on at least one axis, and an inflated rectangle inside the inflated container <=> the real part
respects the 5 mm trim. Coordinates of the inflated rectangle's origin equal the real (x, y).

Algorithms follow the classic MaxRects / Guillotine families (J. Jylänki, "A Thousand Ways to Pack the
Bin", 2010; also summarised in the rectpack README) and the research prototype in analysis/cutting.
Every produced layout is still checked by the independent validator in ``geometry.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain import GAP_MM, TRIM_MM

Rect = tuple[int, int, int, int]  # x, y, w, h (inflated)

HEURISTICS = ("bssf", "baf", "blsf", "bl")
SPLITS = ("sas", "las", "maxarea", "minarea")


@dataclass(slots=True)
class Item:
    key: int
    length: int
    width: int


def container(length_mm: int, width_mm: int) -> Rect:
    return (TRIM_MM, TRIM_MM, length_mm - 2 * TRIM_MM + GAP_MM, width_mm - 2 * TRIM_MM + GAP_MM)


def _score(heuristic: str, fx: int, fy: int, fw: int, fh: int, w: int, h: int) -> tuple:
    lw, lh = fw - w, fh - h
    short, long_ = (lw, lh) if lw < lh else (lh, lw)
    if heuristic == "bssf":
        return (short, long_, fy, fx)
    if heuristic == "baf":
        return (fw * fh - w * h, short, fy, fx)
    if heuristic == "blsf":
        return (long_, short, fy, fx)
    return (fy + h, fx, short)  # bottom-left


class MaxRectsBin:
    __slots__ = ("free", "placed", "heuristic")

    def __init__(self, length_mm: int, width_mm: int, heuristic: str = "bssf"):
        self.free: list[Rect] = [container(length_mm, width_mm)]
        self.placed: list[tuple[int, int, int, int]] = []  # key, x, y, rot
        self.heuristic = heuristic

    def best(self, item: Item, rotations: tuple[int, ...] = (0, 1)) -> tuple | None:
        best = None
        for rot in rotations:
            w = (item.width if rot else item.length) + GAP_MM
            h = (item.length if rot else item.width) + GAP_MM
            for fx, fy, fw, fh in self.free:
                if w <= fw and h <= fh:
                    score = _score(self.heuristic, fx, fy, fw, fh, w, h)
                    if best is None or score < best[0]:
                        best = (score, fx, fy, w, h, rot)
        return best

    def insert_at(self, key: int, x: int, y: int, w: int, h: int, rot: int) -> None:
        new: list[Rect] = []
        for fx, fy, fw, fh in self.free:
            if x >= fx + fw or x + w <= fx or y >= fy + fh or y + h <= fy:
                new.append((fx, fy, fw, fh))
                continue
            if x > fx:
                new.append((fx, fy, x - fx, fh))
            if x + w < fx + fw:
                new.append((x + w, fy, fx + fw - x - w, fh))
            if y > fy:
                new.append((fx, fy, fw, y - fy))
            if y + h < fy + fh:
                new.append((fx, y + h, fw, fy + fh - y - h))
        self.free = _prune(new)
        self.placed.append((key, x, y, rot))

    def apply(self, key: int, choice: tuple) -> None:
        _, x, y, w, h, rot = choice
        self.insert_at(key, x, y, w, h, rot)

    def insert(self, item: Item, rotations: tuple[int, ...] = (0, 1)) -> bool:
        choice = self.best(item, rotations)
        if choice is None:
            return False
        self.apply(item.key, choice)
        return True


def _prune(rects: list[Rect]) -> list[Rect]:
    rects = list(dict.fromkeys(rects))
    rects.sort(key=lambda r: -r[2] * r[3])
    kept: list[Rect] = []
    for r in rects:
        rx, ry, rw, rh = r
        if any(rx >= kx and ry >= ky and rx + rw <= kx + kw and ry + rh <= ky + kh for kx, ky, kw, kh in kept):
            continue
        kept.append(r)
    return kept


class GuillotineBin:
    __slots__ = ("free", "placed", "heuristic", "split")

    def __init__(self, length_mm: int, width_mm: int, heuristic: str = "baf", split: str = "sas"):
        self.free: list[Rect] = [container(length_mm, width_mm)]
        self.placed: list[tuple[int, int, int, int]] = []
        self.heuristic = heuristic
        self.split = split

    def best(self, item: Item, rotations: tuple[int, ...] = (0, 1)) -> tuple | None:
        best = None
        for index, (fx, fy, fw, fh) in enumerate(self.free):
            for rot in rotations:
                w = (item.width if rot else item.length) + GAP_MM
                h = (item.length if rot else item.width) + GAP_MM
                if w <= fw and h <= fh:
                    score = _score(self.heuristic, fx, fy, fw, fh, w, h)
                    if best is None or score < best[0]:
                        best = (score, index, w, h, rot)
        return best

    def insert(self, item: Item, rotations: tuple[int, ...] = (0, 1)) -> bool:
        choice = self.best(item, rotations)
        if choice is None:
            return False
        self.apply(item.key, choice)
        return True

    def apply(self, key: int, choice: tuple) -> None:
        _, index, w, h, rot = choice
        fx, fy, fw, fh = self.free.pop(index)
        lw, lh = fw - w, fh - h
        if self.split == "sas":
            horizontal = lw < lh
        elif self.split == "las":
            horizontal = lw >= lh
        elif self.split == "maxarea":
            horizontal = lw * fh > w * lh
        else:
            horizontal = lw * fh <= w * lh
        # ``horizontal``: the right leftover spans only the item height, the bottom spans the full width.
        if horizontal:
            parts = [(fx + w, fy, lw, h), (fx, fy + h, fw, lh)]
        else:
            parts = [(fx + w, fy, lw, fh), (fx, fy + h, w, lh)]
        self.free.extend(p for p in parts if p[2] > GAP_MM and p[3] > GAP_MM)
        self.placed.append((key, fx, fy, rot))


def make_bin(kind: str, length_mm: int, width_mm: int, heuristic: str, split: str = "sas"):
    if kind == "maxrects":
        return MaxRectsBin(length_mm, width_mm, heuristic)
    return GuillotineBin(length_mm, width_mm, heuristic, split)


def pack_sequence(
    kind: str, length_mm: int, width_mm: int, items: list[Item], heuristic: str, split: str = "sas"
) -> list[tuple[int, int, int, int]]:
    """Greedily insert ``items`` in the given order into one remnant; returns (key, x, y, rot)."""
    bin_ = make_bin(kind, length_mm, width_mm, heuristic, split)
    for item in items:
        bin_.insert(item)
    return bin_.placed
