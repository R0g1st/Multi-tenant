"""Зашифрованный список паролей пользователей: просмотр, изменение, загрузка в БД.

Запуск:  docker compose exec backend python -m app.scripts.credentials <команда>

Команды:
  show [--phone +7999...]       показать номера и пароли (все или один)
  set --phone +7999... [--name "Иванов И.И."]
                                добавить/изменить пароль (вводится скрыто)
  remove --phone +7999...       убрать номер из списка
  import файл.csv               загрузить список из CSV (телефон;пароль[;ФИО]);
                                после импорта исходный CSV удалите — он не зашифрован
  sync                          записать пароли из файла в БД (то же делается при запуске сервера)
  new-passphrase                сменить мастер-пароль файла

Мастер-пароль спрашивается при каждом запуске. Чтобы не вводить его, а также чтобы
сервер сам загружал пароли при старте, задайте CREDENTIALS_PASSPHRASE в .env.
"""
import argparse
import csv
import getpass
import sys

from app.core import credentials_vault
from app.core.config import get_settings
from app.core.security import normalize_phone
from app.services.credentials_sync import sync, vault_path


def _passphrase(confirm: bool = False) -> str:
    if not confirm and get_settings().credentials_passphrase:
        return get_settings().credentials_passphrase
    p = getpass.getpass("Мастер-пароль файла: ")
    if confirm and p != getpass.getpass("Повторите мастер-пароль: "):
        raise SystemExit("Мастер-пароли не совпадают. Ничего не изменено.")
    if len(p) < 12:
        raise SystemExit("Мастер-пароль должен быть не короче 12 символов.")
    return p


def _open() -> tuple[str, dict[str, dict]]:
    path = vault_path()
    passphrase = _passphrase(confirm=not path.exists() and not get_settings().credentials_passphrase)
    try:
        return passphrase, credentials_vault.load(path, passphrase)
    except credentials_vault.VaultError as exc:
        raise SystemExit(str(exc))


def _phone(raw: str) -> str:
    try:
        return normalize_phone(raw)
    except ValueError as exc:
        raise SystemExit(f"{raw}: {exc}")


def cmd_show(args) -> None:
    _, entries = _open()
    if args.phone:
        phone = _phone(args.phone)
        entries = {phone: entries[phone]} if phone in entries else {}
    if not entries:
        print("Записей нет.")
        return
    print(f"{'Телефон':<16}  {'Пароль':<24}  ФИО")
    for phone, e in sorted(entries.items(), key=lambda kv: kv[1].get("name") or kv[0]):
        print(f"{phone:<16}  {e['password']:<24}  {e.get('name') or ''}")
    print(f"Всего: {len(entries)}")


def cmd_set(args) -> None:
    passphrase, entries = _open()
    phone = _phone(args.phone)
    password = getpass.getpass(f"Пароль для {phone} (ввод не отображается): ")
    if not password or password != getpass.getpass("Повторите пароль: "):
        raise SystemExit("Пароли пустые или не совпадают. Ничего не изменено.")
    name = args.name if args.name is not None else entries.get(phone, {}).get("name")
    entries[phone] = {"password": password, "name": name}
    credentials_vault.save(vault_path(), passphrase, entries)
    print(f"Сохранено. Чтобы пароль заработал на сайте, выполните команду sync или перезапустите сервер.")


def cmd_remove(args) -> None:
    passphrase, entries = _open()
    phone = _phone(args.phone)
    if entries.pop(phone, None) is None:
        raise SystemExit("Такого номера в списке нет.")
    credentials_vault.save(vault_path(), passphrase, entries)
    print("Удалено из списка. Текущий пароль пользователя в БД не меняется.")


def cmd_import(args) -> None:
    passphrase, entries = _open()
    added = 0
    with open(args.file, newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.reader(f, delimiter=";"), start=1):
            if not row or not row[0].strip():
                continue
            try:
                phone = normalize_phone(row[0])
            except ValueError:
                print(f"Строка {n}: пропущена (не номер телефона: {row[0]!r})")
                continue
            if len(row) < 2 or not row[1]:
                print(f"Строка {n}: пропущена (нет пароля)")
                continue
            name = row[2].strip() if len(row) > 2 and row[2].strip() else entries.get(phone, {}).get("name")
            entries[phone] = {"password": row[1], "name": name}
            added += 1
    credentials_vault.save(vault_path(), passphrase, entries)
    print(f"Загружено записей: {added}. Всего в списке: {len(entries)}.")
    print(f"ВАЖНО: удалите исходный файл {args.file} — он не зашифрован.")


def cmd_sync(args) -> None:
    try:
        changed, missing = sync(_open()[0])
    except credentials_vault.VaultError as exc:
        raise SystemExit(str(exc))
    print(f"Обновлено паролей в БД: {changed}.")
    if missing:
        print("Нет пользователей на сайте с номерами: " + ", ".join(missing))


def cmd_new_passphrase(args) -> None:
    _, entries = _open()
    print("Задайте новый мастер-пароль.")
    new = getpass.getpass("Новый мастер-пароль: ")
    if new != getpass.getpass("Повторите: ") or len(new) < 12:
        raise SystemExit("Не совпадает или короче 12 символов. Ничего не изменено.")
    credentials_vault.save(vault_path(), new, entries)
    print("Готово. Не забудьте обновить CREDENTIALS_PASSPHRASE в .env, если он задан.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Зашифрованный список паролей пользователей")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show"); p.add_argument("--phone"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("set"); p.add_argument("--phone", required=True); p.add_argument("--name")
    p.set_defaults(fn=cmd_set)
    p = sub.add_parser("remove"); p.add_argument("--phone", required=True); p.set_defaults(fn=cmd_remove)
    p = sub.add_parser("import"); p.add_argument("file"); p.set_defaults(fn=cmd_import)
    sub.add_parser("sync").set_defaults(fn=cmd_sync)
    sub.add_parser("new-passphrase").set_defaults(fn=cmd_new_passphrase)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
