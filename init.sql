-- init.sql

-- Создание таблицы студентов
CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    department TEXT NOT NULL
);

-- Создание таблицы с ответами на статические вопросы
CREATE TABLE IF NOT EXISTS static_responses (
    id SERIAL PRIMARY KEY,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Создание таблицы с ответами на динамические вопросы
CREATE TABLE IF NOT EXISTS dynamic_responses (
    id SERIAL PRIMARY KEY,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    comment TEXT NOT NULL,
    processed_comment TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Создание таблицы организаторов
CREATE TABLE IF NOT EXISTS organizers (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL
);

-- Индексы для ускорения запросов
CREATE INDEX IF NOT EXISTS idx_student_id_static_responses ON static_responses(student_id);
CREATE INDEX IF NOT EXISTS idx_student_id_dynamic_responses ON dynamic_responses(student_id);
