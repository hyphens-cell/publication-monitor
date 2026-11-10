"""Representative list query budgets; all data lives in the test database."""

from time import perf_counter

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import Department, Plan, PlanItem, Publication, ReferenceValue, User


def seed_list_workload():
    department = Department(name="Performance department", code="PERF")
    user = User(
        username="performance",
        full_name="Performance monitor",
        email="perf@example.test",
        password_hash="unused",
        role="ADMIN",
    )
    reference = ReferenceValue(type="PUBLICATION_TYPE", code="ARTICLE", name_ru="Статья", name_kk="Мақала")
    db.session.add_all([department, user, reference])
    db.session.flush()
    for index in range(30):
        plan = Plan(department=department, year=2000 + index, creator=user, status="APPROVED")
        item = PlanItem(plan=plan, title=f"Performance item {index:02}", publication_type=reference)
        publication = Publication(
            plan_item=item,
            department=department,
            title=f"Performance publication {index:02}",
            journal="Journal",
            publication_year=plan.year,
            status="PUBLISHED",
            verification_status="APPROVED",
        )
        db.session.add_all([plan, item, publication])
    db.session.commit()
    return user.id


@pytest.mark.parametrize(
    "path", ["/plans/", "/publications/", "/reports/publications", "/monitoring/", "/analytics/"]
)
def test_list_query_budget(app, client, path):
    user_id = seed_list_workload()
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    db.session.remove()
    queries = []

    def record_query(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(db.engine, "before_cursor_execute", record_query)
    start = perf_counter()
    try:
        response = client.get(path)
    finally:
        duration = (perf_counter() - start) * 1000
        event.remove(db.engine, "before_cursor_execute", record_query)
    assert response.status_code == 200
    print(f"QUERY_BENCHMARK {path} rows=30 queries={len(queries)} elapsed_ms={duration:.2f}")
