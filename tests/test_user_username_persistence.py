from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.bot.handlers.screens import _get_or_create_user
from app.db.base import Base
from app.db.models import User


def test_get_or_create_user_saves_username() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = _get_or_create_user(session, 12345, "first_name")
        session.commit()
        session.refresh(user)

        assert user.telegram_username == "first_name"


def test_get_or_create_user_updates_username_if_new_value_provided() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _get_or_create_user(session, 12345, "first_name")
        session.commit()

        _get_or_create_user(session, 12345, "second_name")
        session.commit()

        saved = session.query(User).filter(User.telegram_user_id == 12345).one()
        assert saved.telegram_username == "second_name"
