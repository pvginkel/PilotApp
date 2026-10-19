"""Schema for GET /api/links: what links in text (F91, F93)."""

from pydantic import BaseModel, Field


class EnvironmentNameSchema(BaseModel):
    """An environment of the record, by its id and the name text calls it by."""

    id: str = Field(
        description="The KubeCoder environment id", examples=["example-env-1"]
    )
    name: str = Field(description="The environment's name", examples=["Example-1"])


class LinksResponseSchema(BaseModel):
    """The deployment's link settings and the record's environments."""

    ticket_id_pattern: str = Field(
        description="The regular expression a whole ticket id matches (F91)",
        examples=["[A-Z][A-Z0-9_]*-[1-9][0-9]*"],
    )
    ticket_url_template: str | None = Field(
        description=(
            "A ticket's address, `{id}` standing for its id; null when unset, and "
            "ticket ids then show unlinked"
        ),
        examples=["https://tracker.example.com/issue/{id}", None],
    )
    environment_link_base_url: str | None = Field(
        description=(
            "KubeCoder's address, without a trailing slash: an environment links to "
            "`<base>/environments/<environment id>/ssh/open`; null when unset, and "
            "environments then show unlinked"
        ),
        examples=["https://kubecoder.example.com", None],
    )
    environments: list[EnvironmentNameSchema] = Field(
        description="Every environment of the record, by name"
    )
