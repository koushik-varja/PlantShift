from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Pytest imports conftest before collecting test modules. Configure protected API
# controls and an isolated SQLite database before backend.app.db/main are imported.
_TEST_DB = Path(tempfile.gettempdir()) / f"plantshift_pytest_{os.getpid()}.db"
_TEST_DB.unlink(missing_ok=True)
os.environ["ADMIN_TOKEN"] = "test-token"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    # SQLAlchemy can keep a pooled SQLite connection open on Windows.
    # Dispose the engine before deleting the temporary test database.
    from backend.app.db import engine

    engine.dispose()
    _TEST_DB.unlink(missing_ok=True)
