import os

from app import database


def create_expense(client, cookies):
    resp = client.post(
        "/api/expenses",
        headers=cookies,
        json={"amount": 12.5, "description": "Coffee", "category": "Food", "date": "2026-08-07"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def upload(client, cookies, expense_id, files):
    return client.post(f"/api/expenses/{expense_id}/photos", headers=cookies, files=files)


def jpeg_file(name="receipt.jpg", data=b"\xff\xd8\xff\xe0fake-jpeg-bytes"):
    return ("files", (name, data, "image/jpeg"))


def test_upload_photo_to_own_expense(client, alice):
    expense = create_expense(client, alice)
    resp = upload(client, alice, expense["id"], [jpeg_file()])
    assert resp.status_code == 201
    photos = resp.json()
    assert len(photos) == 1
    assert isinstance(photos[0]["id"], int)

    listing = client.get("/api/expenses?month=2026-08", headers=alice).json()
    assert [p["id"] for p in listing[0]["photos"]] == [photos[0]["id"]]


def test_upload_multiple_photos_at_once(client, alice):
    expense = create_expense(client, alice)
    resp = upload(client, alice, expense["id"], [jpeg_file("a.jpg"), jpeg_file("b.jpg")])
    assert resp.status_code == 201
    assert len(resp.json()) == 2


def test_upload_requires_ownership(client, alice, bob):
    expense = create_expense(client, alice)
    resp = upload(client, bob, expense["id"], [jpeg_file()])
    assert resp.status_code == 404


def test_upload_to_missing_expense_404s(client, alice):
    resp = upload(client, alice, 999, [jpeg_file()])
    assert resp.status_code == 404


def test_upload_rejects_unsupported_content_type(client, alice):
    expense = create_expense(client, alice)
    resp = upload(client, alice, expense["id"], [("files", ("notes.txt", b"hello", "text/plain"))])
    assert resp.status_code == 400


def test_upload_rejects_oversized_file(client, alice):
    expense = create_expense(client, alice)
    huge = b"x" * (5 * 1024 * 1024 + 1)
    resp = upload(client, alice, expense["id"], [("files", ("big.jpg", huge, "image/jpeg"))])
    assert resp.status_code == 400


def test_upload_rejects_exceeding_max_photo_count(client, alice):
    expense = create_expense(client, alice)
    resp = upload(client, alice, expense["id"], [jpeg_file(f"{i}.jpg") for i in range(6)])
    assert resp.status_code == 400
    # nothing from the rejected batch should have been saved
    assert client.get("/api/expenses?month=2026-08", headers=alice).json()[0]["photos"] == []


def test_upload_rejects_when_existing_plus_new_exceeds_max(client, alice):
    expense = create_expense(client, alice)
    upload(client, alice, expense["id"], [jpeg_file(f"{i}.jpg") for i in range(4)])
    resp = upload(client, alice, expense["id"], [jpeg_file("a.jpg"), jpeg_file("b.jpg")])
    assert resp.status_code == 400


def test_get_photo_returns_original_bytes(client, alice):
    expense = create_expense(client, alice)
    data = b"\xff\xd8\xff\xe0some-jpeg-payload"
    photo_id = upload(client, alice, expense["id"], [jpeg_file(data=data)]).json()[0]["id"]

    resp = client.get(f"/api/expenses/{expense['id']}/photos/{photo_id}", headers=alice)
    assert resp.status_code == 200
    assert resp.content == data
    assert resp.headers["content-type"] == "image/jpeg"


def test_get_photo_requires_ownership(client, alice, bob):
    expense = create_expense(client, alice)
    photo_id = upload(client, alice, expense["id"], [jpeg_file()]).json()[0]["id"]

    resp = client.get(f"/api/expenses/{expense['id']}/photos/{photo_id}", headers=bob)
    assert resp.status_code == 404


def test_get_missing_photo_404s(client, alice):
    expense = create_expense(client, alice)
    resp = client.get(f"/api/expenses/{expense['id']}/photos/999", headers=alice)
    assert resp.status_code == 404


def test_deleting_expense_removes_photo_file_from_disk(client, alice):
    expense = create_expense(client, alice)
    upload(client, alice, expense["id"], [jpeg_file()])

    uploads = database.uploads_dir()
    assert len(os.listdir(uploads)) == 1

    resp = client.delete(f"/api/expenses/{expense['id']}", headers=alice)
    assert resp.status_code == 204
    assert os.listdir(uploads) == []
