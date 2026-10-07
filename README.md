# Платформа охраны труда и обучения персонала

## Запуск на своём ПК (Windows/macOS/Linux)

1. Установите Docker Desktop.
2. Скопируйте `.env.example` в `.env` и поменяйте пароли и `SECRET_KEY`.
3. В папке проекта выполните:
   ```
   docker compose up --build
   ```
   БД создастся сама, миграции применятся автоматически.
4. Создайте первого суперадминистратора:
   ```
   docker compose exec backend python -m app.scripts.create_superadmin
   ```
5. Проверка: http://localhost:8000/api/v1/health и документация API http://localhost:8000/docs
6. Тесты (включая проверку изоляции организаций):
   ```
   docker compose exec backend pytest -q
   ```

## Переезд на хостинг
Всё настраивается через `.env`: адрес БД (`DATABASE_URL`, `MIGRATION_DATABASE_URL`), секрет, каталог файлов.
Подойдёт любой VPS с Docker или управляемый PostgreSQL 16+.
Важно: рабочее подключение должно идти под ролью `ohs_app` (не суперпользователь и не владелец таблиц),
иначе защита изоляции организаций (RLS) не будет действовать.
