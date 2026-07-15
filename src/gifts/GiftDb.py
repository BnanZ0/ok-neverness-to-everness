import json
import os

DB_SCHEMA_VERSION = 1


def default_db() -> dict:
    return {
        "schema_version": DB_SCHEMA_VERSION,
        "profiles": {},
    }


def normalize_slots(value) -> list[int]:
    """Keep valid slot indexes in their user-selected priority order."""
    if not isinstance(value, list):
        return []
    slots = []
    for item in value:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= index < 10 and index not in slots:
            slots.append(index)
    return slots


def normalize_profile(profile_id: str, value) -> dict | None:
    if not isinstance(value, dict):
        return None

    frame_id = str(value.get("frame_id", "")).strip()
    if not frame_id:
        return None

    try:
        target_count = min(3, max(1, int(value.get("target_count", 3))))
    except (TypeError, ValueError):
        target_count = 3

    display_name = str(value.get("display_name", "")).strip() or profile_id
    blocked_slots = normalize_slots(value.get("blocked_slots", []))
    return {
        "display_name": display_name,
        "frame_id": frame_id,
        "selected_slots": [
            slot
            for slot in normalize_slots(value.get("selected_slots", []))
            if slot not in blocked_slots
        ],
        "blocked_slots": blocked_slots,
        "target_count": target_count,
        "enabled": bool(value.get("enabled", True)),
    }


def validate_db(db: dict) -> bool:
    """Normalize in place and return whether the data was changed."""
    changed = False
    if not isinstance(db.get("profiles"), dict):
        db["profiles"] = {}
        changed = True

    profiles = {}
    for profile_id, profile in db["profiles"].items():
        profile_id = str(profile_id).strip()
        normalized = normalize_profile(profile_id, profile)
        if not profile_id or normalized is None:
            changed = True
            continue
        profiles[profile_id] = normalized
        if normalized != profile:
            changed = True
    if profiles != db["profiles"]:
        db["profiles"] = profiles
        changed = True

    if db.get("schema_version") != DB_SCHEMA_VERSION:
        db["schema_version"] = DB_SCHEMA_VERSION
        changed = True
    return changed


def load_db(path: str, logger=None) -> dict:
    data = default_db()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                loaded = json.load(file)
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception as error:
            if logger:
                logger.error("Failed to load gift configuration", error)
    validate_db(data)
    return data


def save_db(path: str, db: dict, logger=None) -> None:
    try:
        validate_db(db)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary_path = f"{path}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as file:
            json.dump(db, file, ensure_ascii=False, indent=4)
        os.replace(temporary_path, path)
    except Exception as error:
        if logger:
            logger.error("Failed to save gift configuration", error)
        else:
            raise
