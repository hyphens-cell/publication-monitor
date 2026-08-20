from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint, Index, CheckConstraint

from app.extensions import db, bcrypt

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    role = db.Column(db.String(30), nullable=False)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    language = db.Column(db.String(2), nullable=False, default="ru")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    department = db.relationship(
        "Department",
        back_populates="users",
        foreign_keys=[department_id],
    )

    created_plans = db.relationship(
        "Plan",
        back_populates="creator",
        foreign_keys="Plan.created_by",
    )

    notifications = db.relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    comments = db.relationship(
        "Comment",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    audit_logs = db.relationship(
        "AuditLog",
        back_populates="user",
    )

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    users = db.relationship(
        "User",
        back_populates="department",
        foreign_keys="User.department_id",
    )

    employees = db.relationship(
        "Employee",
        back_populates="department",
        cascade="all, delete-orphan",
    )

    plans = db.relationship(
        "Plan",
        back_populates="department",
        cascade="all, delete-orphan",
    )

    publications = db.relationship(
        "Publication",
        back_populates="department",
    )


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    full_name = db.Column(db.String(255), nullable=False)
    position = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    department = db.relationship(
        "Department",
        back_populates="employees",
    )

    publication_links = db.relationship(
        "PublicationAuthor",
        back_populates="employee",
        cascade="all, delete-orphan",
    )

    plan_item_links = db.relationship(
        "PlanItemAuthor",
        back_populates="employee",
        cascade="all, delete-orphan",
    )


class Plan(db.Model):
    __tablename__ = "plans"

    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    year = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="DRAFT")
    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    submitted_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "year",
            name="uq_plan_department_year",
        ),
        CheckConstraint(
            "year >= 2000 AND year <= 2100",
            name="ck_plan_year",
        ),
    )

    department = db.relationship(
        "Department",
        back_populates="plans",
    )

    creator = db.relationship(
        "User",
        back_populates="created_plans",
        foreign_keys=[created_by],
    )

    items = db.relationship(
        "PlanItem",
        back_populates="plan",
        cascade="all, delete-orphan",
    )

    versions = db.relationship(
        "PlanVersion",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanVersion.version_number",
    )


class PlanItem(db.Model):
    __tablename__ = "plan_items"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(
        db.Integer,
        db.ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = db.Column(db.String(1000), nullable=False)
    publication_type_id = db.Column(
        db.Integer,
        db.ForeignKey("reference_values.id", ondelete="RESTRICT"),
        nullable=False,
    )
    journal = db.Column(db.String(500), nullable=True)
    quartile_id = db.Column(
        db.Integer,
        db.ForeignKey("reference_values.id", ondelete="RESTRICT"),
        nullable=True,
    )
    planned_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="PLANNED")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    plan = db.relationship(
        "Plan",
        back_populates="items",
    )

    publication_type = db.relationship(
        "ReferenceValue",
        foreign_keys=[publication_type_id],
    )

    quartile = db.relationship(
        "ReferenceValue",
        foreign_keys=[quartile_id],
    )

    author_links = db.relationship(
        "PlanItemAuthor",
        back_populates="plan_item",
        cascade="all, delete-orphan",
    )

    publication = db.relationship(
        "Publication",
        back_populates="plan_item",
        uselist=False,
    )


class PlanItemAuthor(db.Model):
    __tablename__ = "plan_item_authors"

    plan_item_id = db.Column(
        db.Integer,
        db.ForeignKey("plan_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    plan_item = db.relationship(
        "PlanItem",
        back_populates="author_links",
    )

    employee = db.relationship(
        "Employee",
        back_populates="plan_item_links",
    )


class PlanVersion(db.Model):
    __tablename__ = "plan_versions"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(
        db.Integer,
        db.ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number = db.Column(db.Integer, nullable=False)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status = db.Column(db.String(30), nullable=False)
    comment = db.Column(db.Text, nullable=True)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "version_number",
            name="uq_plan_version",
        ),
    )

    plan = db.relationship(
        "Plan",
        back_populates="versions",
    )

    creator = db.relationship(
        "User",
        foreign_keys=[created_by],
    )


class Publication(db.Model):
    __tablename__ = "publications"

    id = db.Column(db.Integer, primary_key=True)
    plan_item_id = db.Column(
        db.Integer,
        db.ForeignKey("plan_items.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
    )
    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=False,
    )

    title = db.Column(db.String(1000), nullable=False)
    doi = db.Column(db.String(500),  nullable=True)
    url = db.Column(db.String(1000), nullable=True)

    journal = db.Column(db.String(500), nullable=True)
    publication_year = db.Column(db.Integer, nullable=True)
    volume = db.Column(db.String(100), nullable=True)
    issue = db.Column(db.String(100), nullable=True)
    pages = db.Column(db.String(100), nullable=True)

    indexing_type_id = db.Column(
        db.Integer,
        db.ForeignKey("reference_values.id", ondelete="RESTRICT"),
        nullable=True,
    )
    quartile_id = db.Column(
        db.Integer,
        db.ForeignKey("reference_values.id", ondelete="RESTRICT"),
        nullable=True,
    )

    affiliation = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False, default="PREPARATION")

    verification_status = db.Column(
        db.String(30),
        nullable=False,
        default="PENDING",
    )

    verified_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    verified_at = db.Column(
        db.DateTime,
        nullable=True,
    )

    verifier = db.relationship(
        "User",
        foreign_keys=[verified_by],
    )

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_publications_department", "department_id"),
        Index("ix_publications_status", "status"),
        Index("ix_publications_year", "publication_year"),
        Index("ix_publications_title", "title"),
    )

    plan_item = db.relationship(
        "PlanItem",
        back_populates="publication",
    )

    department = db.relationship(
        "Department",
        back_populates="publications",
    )

    indexing_type = db.relationship(
        "ReferenceValue",
        foreign_keys=[indexing_type_id],
    )

    quartile = db.relationship(
        "ReferenceValue",
        foreign_keys=[quartile_id],
    )

    author_links = db.relationship(
        "PublicationAuthor",
        back_populates="publication",
        cascade="all, delete-orphan",
        order_by="PublicationAuthor.author_order",
    )

    history = db.relationship(
        "PublicationHistory",
        back_populates="publication",
        cascade="all, delete-orphan",
        order_by="PublicationHistory.changed_at",
    )

    attachments = db.relationship(
        "Attachment",
        back_populates="publication",
        cascade="all, delete-orphan",
    )


class PublicationAuthor(db.Model):
    __tablename__ = "publication_authors"

    publication_id = db.Column(
        db.Integer,
        db.ForeignKey("publications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    author_order = db.Column(db.Integer, nullable=False, default=1)

    publication = db.relationship(
        "Publication",
        back_populates="author_links",
    )

    employee = db.relationship(
        "Employee",
        back_populates="publication_links",
    )


class PublicationHistory(db.Model):
    __tablename__ = "publication_history"

    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(
        db.Integer,
        db.ForeignKey("publications.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    old_status = db.Column(db.String(50), nullable=True)
    new_status = db.Column(db.String(50), nullable=False)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    publication = db.relationship(
        "Publication",
        back_populates="history",
    )

    user = db.relationship(
        "User",
        foreign_keys=[user_id],
    )


class Attachment(db.Model):
    __tablename__ = "attachments"

    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(
        db.Integer,
        db.ForeignKey("publications.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_filename = db.Column(db.String(500), nullable=False)
    stored_filename = db.Column(db.String(500), nullable=False)
    file_path = db.Column(db.String(1000), nullable=False)
    mime_type = db.Column(db.String(255), nullable=True)
    file_size = db.Column(db.BigInteger, nullable=True)
    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    review_status = db.Column(
        db.String(30),
        nullable=False,
        default="PENDING",
    )

    reviewed_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reviewed_at = db.Column(
        db.DateTime,
        nullable=True,
    )

    review_comment = db.Column(
        db.Text,
        nullable=True,
    )

    reviewer = db.relationship(
        "User",
        foreign_keys=[reviewed_by],
    )

    publication = db.relationship(
        "Publication",
        back_populates="attachments",
    )

    uploader = db.relationship(
        "User",
        foreign_keys=[uploaded_by],
    )


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index(
            "ix_comments_entity",
            "entity_type",
            "entity_id",
        ),
    )

    user = db.relationship(
        "User",
        back_populates="comments",
    )


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    type = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    message = db.Column(db.Text, nullable=False)
    entity_type = db.Column(db.String(50), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    email_sent = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        Index(
            "ix_notifications_user_read",
            "user_id",
            "is_read",
        ),
    )

    user = db.relationship(
        "User",
        back_populates="notifications",
    )


class ReferenceValue(db.Model):
    __tablename__ = "reference_values"

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(100), nullable=False)
    name_ru = db.Column(db.String(255), nullable=False)
    name_kk = db.Column(db.String(255), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint(
            "type",
            "code",
            name="uq_reference_type_code",
        ),
        Index(
            "ix_reference_values_type",
            "type",
        ),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index(
            "ix_audit_logs_entity",
            "entity_type",
            "entity_id",
        ),
        Index("ix_audit_logs_user", "user_id"),
    )

    user = db.relationship(
        "User",
        back_populates="audit_logs",
    )