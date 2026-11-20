// Вход на портал и сохранение сессии (один раз, в результаты не попадает).
import http from "k6/http";

import { BASE, LOGIN, PASSWORD } from "../config.js";

export function login() {
  // Первый запрос к /login — форма с кукой CSRF не нужна, но сессия
  // ставится только на POST: редирект 302 — нормальный результат входа.
  const response = http.post(
    `${BASE}/login`,
    { login: LOGIN, password: PASSWORD },
    { redirects: 0, tags: { operation: "login" } },
  );

  const location = response.headers.Location || response.headers.location;
  if (response.status !== 302 || !location || location.includes("error")) {
    fail(`вход не получился: статус ${response.status}, куда: ${location}`);
  }
  const cookie = response.cookies.booking_user;
  if (!cookie || cookie.length === 0) {
    fail("кука сессии не получена");
  }
  return { user: cookie[0].value };
}

export function applySession(data) {
  const jar = http.cookieJar();
  jar.set(BASE, "booking_user", data.user);
}

function fail(message) {
  throw new Error(message);
}
