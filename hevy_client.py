import os

import httpx
from cryptography.fernet import Fernet

from database import get_db

_BASE_URL = "https://api.hevyapp.com/v1"
_SETTINGS_KEY = "hevy_api_key"
_FERNET_KEY_PATH = os.getenv("FERNET_KEY_PATH", "/data/app.key")
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    if os.path.exists(_FERNET_KEY_PATH):
        with open(_FERNET_KEY_PATH, "rb") as f:
            key = f.read().strip()
        try:
            _fernet = Fernet(key)
        except Exception as exc:
            raise ValueError(
                f"Fernet key file exists but is invalid/corrupt: {_FERNET_KEY_PATH}"
            ) from exc
        return _fernet

    key = Fernet.generate_key()
    key_dir = os.path.dirname(_FERNET_KEY_PATH)
    if key_dir:
        os.makedirs(key_dir, exist_ok=True)
    with open(_FERNET_KEY_PATH, "wb") as f:
        f.write(key)
    try:
        os.chmod(_FERNET_KEY_PATH, 0o600)
    except OSError:
        pass  # Windows does not enforce POSIX permissions.
    _fernet = Fernet(key)
    return _fernet


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


def save_api_key(raw_key: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_SETTINGS_KEY, _encrypt(raw_key)),
        )


def get_api_key() -> str | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (_SETTINGS_KEY,)
        ).fetchone()
    if row is None:
        return None
    return _decrypt(row["value"])


class HevyClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_api_key()

    def _headers(self) -> dict:
        if not self.api_key:
            raise ValueError("No Hevy API key configured.")
        return {"api-key": self.api_key}

    def sync_exercise_cache(self) -> int:
        """Fetch all exercise templates from Hevy and upsert into hevy_exercise_cache."""
        exercises: list[dict] = []
        page = 1
        with httpx.Client(timeout=30) as client:
            while True:
                resp = client.get(
                    f"{_BASE_URL}/exercise_templates",
                    headers=self._headers(),
                    params={"page": page, "pageSize": 100},
                )
                resp.raise_for_status()
                data = resp.json()
                exercises.extend(data.get("exercise_templates", []))
                if page >= data.get("page_count", 1):
                    break
                page += 1

        with get_db() as conn:
            conn.executemany(
                """
                INSERT INTO hevy_exercise_cache (id, title, primary_muscle)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    primary_muscle = excluded.primary_muscle,
                    cached_at = CURRENT_TIMESTAMP
                """,
                [
                    (e["id"], e["title"], e.get("primary_muscle_group"))
                    for e in exercises
                ],
            )

        return len(exercises)

    def list_workouts(self, page: int = 1, page_size: int = 10) -> dict:
        """Fetch one page of the account's workouts. Raises on HTTP or network errors."""
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{_BASE_URL}/workouts",
                headers=self._headers(),
                params={"page": page, "pageSize": page_size},
            )
            resp.raise_for_status()
            return resp.json()

    def list_body_measurements(self, page: int = 1, page_size: int = 10) -> dict:
        """Fetch one page of daily body measurements, newest first. Raises on HTTP or network errors."""
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{_BASE_URL}/body_measurements",
                headers=self._headers(),
                params={"page": page, "pageSize": page_size},
            )
            resp.raise_for_status()
            return resp.json()

    def exercise_history(self,exercise_template_id: str) -> list[dict]:
        """Every logged set for one exercise across all sessions, newest first. Raises on HTTP or network errors."""
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{_BASE_URL}/exercise_history/{exercise_template_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("exercise_history") or []

    def get_workout(self, workout_id: str) -> dict:
        """Read one saved workout by ID. Never modifies Hevy."""
        from urllib.parse import quote
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{_BASE_URL}/workouts/{quote(workout_id, safe='')}", headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            return data.get("workout", data)

    def create_workout(self, body: dict) -> dict:
        """Create a workout in Hevy and return it. Raises on HTTP or network errors.
        Hevy answers 201 with {"workout": [<workout>]} (a single-element list)."""
        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{_BASE_URL}/workouts", headers=self._headers(), json=body)
            resp.raise_for_status()
            created = resp.json().get("workout")
        if isinstance(created, list):
            created = created[0] if created else {}
        return created or {}
