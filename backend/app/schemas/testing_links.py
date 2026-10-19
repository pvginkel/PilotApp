"""Schema for the testing endpoint that sets the deployment's link settings."""

from pydantic import BaseModel, Field


class LinkSettingsSchema(BaseModel):
    """The link settings the deployment's environment sets (F91, F93); a
    setting left out or null is unset."""

    ticket_url_template: str | None = Field(
        default=None,
        description="A ticket's address, `{id}` standing for its id",
        examples=["https://tracker.example.com/issue/{id}", None],
    )
    environment_link_base_url: str | None = Field(
        default=None,
        description="KubeCoder's address, without a trailing slash once set",
        examples=["https://kubecoder.example.com", None],
    )
