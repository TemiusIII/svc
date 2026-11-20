// Общая конфигурация тестов k6 (ДЗ 2).
// Значения меняются флагами -e без правки исходников:
//   k6 run -e SCENARIO=mixed -e RATE=8 -e DURATION=30s tests/steps.test.js

export const BASE = __ENV.BASE || "http://127.0.0.1:8080";
export const LOGIN = __ENV.LOGIN || "demo";
export const PASSWORD = __ENV.PASSWORD || "demo";

// Открытая модель нагрузки: постоянная частота запросов в секунду.
export const RATE = Number(__ENV.RATE || 4);
export const DURATION = __ENV.DURATION || "30s";

// Сценарий: mixed — операции по весам профиля нагрузки;
// heavy — только самая тяжёлая операция (/appointments).
export const SCENARIO = __ENV.SCENARIO || "mixed";

// Порог для всех один (методичка ДЗ 2, п. 2.1):
// p95 < 500 мс и доля ошибок < 1 %.
export const LIMIT_MS = Number(__ENV.LIMIT_MS || 500);
export const ERROR_RATE = Number(__ENV.ERROR_RATE || 0.01);

// Смешанный профиль (весы — таблица 1 отчёта ДЗ 2, сумма 100).
export const WEIGHTS = {
  home: 12,
  specialists: 18,
  specialistsFilter: 8,
  specialistCard: 12,
  slots: 22,
  appointments: 15,
  summary: 2,
  book: 9,
  cancel: 2,
};
