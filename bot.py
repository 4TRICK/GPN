import asyncio
import os
import logging
import matplotlib.pyplot as plt
import pandas as pd
import asyncpg
import requests
import json
from jinja2 import Template
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Настройки (теперь из .env)
TOKEN = os.getenv("BOT_TOKEN")
YANDEX_GPT_API_KEY = os.getenv("YANDEX_GPT_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
DATABASE_URL = os.getenv("DATABASE_URL")

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Подключение к БД
async def get_db_connection():
    return await asyncpg.connect(DATABASE_URL)

# Клавиатура с вариантами ответа
def get_keyboard(options):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=o)] for o in options], resize_keyboard=True)

# Начало работы
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Привет! Давай начнем опрос.", reply_markup=get_keyboard(["Начать"]))

# Вопросы анкеты
QUESTIONS = [
    ("Укажите ваше подразделение", "text"),
    ("ФИО", "text"),
    ("Оцените практику в целом (1-10)", "rating"),
    ("Оправдала ли практика ваши ожидания?", ["Да", "Нет", "Частично"]),
    ("Оцените уровень организации практики (1-10)", "rating"),
    ("Была ли у вас достаточная поддержка от наставников? (1-10)", "rating"),
    ("Как вы оцениваете полезность полученных заданий? (1-10)", "rating"),
    ("Достаточно ли было информации для выполнения заданий?",
     ["Да", "Нет, не хватало разъяснений", "Нет, было слишком сложно"]),
    ("Рекомендовали бы вы эту практику другим студентам?", ["Да", "Нет"]),
    ("Что вам больше всего понравилось в практике?", "comment"),
    ("Что можно улучшить?", "comment"),
    ("Хотите добавить что-то еще о своем опыте?", "comment")
]

# Хранилище состояний
user_data = {}

# Обработка ответов
@dp.message()
async def handle_response(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {"step": 0, "responses": {}}

    step = user_data[user_id]["step"]

    # Сохранение ответа
    question, qtype = QUESTIONS[step]
    user_data[user_id]["responses"][question] = message.text

    user_data[user_id]["step"] += 1

    # Если есть еще вопросы, задаем следующий
    if user_data[user_id]["step"] < len(QUESTIONS):
        next_question, next_type = QUESTIONS[user_data[user_id]["step"]]

        if isinstance(next_type, list):  # Варианты ответа
            await message.answer(next_question, reply_markup=get_keyboard(next_type))
        else:
            await message.answer(next_question)

    # Если вопросы закончились, сохраняем в БД
    else:
        await save_to_db(user_id, user_data[user_id]["responses"])
        await message.answer("Спасибо за участие в опросе!", reply_markup=types.ReplyKeyboardRemove())
        del user_data[user_id]  # Очищаем данные пользователя

# Сохранение в PostgreSQL
async def save_to_db(user_id, responses):
    conn = await get_db_connection()

    # Сохранение студента
    student_id = await conn.fetchval(
        "INSERT INTO students (full_name, department) VALUES ($1, $2) RETURNING id",
        responses["ФИО"], responses["Укажите ваше подразделение"]
    )

    # Статические ответы
    for q, a in responses.items():
        if q in [q[0] for q in QUESTIONS if q[1] not in ["comment"]]:
            await conn.execute("INSERT INTO static_responses (student_id, question, answer) VALUES ($1, $2, $3)",
                               student_id, q, a)

    # Динамические ответы
    for q, a in responses.items():
        if q in [q[0] for q in QUESTIONS if q[1] == "comment"] :
            processed_comment = await process_with_yandex_gpt(a)
            await conn.execute(
                "INSERT INTO dynamic_responses (student_id, question, comment, processed_comment) VALUES ($1, $2, $3, $4)",
                student_id, q, a, processed_comment
            )

    await conn.close()

# Запрос в Yandex GPT
async def process_with_yandex_gpt(comment):
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Authorization": f"Api-Key {YANDEX_GPT_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "yandexgpt",
        "folderId": YANDEX_FOLDER_ID,
        "prompt": f"Обработай комментарий и выдели ключевые моменты:\n{comment}",
        "maxTokens": 2000
    }
    response = requests.post(url, headers=headers, json=payload)
    result = response.json()
    return result.get("result", "Ошибка обработки")

# Генерация диаграмм
async def generate_chart():
    conn = await get_db_connection()
    df = pd.DataFrame(await conn.fetch("SELECT question, answer FROM static_responses"))
    await conn.close()

    if df.empty:
        return None

    df_counts = df.groupby(["question", "answer"]).size().reset_index(name="count")

    for question in df_counts["question"].unique():
        q_data = df_counts[df_counts["question"] == question]
        plt.figure(figsize=(8, 6))
        plt.pie(q_data["count"], labels=q_data["answer"], autopct="%1.1f%%")
        plt.title(question)
        plt.savefig(f"survey_bot/charts/{question}.png")
        plt.close()

# Кластеризация вопросов (например, оценок)
async def cluster_ratings():
    conn = await get_db_connection()
    ratings = await conn.fetch("SELECT question, answer FROM static_responses WHERE question LIKE '%оцените%'")
    await conn.close()

    if not ratings:
        return

    ratings_df = pd.DataFrame(ratings)
    ratings_df["answer"] = ratings_df["answer"].astype(float)

    # Нормализация данных
    scaler = StandardScaler()
    ratings_df["normalized"] = scaler.fit_transform(ratings_df[["answer"]])

    # Кластеризация
    kmeans = KMeans(n_clusters=3, random_state=42)
    ratings_df["cluster"] = kmeans.fit_predict(ratings_df[["normalized"]])

    # Сохраняем результаты кластеризации в базу данных
    conn = await get_db_connection()
    for _, row in ratings_df.iterrows():
        await conn.execute(
            "UPDATE static_responses SET cluster = $1 WHERE question = $2 AND answer = $3",
            row["cluster"], row["question"], row["answer"]
        )
    await conn.close()

# Генерация HTML отчета
async def generate_html_report():
    conn = await get_db_connection()

    # Кластеризация
    clusters = await conn.fetch("SELECT question, answer, cluster FROM static_responses WHERE cluster IS NOT NULL")
    # Обработанные комментарии
    comments = await conn.fetch("SELECT question, comment, processed_comment FROM dynamic_responses")

    await conn.close()

    # Генерация HTML с использованием шаблона
    with open("survey_report_template.html", "r") as f:
        template = Template(f.read())

    html_report = template.render(clusters=clusters, comments=comments)

    # Сохраняем отчет
    with open("survey_report.html", "w") as f:
        f.write(html_report)

# Запуск бота
async def main():
    os.makedirs("survey_bot/charts", exist_ok=True)
    await cluster_ratings()  # Кластеризация оценок
    await generate_chart()   # Генерация диаграмм
    await generate_html_report()  # Генерация HTML отчета
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
