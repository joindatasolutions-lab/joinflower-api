"""Los timestamps sin zona de la aplicación representan hora de Colombia."""

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator

from app.core.timezone import as_colombia_naive_datetime


class ColombiaDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return as_colombia_naive_datetime(value)

    def process_result_value(self, value, dialect):
        return as_colombia_naive_datetime(value)
