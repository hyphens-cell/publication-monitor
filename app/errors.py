"""Rollback failed requests without exposing SQL parameters or credentials."""

from flask import current_app, g, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.i18n import translate

ERRORS = {
    400: ("Некорректный запрос", "Проверьте введённые данные и повторите попытку."),
    403: ("Доступ запрещён", "У вас нет прав для выполнения этого действия."),
    404: ("Страница не найдена", "Запрошенная страница или запись не существует."),
    409: ("Конфликт данных", "Данные были изменены. Обновите страницу и повторите попытку."),
    413: ("Файл слишком большой", "Выберите файл меньшего размера и повторите загрузку."),
    429: ("Слишком много запросов", "Повторите попытку позже."),
    500: ("Ошибка сервера", "Не удалось обработать запрос. Попробуйте ещё раз позже."),
}


def error_response(code):
    g.error_response = True
    title, message = ERRORS[code]
    if request.is_json or "/api/" in request.path:
        return jsonify(error=translate(message)), code
    return render_template("errors/error.html", status_code=code, title=title, message=message), code


def register_error_handlers(app):
    for code in ERRORS:
        app.register_error_handler(code, lambda error, code=code: error_response(code))

    @app.errorhandler(IntegrityError)
    def integrity_error(error):
        db.session.rollback()
        return error_response(409)

    @app.errorhandler(SQLAlchemyError)
    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        original = getattr(error, "original_exception", None) or error
        current_app.logger.error("Request failed (%s)", type(original).__name__)
        return error_response(500)
