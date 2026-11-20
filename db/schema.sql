-- Схема базы: специалист, услуга, слот, запись (вариант 3).
-- Индексы — только первичные и внешние ключи (ограничение ДЗ 1, п. 1.4).
CREATE TABLE IF NOT EXISTS specialists (
    id         serial PRIMARY KEY,
    full_name  text NOT NULL,
    speciality text NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
    id           serial PRIMARY KEY,
    name         text NOT NULL,
    duration_min integer NOT NULL CHECK (duration_min > 0)
);

-- Оказываемые услуги: многие-ко-многим.
CREATE TABLE IF NOT EXISTS specialist_services (
    specialist_id integer NOT NULL REFERENCES specialists(id),
    service_id    integer NOT NULL REFERENCES services(id),
    PRIMARY KEY (specialist_id, service_id)
);

CREATE TABLE IF NOT EXISTS slots (
    id            serial PRIMARY KEY,
    specialist_id integer NOT NULL REFERENCES specialists(id),
    service_id    integer NOT NULL REFERENCES services(id),
    starts_at     timestamptz NOT NULL,
    ends_at       timestamptz NOT NULL,
    status        text NOT NULL DEFAULT 'free' CHECK (status IN ('free', 'booked'))
);

CREATE TABLE IF NOT EXISTS appointments (
    id           serial PRIMARY KEY,
    client_login text NOT NULL,
    client_name  text,
    slot_id      integer NOT NULL REFERENCES slots(id),
    status       text NOT NULL DEFAULT 'booked'
                 CHECK (status IN ('booked', 'cancelled')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    cancelled_at timestamptz
);

CREATE TABLE IF NOT EXISTS users (
    id         serial PRIMARY KEY,
    login      text NOT NULL UNIQUE,
    password   text NOT NULL,
    full_name  text NOT NULL
);

-- Пользователь демо-учётка для замеров (пароль учебный, в .env.example
-- указывается changeme).
INSERT INTO users (login, password, full_name) VALUES
    ('demo', 'demo', 'Демо Пользователь'),
    ('manager', 'manager', 'Диспетчер Расписания')
ON CONFLICT (login) DO NOTHING;
