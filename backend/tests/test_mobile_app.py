"""安卓 App：服务器提供安装包（/app.apk）和版本号（/api/app-info），不用登录。"""

from app.storage_service import data_dir


def test_app_info_and_download(client):
    d = data_dir() / "app"
    for f in ("workrecord.apk", "version.txt"):
        (d / f).unlink(missing_ok=True)
    assert client.get("/api/app-info").json()["version"] is None
    assert client.get("/app.apk").status_code == 404
    d.mkdir(parents=True, exist_ok=True)
    (d / "workrecord.apk").write_bytes(b"PK fake apk")
    (d / "version.txt").write_text("1.0.0\n", encoding="utf-8")
    assert client.get("/api/app-info").json() == {"version": "1.0.0", "url": "/app.apk"}
    r = client.get("/app.apk")
    assert r.status_code == 200 and r.content == b"PK fake apk"
    assert r.headers["content-type"] == "application/vnd.android.package-archive"
