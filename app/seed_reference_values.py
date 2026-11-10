from app.extensions import db
from app.models import ReferenceValue

REFERENCE_VALUES = [
    # Publication types
    {
        "type": "PUBLICATION_TYPE",
        "code": "ARTICLE",
        "name_ru": "Научная статья",
        "name_kk": "Ғылыми мақала",
        "sort_order": 10,
    },
    {
        "type": "PUBLICATION_TYPE",
        "code": "CONFERENCE_PAPER",
        "name_ru": "Материалы конференции",
        "name_kk": "Конференция материалдары",
        "sort_order": 20,
    },
    {
        "type": "PUBLICATION_TYPE",
        "code": "MONOGRAPH",
        "name_ru": "Монография",
        "name_kk": "Монография",
        "sort_order": 30,
    },
    {
        "type": "PUBLICATION_TYPE",
        "code": "BOOK_CHAPTER",
        "name_ru": "Глава в книге",
        "name_kk": "Кітаптағы тарау",
        "sort_order": 40,
    },
    {
        "type": "PUBLICATION_TYPE",
        "code": "REVIEW_ARTICLE",
        "name_ru": "Обзорная статья",
        "name_kk": "Шолу мақаласы",
        "sort_order": 50,
    },
    # Indexing types
    {
        "type": "INDEXING_TYPE",
        "code": "SCOPUS",
        "name_ru": "Scopus",
        "name_kk": "Scopus",
        "sort_order": 10,
    },
    {
        "type": "INDEXING_TYPE",
        "code": "WEB_OF_SCIENCE",
        "name_ru": "Web of Science",
        "name_kk": "Web of Science",
        "sort_order": 20,
    },
    {
        "type": "INDEXING_TYPE",
        "code": "SCOPUS_WOS",
        "name_ru": "Scopus + Web of Science",
        "name_kk": "Scopus + Web of Science",
        "sort_order": 30,
    },
    {
        "type": "INDEXING_TYPE",
        "code": "OTHER",
        "name_ru": "Другая индексация",
        "name_kk": "Басқа индекстеу",
        "sort_order": 40,
    },
    {
        "type": "INDEXING_TYPE",
        "code": "NOT_INDEXED",
        "name_ru": "Не индексируется",
        "name_kk": "Индекстелмейді",
        "sort_order": 50,
    },
    # Quartiles
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


LEGACY_INVALID_PUBLICATION_TYPES = {
    "SCOPUS",
    "WEB_OF_SCIENCE",
}


def seed_reference_values():
    created_count = 0

    for data in REFERENCE_VALUES:
        existing = (
            db.session.query(ReferenceValue)
            .filter_by(
                type=data["type"],
                code=data["code"],
            )
            .first()
        )

        if existing is None:
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
            continue

        existing.name_ru = data["name_ru"]
        existing.name_kk = data["name_kk"]
        existing.sort_order = data["sort_order"]
        existing.is_active = True

    legacy_values = (
        db.session.query(ReferenceValue)
        .filter(
            ReferenceValue.type == "PUBLICATION_TYPE",
            ReferenceValue.code.in_(LEGACY_INVALID_PUBLICATION_TYPES),
        )
        .all()
    )

    for legacy_value in legacy_values:
        legacy_value.is_active = False

    db.session.commit()

    return created_count
