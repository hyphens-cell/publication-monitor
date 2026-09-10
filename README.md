# Publication Monitor

Веб-система для планирования, учёта, проверки и анализа публикационной активности кафедр.

## Требования

- Python 3.12+
- PostgreSQL 14+ и утилита `pg_dump` на сервере, если используются резервные копии

## Настройка

Создайте `.env` по образцу `.env.example`, задав уникальный `SECRET_KEY` и параметры PostgreSQL. `SECRET_KEY` обязателен: приложение не запускается с небезопасным встроенным значением.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app run.py db upgrade
.\.venv\Scripts\python.exe -m flask --app run.py seed-reference-values
```

Для локальной разработки установите `SESSION_COOKIE_SECURE=false`. В production используйте HTTPS, оставьте значение `true` и запускайте приложение через WSGI-сервер, например Gunicorn.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m compileall app tests
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

## Роли

- `TECH_ADMIN` — учётные записи, кафедры, справочники, журнал событий, состояние системы и резервные копии.
- `ADMIN` — согласование планов, проверка публикаций и вложений, мониторинг, аналитика и отчёты.
- `DEPARTMENT_HEAD` — данные только своей кафедры: сотрудники, планы, публикации и вложения.

Авторизация основана на Flask-Login и серверно проверяемой записи пользователя; пароли хранятся только в виде BCrypt-хешей. Все изменяющие данные формы защищены CSRF-токеном.
