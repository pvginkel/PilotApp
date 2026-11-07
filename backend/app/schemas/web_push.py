"""Schemas for web push: the deployment's key, and a browser's subscription
(F146; DB 311)."""

from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, Field, field_validator

from app.utils.base64url import unb64

_AUTH_SIZE = 16


class WebPushSetupSchema(BaseModel):
    """What a browser needs to turn its notifications on."""

    public_key: str | None = Field(
        description=(
            "The stage's VAPID public key, base64url, the applicationServerKey a "
            "browser subscribes with; null where the deployment sends no "
            "notifications"
        ),
    )


class PushSubscriptionKeysSchema(BaseModel):
    """A browser's keys, as its PushSubscription gives them."""

    p256dh: str = Field(
        description="The browser's P-256 public key, uncompressed, in base64url",
    )
    auth: str = Field(
        description="The browser's 16-octet authentication secret, in base64url",
    )

    @field_validator("p256dh")
    @classmethod
    def _is_a_p256_point(cls, value: str) -> str:
        try:
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(value))
        except ValueError as error:
            raise ValueError(
                "p256dh must be a P-256 public key in base64url"
            ) from error
        return value

    @field_validator("auth")
    @classmethod
    def _is_a_secret(cls, value: str) -> str:
        try:
            size = len(unb64(value))
        except ValueError as error:
            raise ValueError("auth must be base64url") from error
        if size != _AUTH_SIZE:
            raise ValueError(f"auth must be {_AUTH_SIZE} octets, not {size}")
        return value


class PushSubscriptionSchema(BaseModel):
    """A browser's subscription, as its `PushSubscription.toJSON()` gives it;
    its `expirationTime` is not read."""

    endpoint: str = Field(
        description="The push service's URL for the browser, unique to it",
        examples=["https://push.example.com/send/c9e2…"],
    )
    keys: PushSubscriptionKeysSchema

    @field_validator("endpoint")
    @classmethod
    def _is_an_address(cls, endpoint: str) -> str:
        return _address(endpoint)


class PushEndpointQuerySchema(BaseModel):
    """The browser's subscription to delete, by its endpoint."""

    endpoint: str = Field(
        description="The endpoint of the browser's subscription",
        examples=["https://push.example.com/send/c9e2…"],
    )

    @field_validator("endpoint")
    @classmethod
    def _is_an_address(cls, endpoint: str) -> str:
        return _address(endpoint)


def _address(endpoint: str) -> str:
    try:
        parts = urlsplit(endpoint)
        absolute = parts.scheme in {"http", "https"} and bool(parts.hostname)
    except ValueError:
        absolute = False
    if not absolute:
        raise ValueError("endpoint must be an absolute http or https URL")
    return endpoint
