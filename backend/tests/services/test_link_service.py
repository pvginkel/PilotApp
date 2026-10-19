"""LinkService: the record's environments, which text links (F93)."""

from sqlalchemy.orm import Session

from app.models import Environment
from app.services.container import ServiceContainer


class TestLinkService:
    def test_no_environment_reads_empty(self, container: ServiceContainer) -> None:
        assert container.link_service().environments() == []

    def test_environments_by_name_then_id(
        self, container: ServiceContainer, session: Session
    ) -> None:
        for env_id, name in [
            ("env-c", "Beta-1"),
            ("env-b", "Alpha-1"),
            ("env-a", "Beta-1"),
        ]:
            session.add(Environment(id=env_id, name=name, exempt=False))
        session.flush()

        assert [
            (environment.id, environment.name)
            for environment in container.link_service().environments()
        ] == [("env-b", "Alpha-1"), ("env-a", "Beta-1"), ("env-c", "Beta-1")]
