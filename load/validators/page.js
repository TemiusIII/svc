// Проверки ответов: страница, а не форма входа; ожидаемые отказы.
import { check } from "k6";

// Успешная страница: 200 и не редирект на /login.
export function checkPage(response, name) {
  return check(response, {
    [`${name}: статус 200`]: (r) => r.status === 200,
    [`${name}: не редирект на вход`]: (r) =>
      !r.headers.Location || !r.headers.Location.includes("/login"),
  });
}

// Бронирование: 201 — успех; 409 slot_busy/slot_overlap — ожидаемое
// поведение по правилам варианта (не ошибка теста).
export function checkBook(response) {
  return check(response, {
    "запись создана": (r) => r.status === 201,
    "отказ по правилу варианта": (r) =>
      r.status === 409 &&
      ["slot_busy", "slot_overlap"].includes(
        (r.json("error") || "").toString(),
      ),
  });
}

// Отмена: 200 — ок; 404/409 — ожидаемые отказы (нет записи, уже отменена).
export function checkCancel(response) {
  return check(response, {
    "отмена выполнена": (r) => r.status === 200,
    "отказ по правилу варианта": (r) => r.status === 404 || r.status === 409,
  });
}
