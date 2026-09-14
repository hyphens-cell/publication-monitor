from app.extensions import db
from app.models import Department, Employee, Plan, PlanItem, Publication, ReferenceValue, User


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
    )


def make_plan(department_id, creator_id, status="DRAFT", with_item=True):
    plan = Plan(department_id=department_id, year=2027, created_by=creator_id, status=status)
    db.session.add(plan)
    db.session.flush()
    if with_item:
        publication_type = ReferenceValue(
            type="PUBLICATION_TYPE", code="SCOPUS", name_ru="Scopus", name_kk="Scopus", sort_order=1, is_active=True
        )
        db.session.add(publication_type)
        db.session.flush()
        db.session.add(PlanItem(plan_id=plan.id, title="Publication", publication_type_id=publication_type.id, status="PLANNED"))
    db.session.commit()
    return plan


def test_empty_plan_cannot_be_submitted(client, app):
    with app.app_context():
        department = Department(name="Department", code="DEP", is_active=True)
        db.session.add(department)
        db.session.commit()
        head = make_user("head", "DEPARTMENT_HEAD", department.id)
        plan = make_plan(department.id, head.id, with_item=False)
        plan_id = plan.id

    login(client, "head")
    response = client.post(f"/plans/{plan_id}/submit", follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Plan, plan_id).status == "DRAFT"


def test_plan_submission_return_and_approval_create_publications(client, app):
    with app.app_context():
        department = Department(name="Department", code="DEP", is_active=True)
        db.session.add(department)
        db.session.commit()
        head = make_user("head", "DEPARTMENT_HEAD", department.id)
        make_user("admin", "ADMIN")
        plan = make_plan(department.id, head.id)
        plan_id = plan.id

    login(client, "head")
    assert client.post(f"/plans/{plan_id}/submit").status_code == 302
    with app.app_context():
        assert db.session.get(Plan, plan_id).status == "SUBMITTED"

    client.post("/auth/logout")
    login(client, "admin")
    assert client.post(f"/plans/{plan_id}/return", data={"comment": "Исправьте данные"}).status_code == 302
    with app.app_context():
        assert db.session.get(Plan, plan_id).status == "RETURNED"

    client.post("/auth/logout")
    login(client, "head")
    client.post(f"/plans/{plan_id}/submit")
    client.post("/auth/logout")
    login(client, "admin")
    assert client.post(f"/plans/{plan_id}/approve").status_code == 302
    with app.app_context():
        assert db.session.get(Plan, plan_id).status == "APPROVED"
        assert Publication.query.join(Publication.plan_item).filter_by(plan_id=plan_id).count() == 1


def test_approved_plan_cannot_be_edited_by_department_head(client, app):
    with app.app_context():
        department = Department(name="Department", code="DEP", is_active=True)
        db.session.add(department)
        db.session.commit()
        head = make_user("head", "DEPARTMENT_HEAD", department.id)
        plan = make_plan(department.id, head.id, status="APPROVED")
        plan_id = plan.id
        item_id = plan.items[0].id

    login(client, "head")
    response = client.post(f"/plans/{plan_id}/items/{item_id}/delete", follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(PlanItem, item_id) is not None
