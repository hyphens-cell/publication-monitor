from app.extensions import db
from app.models import ReferenceValue


REFERENCE_VALUES = [
    {
        "type": "PUBLICATION_TYPE",
        "code": "SCOPUS",
        "name_ru": "Scopus",
        "name_kk": "Scopus",
        "sort_order": 10,
    },
    {
        "type": "PUBLICATION_TYPE",
        "code": "WEB_OF_SCIENCE",
        "name_ru": "Web of Science",
        "name_kk": "Web of Science",
        "sort_order": 20,
    },
    {
        "type": "QUARTILE",
        "code": "Q1",
        "name_ru": "Q1",
        "name_kk": "Q1",
        "sort_order": 10,
    },
    {
        "type": "QUARTILE",
        "code": "Q2",
        "name_ru": "Q2",
        "name_kk": "Q2",
        "sort_order": 20,
    },
    {
        "type": "QUARTILE",
        "code": "Q3",
        "name_ru": "Q3",
        "name_kk": "Q3",
        "sort_order": 30,
    },
    {
        "type": "QUARTILE",
        "code": "Q4",
        "name_ru": "Q4",
        "name_kk": "Q4",
        "sort_order": 40,
    },
    {
        "type": "QUARTILE",
        "code": "NO_QUARTILE",
        "name_ru": "Без квартиля",
        "name_kk": "Квартиль жоқ",
        "sort_order": 50,
    },
]


def seed_reference_values():
    created_count = 0

    for data in REFERENCE_VALUES:
        existing = db.session.query(ReferenceValue).filter_by(
            type=data["type"],
            code=data["code"],
        ).first()

        if existing is not None:
            continue

        db.session.add(
            ReferenceValue(
                type=data["type"],
                code=data["code"],
                name_ru=data["name_ru"],
                name_kk=data["name_kk"],
                sort_order=data["sort_order"],
                is_active=True,
            )
        )

        created_count += 1

    db.session.commit()

    return created_count