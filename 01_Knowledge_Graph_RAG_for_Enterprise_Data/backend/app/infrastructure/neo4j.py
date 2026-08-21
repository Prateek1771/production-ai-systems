from neo4j import GraphDatabase

from app.config.settings import settings


driver = GraphDatabase.driver(
    settings.neo4j_uri,
    auth=(
        settings.neo4j_user,
        settings.neo4j_password,
    ),
)


def verify_connection() -> bool:
    try:
        driver.verify_connectivity()
        return True
    except Exception:
        return False