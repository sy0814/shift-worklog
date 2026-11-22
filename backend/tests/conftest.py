import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["RUN_SCHEDULER"] = "false"
os.environ["DEEPSEEK_API_KEY"] = ""  # 默认不翻译；翻译测试里单独打开

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client, username, password):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_h(client):
    return login(client, "admin", "admin123")


@pytest.fixture(scope="session")
def leader_h(client):
    return login(client, "t1_leader1", "t1_leader1")
