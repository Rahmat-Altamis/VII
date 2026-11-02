import os

from alembic import context
from vii.persistence.models import Base
target_metadata = Base.metadata


def _url() -> str:
    # Explicit -x url= wins, then VII_DATABASE_URL, then alembic.ini default.
    return (context.get_x_argument(as_dictionary=True).get("url")
            or os.environ.get("VII_DATABASE_URL")
            or "sqlite:///./data/vii.db")


def run_migrations_offline():
    context.configure(url=_url(),
                      target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
def run_migrations_online():
    from sqlalchemy import create_engine
    url = _url()
    with create_engine(url).connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
