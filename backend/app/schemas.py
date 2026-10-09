from datetime import date, datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import normalize_phone, validate_password_strength

Role = Literal["superadmin", "center_admin", "org_admin", "employee"]
T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


def _phone(v: str | None) -> str | None:
    if v is None or v.strip() == "":
        return None
    return normalize_phone(v)


def _email(v: str | None) -> str | None:
    if v is None or v.strip() == "":
        return None
    v = v.strip()
    if "@" not in v or " " in v:
        raise ValueError("Некорректный адрес электронной почты")
    return v


# ---- Авторизация ----
class LoginIn(BaseModel):
    phone: str = Field(max_length=32)
    password: str = Field(max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, v: str) -> str:
        validate_password_strength(v)
        return v


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool


class MeOut(BaseModel):
    id: UUID
    phone: str
    full_name: str
    role: Role
    org_id: UUID | None
    must_change_password: bool


class CredentialsOut(BaseModel):
    user_id: UUID
    phone: str
    temporary_password: str
    message: str = "Пароль показан один раз. Передайте его пользователю; при первом входе он должен будет сменить пароль."


# ---- Организации ----
class OrganizationIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    inn: str | None = Field(default=None, pattern=r"^(\d{10}|\d{12})$")
    kpp: str | None = Field(default=None, pattern=r"^\d{9}$")
    legal_address: str | None = Field(default=None, max_length=1000)
    contact_phone: str | None = Field(default=None, max_length=20)
    contact_email: str | None = Field(default=None, max_length=254)
    responsible_name: str | None = Field(default=None, max_length=200)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    inn: str | None = Field(default=None, pattern=r"^(\d{10}|\d{12})$")
    kpp: str | None = Field(default=None, pattern=r"^\d{9}$")
    legal_address: str | None = Field(default=None, max_length=1000)
    contact_phone: str | None = Field(default=None, max_length=20)
    contact_email: str | None = Field(default=None, max_length=254)
    responsible_name: str | None = Field(default=None, max_length=200)
    status: Literal["active", "blocked"] | None = None


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    inn: str | None
    kpp: str | None
    legal_address: str | None
    contact_phone: str | None
    contact_email: str | None
    responsible_name: str | None
    status: str
    created_at: datetime


# ---- Подразделения / должности ----
class CatalogIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    org_id: UUID | None = None


class CatalogUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CatalogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    org_id: UUID
    name: str


# ---- Сотрудники ----
class EmployeeIn(BaseModel):
    org_id: UUID | None = None
    full_name: str = Field(min_length=1, max_length=200)
    birth_date: date | None = None
    department_id: UUID | None = None
    position_id: UUID | None = None
    phone: str | None = None
    email: str | None = Field(default=None, max_length=254)
    hired_at: date | None = None


    @field_validator("phone")
    @classmethod
    def check_phone(cls, v):
        return _phone(v)

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        return _email(v)


class EmployeeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    birth_date: date | None = None
    department_id: UUID | None = None
    position_id: UUID | None = None
    phone: str | None = None
    email: str | None = Field(default=None, max_length=254)
    hired_at: date | None = None


    @field_validator("phone")
    @classmethod
    def check_phone(cls, v):
        return _phone(v)

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        return _email(v)


class EmployeeOut(BaseModel):
    id: UUID
    org_id: UUID
    full_name: str
    birth_date: date | None
    department_id: UUID | None
    department_name: str | None
    position_id: UUID | None
    position_name: str | None
    phone: str | None
    email: str | None
    hired_at: date | None
    status: str
    has_access: bool
    last_login_at: datetime | None = None


class GrantAccessIn(BaseModel):
    phone: str | None = None

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v):
        return _phone(v)


# ---- Пользователи (руководящие роли) ----
class UserIn(BaseModel):
    phone: str
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    org_id: UUID | None = None

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v):
        return normalize_phone(v)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    org_id: UUID | None
    phone: str
    full_name: str
    role: Role
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    at: datetime
    actor_user_id: UUID | None
    org_id: UUID | None
    action: str
    entity_type: str
    entity_id: str | None
    description: str | None
    details: dict | None


# ---- Библиотека учебных материалов ----
class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: UUID | None = None
    org_id: UUID | None = None  # без родителя: None — общая библиотека (заказчику всегда своя)


class FolderUpdate(BaseModel):
    """parent_id: не передан — папка остаётся на месте, null — переносится в корень."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: UUID | None = None


class FolderOut(BaseModel):
    id: UUID
    org_id: UUID | None
    parent_id: UUID | None
    name: str
    items: int


class LibraryItemUpdate(BaseModel):
    """folder_id: не передан — материал остаётся на месте, null — переносится в корень."""
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    folder_id: UUID | None = None


class LibraryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    org_id: UUID | None
    folder_id: UUID | None
    title: str
    description: str | None
    kind: Literal["document", "video"]
    file_name: str
    mime: str
    size: int
    created_at: datetime


class FileLinkOut(BaseModel):
    url: str


# ---- Мой заказчик (для работника) ----
class CustomerContact(BaseModel):
    full_name: str
    phone: str


class MyCustomerOut(BaseModel):
    """Без сведений о входах: работник не видит, кто когда заходил."""
    name: str
    inn: str | None
    kpp: str | None
    legal_address: str | None
    contact_phone: str | None
    contact_email: str | None
    responsible_name: str | None
    contacts: list[CustomerContact]


# ---- Курсы и тесты ----
class TestOption(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    correct: bool = False


class TestQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    multiple: bool = False  # несколько правильных ответов
    options: list[TestOption] = Field(min_length=2, max_length=10)

    @field_validator("options")
    @classmethod
    def _correct(cls, v, info):
        n = sum(o.correct for o in v)
        if n == 0:
            raise ValueError("У каждого вопроса должен быть отмечен правильный ответ")
        if n > 1 and not info.data.get("multiple"):
            raise ValueError("Отмечено несколько правильных ответов — включите «несколько ответов»")
        return v


class CourseIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    pass_score: int = Field(default=80, ge=1, le=100)
    validity_months: int | None = Field(default=None, ge=1, le=120)


class CourseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    pass_score: int | None = Field(default=None, ge=1, le=100)
    validity_months: int | None = Field(default=None, ge=1, le=120)


class CourseOut(BaseModel):
    id: UUID
    org_id: UUID | None  # None — общий курс учебного центра
    org_name: str | None
    editable: bool
    title: str
    description: str | None
    pass_score: int
    validity_months: int | None
    materials: int
    questions: int


class CourseMaterialOut(BaseModel):
    item_id: UUID
    title: str
    kind: str
    file_name: str
    size: int


class CourseDetailOut(BaseModel):
    id: UUID
    org_id: UUID | None
    editable: bool
    title: str
    description: str | None
    pass_score: int
    validity_months: int | None
    materials: list[CourseMaterialOut]
    test: list[TestQuestion]


class CourseMaterialsIn(BaseModel):
    item_ids: list[UUID] = Field(max_length=200)  # весь список в нужном порядке


class CourseTestIn(BaseModel):
    questions: list[TestQuestion] = Field(max_length=200)


# ---- Назначение обучения ----
AssignmentState = Literal["assigned", "in_progress", "passed", "overdue", "expired"]


class AssignIn(BaseModel):
    course_id: UUID
    employee_ids: list[UUID] = Field(min_length=1, max_length=1000)
    due_date: date | None = None


class AssignResultOut(BaseModel):
    created: int
    skipped: list[str]  # ФИО тех, у кого этот курс уже назначен и не пройден


class AssignmentOut(BaseModel):
    id: UUID
    org_id: UUID
    org_name: str
    employee_id: UUID
    employee_name: str
    department_name: str | None
    course_id: UUID
    course_title: str
    assigned_at: datetime
    due_date: date | None
    state: AssignmentState
    viewed: int
    materials: int
    has_test: bool
    attempts: int
    score: int | None
    completed_at: datetime | None
    expires_at: date | None


class MyMaterialOut(BaseModel):
    item_id: UUID
    title: str
    description: str | None
    kind: str
    viewed: bool


class PublicQuestion(BaseModel):
    """Вопрос без правильных ответов — то, что видит работник."""
    text: str
    multiple: bool
    options: list[str]


class MyCourseOut(BaseModel):
    assignment: AssignmentOut
    description: str | None
    pass_score: int
    materials: list[MyMaterialOut]
    test: list[PublicQuestion]
    can_take_test: bool


class TestSubmitIn(BaseModel):
    answers: list[list[int]] = Field(max_length=200)  # номера выбранных вариантов по каждому вопросу


class TestResultOut(BaseModel):
    score: int
    passed: bool
    correct: int
    total: int
    pass_score: int
