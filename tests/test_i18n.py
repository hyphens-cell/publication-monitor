from app.extensions import db
from app.i18n import (
    ATTACHMENT_STATUS_LABELS,
    PLAN_STATUS_LABELS,
    PUBLICATION_STATUS_LABELS,
    ROLE_LABELS,
    VERIFICATION_STATUS_LABELS,
    localized_label,
)
from app.models import User


def make_user(username="kk_user", language="kk"):
    user = User(
        username=username,
        full_name="Тест пайдаланушы",
        email=f"{username}@example.test",
        role="TECH_ADMIN",
        language=language,
        is_active=True,
    )
    user.set_password("correct-horse-battery-staple")
    db.session.add(user)
    db.session.commit()
    return user


def test_all_jinja_templates_compile(app):
    names = app.jinja_env.list_templates()
    for name in names:
        app.jinja_env.get_template(name)
    assert len(names) == 24


def test_anonymous_kazakh_login_is_fully_localized(client):
    client.post(
        "/auth/language",
        data={"language": "kk", "next": "/auth/login"},
    )
    response = client.get("/auth/login")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<html lang="kk">' in html
    assert "Кіру — Жарияланымдар мониторингі" in html
    assert 'placeholder="Логинді енгізіңіз"' in html
    assert "Вход в систему" not in html


def test_language_survives_logout(client, app):
    with app.app_context():
        make_user()

    client.post(
        "/auth/login",
        data={
            "username": "kk_user",
            "password": "correct-horse-battery-staple",
        },
    )
    client.post("/auth/logout")
    response = client.get("/auth/login")

    assert '<html lang="kk">' in response.get_data(as_text=True)


def test_all_role_and_status_codes_have_ru_and_kk_labels(app):
    catalogues = (
        ROLE_LABELS,
        PLAN_STATUS_LABELS,
        PUBLICATION_STATUS_LABELS,
        VERIFICATION_STATUS_LABELS,
        ATTACHMENT_STATUS_LABELS,
    )
    with app.test_request_context("/"):
        for catalogue in catalogues:
            for code, russian_label in catalogue.items():
                assert localized_label(catalogue, code) == russian_label

        from flask import session

        session["language"] = "kk"
        for catalogue in catalogues:
            for code in catalogue:
                label = localized_label(catalogue, code)
                assert label != code
                assert label != catalogue[code] or catalogue[code] == "Монитор"
