// Шаги сценария: по одной операции контракта на функцию.
// Каждая помечена тегом operation — по тегам k6 считает медиану и p95
// на операцию, а не на весь поток.
import http from "k6/http";

import { BASE } from "../config.js";
import { checkBook, checkCancel, checkPage } from "../validators/page.js";

export function home() {
  const r = http.get(`${BASE}/`, {
    redirects: 0, tags: { operation: "home" }, timeout: "30s",
  });
  checkPage(r, "услуги");
}

export function specialists() {
  const r = http.get(`${BASE}/specialists`, {
    redirects: 0, tags: { operation: "specialists" }, timeout: "30s",
  });
  checkPage(r, "специалисты");
}

export function specialistsFilter() {
  const r = http.get(
    `${BASE}/specialists?speciality=%D1%82%D0%B5%D1%80%D0%B0%D0%BF%D0%B5%D0%B2%D1%82`,
    { redirects: 0, tags: { operation: "specialistsFilter" }, timeout: "30s" },
  );
  checkPage(r, "специалисты с фильтром");
}

export function specialistCard(id) {
  const r = http.get(`${BASE}/specialists/${id}`, {
    redirects: 0, tags: { operation: "specialistCard" }, timeout: "30s",
  });
  checkPage(r, "карточка специалиста");
}

export function slots(service) {
  const r = http.get(`${BASE}/slots?service=${service}`, {
    redirects: 0, tags: { operation: "slots" }, timeout: "30s",
  });
  checkPage(r, "свободные слоты");
}

export function appointments() {
  const r = http.get(`${BASE}/appointments`, {
    redirects: 0, tags: { operation: "appointments" }, timeout: "30s",
  });
  checkPage(r, "мои записи");
}

export function summary() {
  const r = http.get(`${BASE}/summary`, {
    redirects: 0, tags: { operation: "summary" }, timeout: "30s",
  });
  checkPage(r, "сводка");
}

// Бронирование: свободный слот выбирается из свежего списка слотов услуги.
export function bookAndMaybeCancel(data, service) {
  const list = http.get(`${BASE}/slots?service=${service}`, {
    redirects: 0, tags: { operation: "bookSlotsLookup" }, timeout: "30s",
  });
  const found = list.body.match(/name="slot_id" value="(\d+)"/);
  if (!found) {
    check(list, { "слоты не найдены": () => false });
    return null;
  }
  const slotId = found[1];
  const r = http.post(`${BASE}/book`,
    { slot_id: slotId, client_name: "Нагрузочный Клиент" },
    { redirects: 0, tags: { operation: "book" }, timeout: "30s" });
  const booked = checkBook(r);
  if (!booked || r.status !== 201) return null;
  const apptId = r.json("appointment_id");
  // Каждая третья запись отменяется: отмена — часть профиля.
  if (Math.random() < 0.33) {
    const c = http.post(`${BASE}/cancel`,
      { appointment_id: apptId },
      { redirects: 0, tags: { operation: "cancel" }, timeout: "30s" });
    checkCancel(c);
  }
  return apptId;
}
