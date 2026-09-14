from app.extensions import db
from app.models import Department, Publication, User
from app.publications import normalize_doi
from app.admin.system import _pg_dump_command
from pathlib import Path


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
    assert {"admin.audit_list", "admin.list_references", "admin.system_status", "admin.list_backups"} <= endpoints


def test_technical_admin_can_open_audit_and_system_pages(client, app):
    with app.app_context():
        make_user("tech", "TECH_ADMIN")

    login(client, "tech")
    assert client.get("/admin/audit?view=1").status_code == 200
    assert client.get("/admin/system").status_code == 200


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
