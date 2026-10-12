"""Map portrait images from google-images/artisans into public URLs for catalog seeding.

Only artisans with a real image file in this folder are included in the catalog.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from google_images_catalog import artisan_roster, list_images, norm, slug, state_metadata
from india_data import STATE_COORDS, STATE_ZONE

ROOT = Path(__file__).resolve().parent.parent / "final_hidden_india"
ARTISAN_IMAGES_ROOT = ROOT / "google-images" / "artisans"
PUBLIC_ARTISANS = ROOT / "public" / "images" / "artisans"

# Folder names that do not resolve cleanly via state name matching
ARTISAN_DIR_TO_STATE: dict[str, str] = {
    "harayana_face_male": "Haryana",
    "Maharashtrian artisan": "Maharashtra",
    "Maharashtrian_artisan": "Maharashtra",
}


@dataclass
class PortraitArtisan:
    state: str
    name: str
    bio: str
    tag: str
    avatar: str
    category: str
    zone: str


def resolve_artisan_folder(dir_name: str) -> str | None:
    if dir_name in ARTISAN_DIR_TO_STATE:
        return ARTISAN_DIR_TO_STATE[dir_name]

    target = norm(dir_name.replace("&", "and"))
    for state in STATE_COORDS:
        st_norm = norm(state)
        if st_norm in target or target.startswith(st_norm):
            return state

    underscored = dir_name.replace(" ", "_").replace("&", "_and_")
    from google_images_catalog import resolve_state

    resolved = resolve_state(underscored)
    if resolved:
        return resolved

    if "haryana" in target or "harayana" in target:
        return "Haryana"
    if "maharashtra" in target or "maharashtrian" in target:
        return "Maharashtra"
    return None


def copy_artisan_portrait(state: str, index: int, source: Path) -> str:
    dest_dir = PUBLIC_ARTISANS / slug(state)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"portrait-{index + 1}{source.suffix.lower()}"
    if not dest.exists() or dest.stat().st_mtime < source.stat().st_mtime:
        shutil.copy2(source, dest)
    return f"/images/artisans/{slug(state)}/{dest.name}"


def unique_artisan_name(base: str, used: set[str]) -> str:
    if base not in used:
        used.add(base)
        return base
    n = 2
    while f"{base} ({n})" in used:
        n += 1
    candidate = f"{base} ({n})"
    used.add(candidate)
    return candidate


def scan_portrait_artisans() -> dict[str, list[PortraitArtisan]]:
    """Return state -> portrait artisans (one per image file in google-images/artisans)."""
    if not ARTISAN_IMAGES_ROOT.is_dir():
        return {}

    by_state: dict[str, list[PortraitArtisan]] = {}
    used_names: dict[str, set[str]] = {}

    for folder in sorted(ARTISAN_IMAGES_ROOT.iterdir()):
        if not folder.is_dir():
            continue
        state = resolve_artisan_folder(folder.name)
        if not state:
            continue

        images = list_images(folder)
        if not images:
            continue

        _, artisan_category, _, _ = state_metadata(state)
        zone = STATE_ZONE.get(state, "")
        roster = artisan_roster(state)
        used = used_names.setdefault(state, set())

        portraits: list[PortraitArtisan] = []
        for i, img_path in enumerate(images):
            roster_name, roster_bio, tag = roster[i % len(roster)]
            name = unique_artisan_name(roster_name, used)
            avatar = copy_artisan_portrait(state, i, img_path)
            portraits.append(
                PortraitArtisan(
                    state=state,
                    name=name,
                    bio=roster_bio,
                    tag=tag,
                    avatar=avatar,
                    category=artisan_category,
                    zone=zone,
                )
            )

        if portraits:
            by_state[state] = portraits

    return by_state


def portrait_summary(portraits: dict[str, list[PortraitArtisan]]) -> dict:
    total = sum(len(v) for v in portraits.values())
    return {"states": len(portraits), "artisans": total}
