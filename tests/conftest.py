"""
Shared pytest fixtures for the whole suite.

IMPORTANT: main.py runs init_db() and starts a background scheduler as a
side effect of being imported (not inside a proper FastAPI lifespan hook).
That means the test database MUST be pointed at a throwaway file via the
DATABASE_URL env var *before* `app.main` is imported anywhere — including
before pytest collects any other test module that might import it. That's
why this file sets the env vars at module level, above every other import,
and why conftest.py (which pytest always loads first) is the right place
for it rather than an autouse fixture.
"""
import os
import sys
import tempfile
from pathlib import Path

# --- Point the app at a throwaway SQLite file before app.main is ever imported ---
_TEST_DB_FILE = Path(tempfile.gettempdir()) / "techpro_crm_test.db"
if _TEST_DB_FILE.exists():
    _TEST_DB_FILE.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_FILE}"
os.environ["SESSION_SECRET"] = "test-session-secret-not-for-production"
os.environ["SETTINGS_ENCRYPTION_KEY"] = "kQqjXGz0Yb3g8h5m1nR7sT2vC4wA6dF9eH0iJ3kL5mN="  # fixed test key, not a real secret

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Staff  # noqa: E402
from app.auth import hash_pin  # noqa: E402


@pytest.fixture(scope="session")
def db_session():
    """Direct DB access for test setup/arrange steps (bypassing HTTP)."""
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture(scope="session", autouse=True)
def seed_roles(db_session):
    """The app seeds a default Owner (PIN 1234) on init_db(). Add one of
    each other role here so every test file can assume these exist,
    rather than each test file re-seeding its own staff."""
    existing = {s.role: s for s in db_session.query(Staff).all()}
    to_add = []
    if "manager" not in existing:
        to_add.append(Staff(id="test-manager", name="Test Manager", role="manager",
                             pin_hash=hash_pin("2222"), active=True))
    if "cashier" not in existing:
        to_add.append(Staff(id="test-cashier", name="Test Cashier", role="cashier",
                             pin_hash=hash_pin("3333"), active=True))
    if "technician" not in existing:
        to_add.append(Staff(id="test-technician", name="Test Technician", role="technician",
                             pin_hash=hash_pin("4444"), active=True))
    if to_add:
        db_session.add_all(to_add)
        db_session.commit()
    return {"owner": "1234", "manager": "2222", "cashier": "3333", "technician": "4444"}


def _login_client(pin: str) -> TestClient:
    client = TestClient(app)
    resp = client.post("/login", data={"pin": pin}, follow_redirects=False)
    assert resp.status_code == 303, f"Login with PIN {pin} failed: {resp.status_code}"
    return client


@pytest.fixture
def owner_client(seed_roles):
    return _login_client(seed_roles["owner"])


@pytest.fixture
def manager_client(seed_roles):
    return _login_client(seed_roles["manager"])


@pytest.fixture
def cashier_client(seed_roles):
    return _login_client(seed_roles["cashier"])


@pytest.fixture
def technician_client(seed_roles):
    return _login_client(seed_roles["technician"])


@pytest.fixture
def anon_client():
    """Never logs in — for testing that protected routes redirect/403."""
    return TestClient(app)
