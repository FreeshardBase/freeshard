from datetime import datetime, timezone

from sqlalchemy.exc import NoResultFound
from sqlmodel import select

from portal_core.database.database import session
from portal_core.database.models import Terminal
from portal_core.util.signals import on_terminal_auth


@on_terminal_auth.connect
def update_terminal_last_connection(terminal: Terminal):
	with session() as session_:
		existing_terminal = session_.exec(select(Terminal).where(Terminal.id == terminal.id)).one()
		existing_terminal.last_connection = datetime.now(timezone.utc)
		session_.add(existing_terminal)
		session_.commit()


def get_terminal_by_id(terminal_id: str) -> Terminal:
	with session() as session_:
		statement = select(Terminal).where(Terminal.id == terminal_id)
		try:
			return session_.exec(statement).one()
		except NoResultFound as e:
			raise KeyError(terminal_id) from e
