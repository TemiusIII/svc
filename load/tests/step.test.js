// Нагрузочный тест ДЗ 2: два сценария, открытая модель нагрузки.
//
//   k6 run -e SCENARIO=mixed -e RATE=4 -e DURATION=30s tests/step.test.js
//   k6 run -e SCENARIO=heavy  -e RATE=2 -e DURATION=30s tests/step.test.js
//
//   SCENARIO=mixed — операции по весам профиля нагрузки (таблица 1 отчёта);
//   SCENARIO=heavy  — только самая тяжёлая операция по ДЗ 1 (/appointments).
//
// Открытая модель: constant-arrival-rate — частота в запросах в секунду,
// как в лабораторной работе № 3. Вход — один раз в setup(), в результаты
// не попадает. Порог подраздела 2.1 методички записан в thresholds:
// p95 < 500 мс и доля ошибок < 1 %.
import http from "k6/http";
import { sleep } from "k6";

// Ответы 2xx, 3xx и ожидаемые 4xx (отказы по правилам варианта:
// 404 slot_not_found, 409 slot_busy/slot_overlap) считаются ожидаемыми —
// иначе k6 помечает их failed и порог по ошибкам падает ложно.
http.setResponseCallback(http.expectedStatuses(200, 201, 302, 404, 409));

import {
  DURATION, ERROR_RATE, LIMIT_MS, RATE, SCENARIO, WEIGHTS,
} from "../config.js";
import { login, applySession } from "../flows/auth.js";
import * as steps from "../scenarios/steps.js";

export const options = {
  scenarios: {
    [SCENARIO === "heavy" ? "heavy" : "mixed"]: {
      executor: "constant-arrival-rate",
      rate: RATE,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: Math.max(20, RATE * 4),
      maxVUs: Math.max(100, RATE * 20),
    },
  },
  thresholds: {
    "http_req_duration{scenario:mixed}": [`p(95)<${LIMIT_MS}`],
    "http_req_failed{scenario:mixed}": [`rate<${ERROR_RATE}`],
    "http_req_duration{scenario:heavy}": [`p(95)<${LIMIT_MS}`],
    "http_req_failed{scenario:heavy}": [`rate<${ERROR_RATE}`],
    // Порог на каждую операцию — одинаков для обеих сценариев.
    "http_req_duration{operation:home}": [`p(95)<${LIMIT_MS}`],
    "http_req_duration{operation:specialists}": [`p(95)<${LIMIT_MS}`],
    "http_req_duration{operation:specialistsFilter}": [`p(95)<${LIMIT_MS}`],
    "http_req_duration{operation:specialistCard}": [`p(95)<${LIMIT_MS}`],
    "http_req_duration{operation:slots}": [`p(95)<${LIMIT_MS}`],
    "http_req_duration{operation:appointments}": [`p(95)<${LIMIT_MS}`],
    "http_req_duration{operation:summary}": [`p(95)<${LIMIT_MS}`],
    "http_req_duration{operation:book}": [`p(95)<${LIMIT_MS}`],
    "http_req_duration{operation:cancel}": [`p(95)<${LIMIT_MS}`],
  },
};

export function setup() {
  // Вход один раз до нагрузки; в результаты не попадает.
  return login();
}

// Выбор операции по весам профиля: весы из config.js, сумма 100.
function pickStep(iter) {
  const entries = Object.entries(WEIGHTS);
  const total = entries.reduce((s, [, w]) => s + w, 0);
  let pick = (iter * 2654435761 % total) + Math.random() * 0.9999;
  for (const [name, weight] of entries) {
    pick -= weight;
    if (pick <= 0) return name;
  }
  return entries[entries.length - 1][0];
}

const SERVICES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

export default function (data) {
  applySession(data);
  if (SCENARIO === "heavy") {
    // Самая тяжёлая операция по замерам ДЗ 1: «Мои записи»
    // (p50 168 мс, p95 304 мс на рабочем объёме).
    steps.appointments();
    return;
  }
  const iter = __ITER;
  const step = pickStep(iter);
  switch (step) {
    case "home":
      steps.home();
      break;
    case "specialists":
      steps.specialists();
      break;
    case "specialistsFilter":
      steps.specialistsFilter();
      break;
    case "specialistCard":
      steps.specialistCard(1 + (iter % 200));
      break;
    case "slots":
      steps.slots(SERVICES[iter % SERVICES.length]);
      break;
    case "appointments":
      steps.appointments();
      break;
    case "summary":
      steps.summary();
      break;
    case "book":
      steps.bookAndMaybeCancel(data, SERVICES[iter % SERVICES.length]);
      break;
    case "cancel":
      // Отмена идёт вместе с бронированием (см. bookAndMaybeCancel);
      // самостоятельный вес не выделяется, шаг — лёгкая страница.
      steps.appointments();
      break;
    default:
      steps.home();
  }
  sleep(0.05);
}
