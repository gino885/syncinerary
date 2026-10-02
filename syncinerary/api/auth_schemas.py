"""Strict credential inputs; account responses never contain credential fields."""
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{8}$")]


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.casefold()


class RegisterRequest(EmailRequest):
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    password: Password


class SignInRequest(EmailRequest):
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class CodeRequest(EmailRequest):
    code: Code
    password: Password


class SocialSignInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_token: SecretStr
    nonce: Annotated[str, StringConstraints(min_length=32, max_length=128)]
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    authorization_code: SecretStr | None = None

    @field_validator("id_token", "authorization_code")
    @classmethod
    def bounded_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        if not 1 <= len(value.get_secret_value()) <= 16384:
            raise ValueError("Invalid identity token")
        return value


class DeleteAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr | None = None
    social_identity: SocialSignInRequest | None = None
    confirmation: Literal["DELETE"]

    @field_validator("current_password")
    @classmethod
    def validate_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        length = len(value.get_secret_value())
        if length < 8 or length > 128:
            raise ValueError("Password length is invalid")
        return value

    @model_validator(mode="after")
    def exactly_one_proof(self):
        if (self.current_password is None) == (self.social_identity is None):
            raise ValueError("Confirm your identity with your account's sign-in method")
        return self
