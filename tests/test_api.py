"""Тесты операций интерфейса (методичка ДЗ 1, п. 2.2 и 2.3).

Проверяют контракт: коды ответов, состав полей, поведение без
авторизации и при неверных параметрах. Станут страховкой в ДЗ 3:
оптимизация меняет способ получения данных, ответы — нет.
"""
import pytest


async def test_login_page_lists_accounts(client):
    response = await client.get("/login")
    assert response.status_code == 200
    assert "demo" in response.text


async def test_wrong_password_rejected(client):
    response = await client.post("/login",
                                 data={"login": "demo", "password": "нет"})
    assert response.status_code == 302
    assert "error" in response.headers["location"]


async def test_pages_require_login(client):
    for path in ("/", "/specialists", "/appointments", "/summary"):
        response = await client.get(path)
        assert response.status_code == 302, path
        assert "/login" in response.headers["location"], path


async def test_book_requires_login(client):
    response = await client.post("/book", data={"slot_id": 1})
    assert response.status_code == 302


async def test_specialists_page_is_paged(demo):
    response = await demo.get("/specialists")
    assert response.status_code == 200
    assert "Показано" in response.text
    assert "страница" in response.text


async def test_specialists_filter_narrows(demo):
    everyone = await demo.get("/specialists")
    some = await demo.get("/specialists?speciality=терапевт")
    assert everyone.status_code == some.status_code == 200
    assert "из 200" in everyone.text          # рабочее наполнение
    assert "из 25" in some.text


async def test_specialist_card_shows_related(demo):
    response = await demo.get("/specialists/3")
    assert response.status_code == 200
    assert "Услуги" in response.text           # связанные услуги
    assert "Последние записи" in response.text


async def test_specialist_card_missing_redirects(demo):
    response = await demo.get("/specialists/999999")
    assert response.status_code == 302


async def test_slots_require_service(demo):
    response = await demo.get("/slots")
    assert response.status_code == 302


async def test_slots_page_shows_window(demo):
    response = await demo.get("/slots?service=2")
    assert response.status_code == 200
    assert "Свободные слоты" in response.text
    assert "найдено:" in response.text


async def test_summary_shows_kpis(demo):
    response = await demo.get("/summary")
    assert response.status_code == 200
    for label in ("всего записей", "действующих", "отменённых", "доля отмен"):
        assert label in response.text


async def test_response_time_header_present(demo):
    response = await demo.get("/specialists")
    assert "X-Response-Time-ms" in response.headers
    assert float(response.headers["X-Response-Time-ms"]) >= 0


async def test_book_unknown_slot_404(demo):
    response = await demo.post("/book", data={"slot_id": 99999999})
    assert response.status_code == 404
    assert response.json()["error"] == "slot_not_found"


async def test_cancel_unknown_appointment_404(demo):
    response = await demo.post("/cancel", data={"appointment_id": 99999999})
    assert response.status_code == 404
