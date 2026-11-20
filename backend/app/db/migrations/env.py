import os

from alembic import context
from sqlalchemy import create_engine, pool

cfg = context.config
url = cfg.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]


def run() -> None:
    if context.is_offline_mode():
        context.configure(url=url, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn)
        with context.begin_transaction():
            context.run_migrations()


run()
