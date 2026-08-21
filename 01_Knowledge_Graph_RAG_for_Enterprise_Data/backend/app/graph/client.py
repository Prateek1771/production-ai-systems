"""Neo4j session handling.

The driver is a long-lived connection pool and should be created once.
Sessions are cheap and must not be shared across threads, so they are
created per unit of work and closed by the context manager.
"""

from contextlib import contextmanager

from neo4j import Driver, GraphDatabase, Session

from app.config.settings import settings


_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver

    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_lifetime=3600,
            # Before the graph is built, every query warns that the
            # Entity label does not exist. That is expected, not useful.
            warn_notification_severity="OFF",
        )

    return _driver


@contextmanager
def session() -> Session:
    driver = get_driver()
    with driver.session() as active:
        yield active


def run_read(cypher: str, **parameters) -> list[dict]:
    with session() as active:
        result = active.run(cypher, **parameters)
        return [record.data() for record in result]


def run_write(cypher: str, **parameters) -> list[dict]:
    with session() as active:
        result = active.execute_write(
            lambda tx: [r.data() for r in tx.run(cypher, **parameters)]
        )
        return result


def close() -> None:
    global _driver

    if _driver is not None:
        _driver.close()
        _driver = None


if __name__ == "__main__":

    print("uri:", settings.neo4j_uri)
    print("nodes:", run_read("MATCH (n) RETURN count(n) AS n")[0]["n"])
    close()
