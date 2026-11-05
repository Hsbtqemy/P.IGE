"""Images: upload, serve, attach to a paragraph, cleanup."""

import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from pige.server.app import CSRF_HEADER, create_app
from pige.server.auth import hash_password, new_api_token
from pige.server.config import Settings

PASSWORD = "correct horse battery staple"
_TOKEN, _TOKEN_HASH = new_api_token()


def png(w: int = 3, h: int = 2) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture()
def setup(tmp_path):
    settings = Settings(data_dir=tmp_path, password_hash=hash_password(PASSWORD), session_secret="s" * 48,
                        api_token_hashes=frozenset({_TOKEN_HASH}), cookie_secure=False, background_jobs=False)
    with TestClient(create_app(settings)) as c:
        c.headers.update({"Authorization": f"Bearer {_TOKEN}"})
        space = c.post("/api/v2/spaces", json={"name": "MSHS"}).json()
        yield c, tmp_path, space


def test_an_image_is_kept_served_and_attached(setup):
    c, root, space = setup
    up = c.post("/api/v2/files?name=tableau.png", content=png(), headers={"content-type": "image/png"})
    assert up.status_code == 201, up.text
    f = up.json()
    assert (f["mime"], f["width"], f["height"], f["entry_id"]) == ("image/png", 3, 2, None)
    got = c.get(f["url"])
    assert got.status_code == 200 and got.content == png() and got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"
    entry = c.post("/api/v2/entries", json={"entry_date": "2026-11-03", "space_id": space["id"], "body": "Tableau",
                                            "file_ids": [f["id"]]}).json()
    assert [x["id"] for x in entry["files"]] == [f["id"]]
    # Straight into an existing entry.
    second = c.post(f"/api/v2/files?entry_id={entry['id']}", content=png(5, 4)).json()
    assert len(c.get(f"/api/v2/entries/{entry['id']}").json()["files"]) == 2 and second["width"] == 5


def test_only_real_images_and_cleanup(setup):
    c, root, space = setup
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert c.post("/api/v2/files", content=svg, headers={"content-type": "image/png"}).status_code == 415
    assert c.post("/api/v2/files", content=b"x" * (8 * 1024 * 1024 + 1)).status_code == 413
    assert c.get("/api/v2/files/../../etc/passwd").status_code == 404
    f = c.post("/api/v2/files", content=png()).json()
    entry = c.post("/api/v2/entries", json={"entry_date": "2026-11-03", "space_id": space["id"], "body": "x",
                                            "file_ids": [f["id"]]}).json()
    web = TestClient(c.app)
    web.post("/api/login", json={"password": PASSWORD})
    assert web.delete(f"/api/v2/entries/{entry['id']}", headers={CSRF_HEADER: "web"}).status_code == 204
    assert c.get(f["url"]).status_code == 404
    on_disk = list((root / "files").glob("*/*.*"))
    assert len(on_disk) == 1  # the row went with the entry; the file goes at the next sweep
    from pige.server.api_files import FileStore
    assert FileStore(root / "files").sweep(c.app.state.model_store) == 1
    assert list((root / "files").glob("*/*.*")) == []


def test_attachments_of_a_mail_are_kept_once_and_downloaded(setup):
    c, root, space = setup
    mail = c.post("/api/v2/entries", json={"entry_date": "2026-11-05", "space_id": space["id"], "title": "Convention",
                                           "body": "Mail de A\n\nCi-joint.", "source": "mail",
                                           "mail_message_id": "<c1@x>"}).json()
    pdf = b"%PDF-1.4\n" + b"x" * 100
    url = f"/api/v2/files?attachment=1&entry_id={mail['id']}&name=convention%20sign%C3%A9e.pdf"
    first = c.post(url, content=pdf, headers={"content-type": "application/pdf"})
    assert first.status_code == 201, first.text
    f = first.json()
    assert (f["kind"], f["mime"]) == ("attachment", "application/pdf")
    assert c.post(url, content=pdf, headers={"content-type": "application/pdf"}).json()["id"] == f["id"]  # filed twice
    got = c.get(f["url"])
    assert got.content == pdf and got.headers["content-disposition"].startswith("attachment; filename*=UTF-8''convention")
    assert "sandbox" in got.headers["content-security-policy"]
    # HTML pretending to be anything: kept, but only ever downloaded as bytes.
    html = c.post(f"/api/v2/files?attachment=1&entry_id={mail['id']}&name=page.html", content=b"<script>x</script>",
                  headers={"content-type": "text/html"}).json()
    served = c.get(html["url"])
    assert served.headers["content-type"] == "application/octet-stream"
    entry = c.get(f"/api/v2/entries/{mail['id']}").json()
    assert sorted(x["kind"] for x in entry["files"]) == ["attachment", "attachment"]
    convs = c.get(f"/api/v2/conversations?space_id={space['id']}").json()
    full = c.get(f"/api/v2/conversations/{convs[0]['id']}").json()
    assert [x["name"] for x in full["mails"][0]["files"]] == ["convention signée.pdf", "page.html"]
    assert c.post("/api/v2/files?attachment=1&name=x.pdf", content=pdf).status_code == 400  # belongs to a mail
