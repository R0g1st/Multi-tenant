#!/bin/sh
# Создаёт рабочую роль приложения. Она не владелец таблиц и не обходит RLS.
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
CREATE ROLE ohs_app LOGIN PASSWORD '${OHS_APP_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ohs_app;
GRANT USAGE ON SCHEMA public TO ohs_app;
SQL
