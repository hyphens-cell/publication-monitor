# Publication Monitor 2.0

> Единая двуязычная система для планирования, согласования, мониторинга и анализа публикационной деятельности университета.

**Русский / Қазақша · Flask · PostgreSQL · Bootstrap 5 · Excel/PDF · Role-Based Access**

Publication Monitor помогает кафедрам вести годовые планы и публикации, а ответственным сотрудникам — проверять результаты, вложения и DOI-конфликты, строить аналитику и формировать отчёты. Вторая версия получила единый responsive-интерфейс, полную RU/KK-локализацию, усиленную изоляцию данных кафедр и production-настройки.

## Что умеет V2

- годовые планы кафедр с версиями, замечаниями и контролируемым workflow;
- реестр публикаций, история статусов и проверка обязательных данных;
- DOI-нормализация, поиск дублей и разрешение конфликтов;
- загрузка и проверка подтверждающих файлов;
- комментарии и персональные уведомления;
- мониторинг выполнения планов и аналитические панели;
- экспорт отчётов в Excel и PDF;
- системный аудит, справочники, диагностика и PostgreSQL backup;
- полноценный интерфейс на русском и казахском языках;
- адаптивная работа на desktop, tablet и mobile.

## Роли и зоны ответственности

| Роль | Возможности |
|---|---|
| `TECH_ADMIN` | Пользователи, кафедры, справочники, журнал действий, состояние системы и резервные копии |
| `ADMIN` | Согласование планов, проверка публикаций и вложений, мониторинг, аналитика и отчёты |
| `DEPARTMENT_HEAD` | Сотрудники, планы, публикации и файлы только собственной кафедры |

Frontend скрывает недоступные разделы, но безопасность не зависит от меню: ограничения повторно проверяются на сервере для URL, query-параметров, form data и идентификаторов объектов.

## Быстрый старт

### 1. Подготовьте окружение

Требуются Python 3.12+, PostgreSQL 14+ и `pg_dump` для резервных копий.

```powershell
git clone https://github.com/hyphens-cell/publication-monitor.git
cd publication-monitor
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

В `.env` задайте случайный `SECRET_KEY` и параметры отдельной PostgreSQL-базы. Файл `.env` исключён из Git.

### 2. Подготовьте базу данных

```powershell
.\.venv\Scripts\python.exe -m flask --app run.py db upgrade
.\.venv\Scripts\python.exe -m flask --app run.py seed-reference-values
```

### 3. Запустите приложение

```powershell
.\.venv\Scripts\python.exe run.py
```

Для локальной разработки используйте `APP_ENV=development` и `SESSION_COOKIE_SECURE=false`. В production приложение требует HTTPS, надёжный `SECRET_KEY` и запуск через WSGI-сервер.

## Резервное копирование

Backup создаётся настоящим `pg_dump` в custom-формате. Пароль берётся из `DATABASE_URL` или `DB_PASSWORD` и передаётся дочернему процессу только через `PGPASSWORD` — он не попадает в аргументы командной строки и интерфейс.

Перед восстановлением остановите запись данных, сохраните текущую БД и каталог `instance/uploads`, затем выполните проверенный `pg_restore` под администратором инфраструктуры. Небезопасный web-endpoint автоматического restore намеренно отсутствует.

## Проверки качества

```powershell
.\.venv\Scripts\python.exe -m compileall app tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests run.py migrations
git diff --check
```

Тесты используют изолированную конфигурацию и SQLite in-memory, не подключаясь к production-базе.

## Структура проекта

```text
app/
├── admin/          # системное администрирование
├── domain/         # доменные правила и статусы
├── services/       # workflow, exports, storage, validation
├── static/         # дизайн-система и JavaScript
├── templates/      # единые RU/KK Jinja-шаблоны
└── *.py            # Flask blueprints и application factory
migrations/         # Alembic migrations
tests/              # security, workflows, i18n, performance
docs/               # аудит, трассировка требований и руководство
```

## Документация

- [Пользовательский гид V2](docs/GUIDE.md)
- [Аудит реализации](docs/audit.md)
- [Сопоставление с требованиями](docs/requirements-traceability.md)
- [Исходное техническое задание](docs/specification-source.txt)

## Безопасность

Пароли хранятся только как BCrypt-хеши. Изменяющие запросы защищены CSRF. Загрузка файлов проверяет расширение, размер и безопасное имя; скачивание и удаление проходят object-level authorization. Production-профиль запрещает короткий `SECRET_KEY`, небезопасные cookies и debug-режим.

---

**Publication Monitor 2.0** — production-oriented Flask/Jinja-система без SPA-зависимости, с серверным RBAC и единой RU/KK дизайн-системой.
