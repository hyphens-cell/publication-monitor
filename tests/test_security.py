from pathlib import Path

import pytest

from app.admin.system import _pg_dump_command
from app.extensions import db
from app.models import Department, Plan, Publication, User
from app.publications import normalize_doi


def make_user(username, role, department_id=None):
    user = User(
        username=username,
        full_name=username,
        email=f"{username}@example.test",
        role=role,
        department_id=department_id,
        is_active=True,
    )
    user.set_password("correct-horse-battery-staple")
    db.session.add(user)
    db.session.commit()
    return user


def login(client, username):
    return client.post(
        "/auth/login",
        data={"username": username, "password": "correct-horse-battery-staple"},
        follow_redirects=False,
    )


def test_unauthenticated_requests_redirect_to_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_technical_admin_cannot_open_publications(client, app):
    with app.app_context():
        make_user("tech", "TECH_ADMIN")

    login(client, "tech")
    response = client.get("/publications/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_department_head_cannot_read_another_department_publication(client, app):
    with app.app_context():
        own = Department(name="Own", code="OWN", is_active=True)
        other = Department(name="Other", code="OTHER", is_active=True)
        db.session.add_all([own, other])
        db.session.commit()
        make_user("head", "DEPARTMENT_HEAD", own.id)
        publication = Publication(department_id=other.id, title="Hidden", status="PREPARATION")
        db.session.add(publication)
        db.session.commit()
        publication_id = publication.id

    login(client, "head")
    response = client.get(f"/publications/{publication_id}")
    assert response.status_code == 403


def test_admin_cannot_edit_department_publication(client, app):
    with app.app_context():
        department = Department(name="Department", code="DEP", is_active=True)
        db.session.add(department)
        db.session.commit()
        make_user("admin", "ADMIN")
        publication = Publication(department_id=department.id, title="Record", status="PREPARATION")
        db.session.add(publication)
        db.session.commit()
        publication_id = publication.id

    login(client, "admin")
    response = client.get(f"/publications/{publication_id}/edit", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_doi_normalization_handles_url_case_and_spaces():
    assert normalize_doi(" https://doi.org/10.1000/Ab C ") == "10.1000/abc"
    assert normalize_doi("doi:10.1000/ABC") == "10.1000/abc"
    assert normalize_doi("   ") is None


def test_technical_admin_routes_are_registered(app):
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    assert {
        "admin.audit_list",
        "admin.list_references",
        "admin.system_status",
        "admin.list_backups",
    } <= endpoints


def test_technical_admin_can_open_audit_and_system_pages(client, app):
    with app.app_context():
        make_user("tech", "TECH_ADMIN")

    login(client, "tech")
    audit_response = client.get("/admin/audit")
    references_response = client.get("/admin/references")
    assert audit_response.status_code == 200
    assert audit_response.content_type.startswith("text/html")
    assert references_response.status_code == 302
    assert client.get("/admin/api/audit").is_json
    assert client.get("/admin/api/references").status_code == 302
    system_response = client.get("/admin/system")
    backups_response = client.get("/admin/system/backups")
    assert system_response.status_code == 200
    assert system_response.content_type.startswith("text/html")
    assert backups_response.status_code == 200
    assert backups_response.content_type.startswith("text/html")
    assert client.get("/admin/system/status").is_json
    assert client.get("/admin/system/api/backups").is_json


def test_non_technical_roles_cannot_open_system_pages(client, app):
    with app.app_context():
        make_user("admin", "ADMIN")

    login(client, "admin")
    for path in (
        "/admin/system",
        "/admin/system/backups",
        "/admin/system/status",
        "/admin/system/api/backups",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/")


def test_department_head_list_routes_default_to_own_department(client, app):
    with app.app_context():
        own = Department(name="Own", code="OWN", is_active=True)
        other = Department(name="Other", code="OTHER", is_active=True)
        db.session.add_all([own, other])
        db.session.commit()
        head = make_user("head", "DEPARTMENT_HEAD", own.id)
        db.session.add_all(
            [
                Publication(department_id=own.id, title="Visible", status="PREPARATION"),
                Publication(department_id=other.id, title="Hidden", status="PREPARATION"),
                Plan(department_id=own.id, year=2026, status="APPROVED", created_by=head.id),
                Plan(department_id=other.id, year=2099, status="APPROVED", created_by=head.id),
            ]
        )
        db.session.commit()
        own_id = own.id
        other_id = other.id

    login(client, "head")
    for path in ("/publications/", "/analytics/", "/reports/publications"):
        response = client.get(path)
        assert response.status_code == 200

    publications_html = client.get("/publications/").get_data(as_text=True)
    assert "Visible" in publications_html
    assert "Hidden" not in publications_html
    assert "2026" in publications_html
    assert "2099" not in publications_html
    assert "2099" not in client.get("/analytics/").get_data(as_text=True)
    assert "2099" not in client.get("/reports/publications").get_data(as_text=True)
    assert client.get(f"/publications/?department_id={own_id}").status_code == 200
    assert client.get(f"/publications/?department_id={other_id}").status_code == 403


@pytest.mark.parametrize(
    ("role", "required_links", "forbidden_links"),
    (
        (
            "TECH_ADMIN",
            ("/admin/users", "/admin/departments", "/admin/system/backups"),
            ("/plans/", "/publications/", "/monitoring/"),
        ),
        (
            "ADMIN",
            ("/plans/", "/publications/", "/monitoring/", "/analytics/"),
            ("/admin/users", "/employees/", "/admin/system"),
        ),
        (
            "DEPARTMENT_HEAD",
            ("/plans/", "/publications/", "/employees/"),
            ("/admin/users", "/monitoring/", "/admin/system"),
        ),
    ),
)
def test_navigation_is_role_aware(
    client,
    app,
    role,
    required_links,
    forbidden_links,
):
    with app.app_context():
        department_id = None
        if role == "DEPARTMENT_HEAD":
            department = Department(name="Own", code="OWN", is_active=True)
            db.session.add(department)
            db.session.commit()
            department_id = department.id
        make_user(role.lower(), role, department_id)

    login(client, role.lower())
    html = client.get("/").get_data(as_text=True)
    for path in required_links:
        assert f'href="{path}' in html
    for path in forbidden_links:
        assert f'href="{path}' not in html


def test_not_found_uses_safe_error_page(client):
    response = client.get("/missing-page")
    assert response.status_code == 404
    assert "Страница не найдена" in response.get_data(as_text=True)


def test_language_selection_persists_and_preserves_local_path(client, app):
    with app.app_context():
        user = make_user("head", "DEPARTMENT_HEAD")
        user.language = "ru"
        db.session.commit()

    login(client, "head")
    response = client.post(
        "/auth/language",
        data={"language": "kk", "next": "/plans/?year=2026"},
        follow_redirects=False,
    )
    assert response.headers["Location"].endswith("/plans/?year=2026")
    with app.app_context():
        assert User.query.filter_by(username="head").one().language == "kk"


def test_backup_command_keeps_password_out_of_command_line(monkeypatch):
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    command, process_env = _pg_dump_command(
        "postgresql+psycopg://backup_user:secret-password@db.example:5433/publications",
        Path("backup.dump"),
    )
    assert "secret-password" not in " ".join(command)
    assert process_env["PGPASSWORD"] == "secret-password"
    assert command[command.index("--dbname") + 1] == "publications"


def test_backup_command_uses_environment_password(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "environment-secret")
    command, process_env = _pg_dump_command(
        "postgresql+psycopg://backup_user@db.example/publications",
        Path("backup.dump"),
    )
    assert "environment-secret" not in " ".join(command)
    assert process_env["PGPASSWORD"] == "environment-secret"
