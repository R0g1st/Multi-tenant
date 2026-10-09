"""Библиотека учебных материалов: папки любой вложенности, документы и видео.

Два вида владельцев: общая библиотека учебного центра (org_id = None, её видят все заказчики)
и материалы заказчика (org_id = организация, видит только он и учебный центр). Изменять общее
может только учебный центр, своё — заказчик; это же обеспечивает RLS в базе.

Файлы лежат в storage/library под случайными именами; отдаются по подписанной ссылке,
чтобы видео можно было проигрывать и перематывать прямо в браузере.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.deps import Actor, get_db, require_manage, require_roles
from app.core.tokens import create_file_token, decode_file_token
from app.models import Course, CourseMaterial, LibraryFolder, LibraryItem
from app.schemas import FileLinkOut, FolderIn, FolderOut, FolderUpdate, LibraryItemOut, LibraryItemUpdate
from app.services.audit import client_ip, log

router = APIRouter(prefix="/library", tags=["library"])
USERS = require_roles("superadmin", "center_admin", "org_admin")

DOCUMENTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
             ".rtf", ".txt", ".jpg", ".jpeg", ".png"}
VIDEOS = {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}
CHUNK = 1024 * 1024


def library_dir() -> Path:
    return Path(get_settings().storage_dir) / "library"


def owner_param(actor: Actor, owner: str | None) -> UUID | None:
    """owner из запроса: «shared» (или пусто) — общая библиотека, иначе id организации.
    Заказчик может смотреть только общую и свою."""
    if not owner or owner == "shared":
        return None
    try:
        org = UUID(owner)
    except ValueError:
        raise HTTPException(422, "Неверный параметр owner")
    if not actor.is_center_wide and org != actor.org_id:
        raise HTTPException(403, "Это материалы другой организации")
    return org


def _new_owner(actor: Actor, parent: LibraryFolder | None, requested: UUID | None) -> UUID | None:
    """Владелец нового объекта: как у папки, куда кладём; в корне — общая библиотека
    для учебного центра (или выбранный заказчик) и всегда своя — для заказчика."""
    if parent is not None:
        owner = parent.org_id
    else:
        owner = requested if actor.is_center_wide else actor.org_id
    require_manage(actor, owner)
    return owner


def _folder(db, folder_id: UUID) -> LibraryFolder:
    f = db.get(LibraryFolder, folder_id)  # RLS: чужие папки заказчику не видны
    if f is None or f.deleted_at is not None:
        raise HTTPException(404, "Папка не найдена")
    return f


def _item(db, item_id: UUID) -> LibraryItem:
    i = db.get(LibraryItem, item_id)
    if i is None or i.deleted_at is not None:
        raise HTTPException(404, "Материал не найден")
    return i


def _path(db, folder_id: UUID | None) -> str:
    names = []
    while folder_id:
        f = db.get(LibraryFolder, folder_id)
        names.append(f.name)
        folder_id = f.parent_id
    return " / ".join(reversed(names)) or "Корень библиотеки"


def _owner_cond(model, owner: UUID | None):
    return model.org_id == owner if owner else model.org_id.is_(None)


# ---------- Папки ----------
@router.get("/folders", response_model=list[FolderOut])
def list_folders(owner: str | None = None, actor: Actor = Depends(USERS), db=Depends(get_db)):
    """Папки одной библиотеки плоским списком (дерево строит интерфейс) с числом материалов."""
    org = owner_param(actor, owner)
    counts = dict(db.execute(select(LibraryItem.folder_id, func.count())
                             .where(LibraryItem.deleted_at.is_(None), _owner_cond(LibraryItem, org))
                             .group_by(LibraryItem.folder_id)).all())
    folders = db.scalars(select(LibraryFolder)
                         .where(LibraryFolder.deleted_at.is_(None), _owner_cond(LibraryFolder, org))
                         .order_by(func.lower(LibraryFolder.name))).all()
    return [FolderOut(id=f.id, org_id=f.org_id, parent_id=f.parent_id, name=f.name, items=counts.get(f.id, 0))
            for f in folders]


@router.post("/folders", response_model=FolderOut, status_code=201)
def create_folder(body: FolderIn, request: Request, actor: Actor = Depends(USERS), db=Depends(get_db)):
    parent = _folder(db, body.parent_id) if body.parent_id else None
    owner = _new_owner(actor, parent, body.org_id)
    f = LibraryFolder(name=body.name.strip(), parent_id=body.parent_id, org_id=owner)
    db.add(f)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "Папка с таким названием здесь уже есть")
    log(db, actor=actor, org_id=owner, action="library.folder_create", entity_type="library_folder",
        entity_id=f.id, ip=client_ip(request), description=f"{actor.full_name} создал папку «{_path(db, f.id)}»")
    return FolderOut(id=f.id, org_id=f.org_id, parent_id=f.parent_id, name=f.name, items=0)


@router.patch("/folders/{folder_id}", response_model=FolderOut)
def update_folder(folder_id: UUID, body: FolderUpdate, request: Request,
                  actor: Actor = Depends(USERS), db=Depends(get_db)):
    f = _folder(db, folder_id)
    require_manage(actor, f.org_id)
    old_path = _path(db, f.id)
    if body.name is not None:
        f.name = body.name.strip()
    if "parent_id" in body.model_fields_set and body.parent_id != f.parent_id:
        # нельзя переложить папку внутрь самой себя, своей подпапки или в чужую библиотеку
        if body.parent_id and _folder(db, body.parent_id).org_id != f.org_id:
            raise HTTPException(422, "Папку можно перенести только внутри той же библиотеки")
        cur = body.parent_id
        while cur:
            if cur == f.id:
                raise HTTPException(422, "Нельзя переместить папку внутрь неё самой")
            cur = _folder(db, cur).parent_id
        f.parent_id = body.parent_id
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "Папка с таким названием здесь уже есть")
    new_path = _path(db, f.id)
    if new_path != old_path:
        log(db, actor=actor, org_id=f.org_id, action="library.folder_update", entity_type="library_folder",
            entity_id=f.id, ip=client_ip(request), details={"path": [old_path, new_path]},
            description=f"{actor.full_name} изменил папку «{old_path}» → «{new_path}»")
    items = db.scalar(select(func.count()).select_from(LibraryItem)
                      .where(LibraryItem.folder_id == f.id, LibraryItem.deleted_at.is_(None)))
    return FolderOut(id=f.id, org_id=f.org_id, parent_id=f.parent_id, name=f.name, items=items)


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: UUID, request: Request, actor: Actor = Depends(USERS), db=Depends(get_db)):
    """Удалить можно только пустую папку — чтобы случайно не потерять материалы."""
    f = _folder(db, folder_id)
    require_manage(actor, f.org_id)
    busy = db.scalar(select(func.count()).select_from(LibraryFolder)
                     .where(LibraryFolder.parent_id == f.id, LibraryFolder.deleted_at.is_(None))) or \
        db.scalar(select(func.count()).select_from(LibraryItem)
                  .where(LibraryItem.folder_id == f.id, LibraryItem.deleted_at.is_(None)))
    if busy:
        raise HTTPException(409, "Папка не пуста: сначала перенесите или удалите её содержимое")
    path = _path(db, f.id)
    f.deleted_at = datetime.now(timezone.utc)
    log(db, actor=actor, org_id=f.org_id, action="library.folder_delete", entity_type="library_folder",
        entity_id=f.id, ip=client_ip(request), description=f"{actor.full_name} удалил папку «{path}»")


# ---------- Материалы ----------
@router.get("/items", response_model=list[LibraryItemOut])
def list_items(owner: str | None = None, folder_id: UUID | None = None,
               q: str | None = Query(None, max_length=200),
               actor: Actor = Depends(USERS), db=Depends(get_db)):
    """С q — поиск по названию во всей библиотеке владельца, иначе — содержимое папки
    (без folder_id — корень библиотеки владельца)."""
    conds = [LibraryItem.deleted_at.is_(None)]
    if folder_id and not q:
        conds.append(LibraryItem.folder_id == _folder(db, folder_id).id)
    else:
        conds.append(_owner_cond(LibraryItem, owner_param(actor, owner)))
        if q:
            conds.append(LibraryItem.title.ilike(f"%{q}%", autoescape=True))
        else:
            conds.append(LibraryItem.folder_id.is_(None))
    return db.scalars(select(LibraryItem).where(*conds).order_by(func.lower(LibraryItem.title))).all()


@router.post("/items", response_model=LibraryItemOut, status_code=201)
def upload_item(request: Request, file: UploadFile = File(...),
                folder_id: UUID | None = Form(None),
                org_id: UUID | None = Form(None),
                title: str | None = Form(None, max_length=300),
                description: str | None = Form(None, max_length=5000),
                actor: Actor = Depends(USERS), db=Depends(get_db)):
    folder = _folder(db, folder_id) if folder_id else None
    owner = _new_owner(actor, folder, org_id)
    name = Path(file.filename or "").name
    ext = Path(name).suffix.lower()
    if ext in VIDEOS:
        kind = "video"
    elif ext in DOCUMENTS:
        kind = "document"
    else:
        raise HTTPException(422, "Такой тип файла не поддерживается. Документы: "
                            + ", ".join(sorted(DOCUMENTS)) + ". Видео: " + ", ".join(sorted(VIDEOS)))

    limit = get_settings().library_max_upload_mb * 1024 * 1024
    stored = uuid.uuid4().hex + ext
    target = library_dir() / stored
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Файл больше {get_settings().library_max_upload_mb} МБ")
                out.write(chunk)
        if size == 0:
            raise HTTPException(422, "Файл пустой")
        item = LibraryItem(folder_id=folder_id, org_id=owner, title=(title or "").strip() or Path(name).stem,
                           description=(description or "").strip() or None, kind=kind, file_name=name,
                           stored_name=stored, mime=file.content_type or "application/octet-stream",
                           size=size, uploaded_by=actor.id)
        db.add(item)
        db.flush()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    log(db, actor=actor, org_id=owner, action="library.item_upload", entity_type="library_item",
        entity_id=item.id, ip=client_ip(request), details={"file": name, "size": size},
        description=f"{actor.full_name} загрузил «{item.title}» в «{_path(db, folder_id)}»")
    return item


@router.patch("/items/{item_id}", response_model=LibraryItemOut)
def update_item(item_id: UUID, body: LibraryItemUpdate, request: Request,
                actor: Actor = Depends(USERS), db=Depends(get_db)):
    item = _item(db, item_id)
    require_manage(actor, item.org_id)
    changes = {}
    if body.title is not None and body.title.strip() != item.title:
        changes["title"] = [item.title, body.title.strip()]
        item.title = body.title.strip()
    if "description" in body.model_fields_set:
        item.description = (body.description or "").strip() or None
    if "folder_id" in body.model_fields_set and body.folder_id != item.folder_id:
        if body.folder_id and _folder(db, body.folder_id).org_id != item.org_id:
            raise HTTPException(422, "Материал можно перенести только внутри той же библиотеки")
        changes["folder"] = [_path(db, item.folder_id), _path(db, body.folder_id)]
        item.folder_id = body.folder_id
    item.updated_at = datetime.now(timezone.utc)
    if changes:
        log(db, actor=actor, org_id=item.org_id, action="library.item_update", entity_type="library_item",
            entity_id=item.id, ip=client_ip(request), details=changes,
            description=f"{actor.full_name} изменил материал «{item.title}»")
    return item


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: UUID, request: Request, actor: Actor = Depends(USERS), db=Depends(get_db)):
    item = _item(db, item_id)
    require_manage(actor, item.org_id)
    # курсы ищем служебной сессией: общий материал может стоять в курсах любых заказчиков
    with tenant_session(bypass=True) as sdb:
        used = sdb.scalars(select(Course.title).join(CourseMaterial, CourseMaterial.course_id == Course.id)
                           .where(CourseMaterial.item_id == item.id, Course.deleted_at.is_(None))).all()
    if used:
        raise HTTPException(409, "Материал входит в курсы: " + ", ".join(f"«{t}»" for t in used)
                            + ". Сначала уберите его из курсов.")
    item.deleted_at = datetime.now(timezone.utc)
    log(db, actor=actor, org_id=item.org_id, action="library.item_delete", entity_type="library_item",
        entity_id=item.id, ip=client_ip(request), details={"file": item.file_name},
        description=f"{actor.full_name} удалил материал «{item.title}» из «{_path(db, item.folder_id)}»")
    db.flush()
    (library_dir() / item.stored_name).unlink(missing_ok=True)


@router.get("/items/{item_id}/link", response_model=FileLinkOut)
def item_link(item_id: UUID, actor: Actor = Depends(USERS), db=Depends(get_db)):
    _item(db, item_id)  # RLS: только общее и своё
    return FileLinkOut(url=f"/api/v1/library/files/{item_id}?t={create_file_token(item_id)}")


@router.get("/files/{item_id}", include_in_schema=False)
def item_file(item_id: UUID, t: str, download: bool = False):
    """Сам файл. Доступ — по подписанной ссылке из /items/{id}/link (она проверяет права)."""
    try:
        if decode_file_token(t) != str(item_id):
            raise jwt.InvalidTokenError
    except jwt.PyJWTError:
        raise HTTPException(403, "Ссылка недействительна или устарела. Откройте материал заново.")
    with tenant_session(bypass=True) as db:
        item = db.get(LibraryItem, item_id)
        if item is None or item.deleted_at is not None:
            raise HTTPException(404, "Материал не найден")
    path = library_dir() / item.stored_name
    if not path.exists():
        raise HTTPException(404, "Файл не найден на сервере")
    return FileResponse(path, media_type=item.mime, filename=item.file_name,
                        content_disposition_type="attachment" if download else "inline")
