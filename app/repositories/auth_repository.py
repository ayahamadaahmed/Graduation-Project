from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import (
    ProviderMembership,
    UserAccount,
)
from app.models.doctor import Doctor


class AuthRepository:

    def __init__(
        self,
        session: Session,
    ) -> None:

        self.session = session

    # ========================================================
    # USER ACCOUNT
    # ========================================================

    def get_user_by_email(
        self,
        *,
        email: str,
    ) -> UserAccount | None:

        statement = (
            select(
                UserAccount
            )
            .where(
                UserAccount.email == email
            )
        )

        return self.session.scalar(
            statement
        )

    def add_user(
        self,
        user: UserAccount,
    ) -> UserAccount:

        self.session.add(
            user
        )

        self.session.flush()

        return user

    def get_active_membership(
        self,
        *,
        user_id: UUID,
        provider_id: UUID,
    ) -> ProviderMembership | None:

        statement = (
            select(
                ProviderMembership
            )
            .where(
                ProviderMembership.user_id
                == user_id,

                ProviderMembership.provider_id
                == provider_id,

                ProviderMembership.is_active
                == 1,
            )
        )

        return self.session.scalar(
            statement
        )

    # ========================================================
    # PROVIDER MEMBERSHIP
    # ========================================================

    def add_membership(
        self,
        membership: ProviderMembership,
    ) -> ProviderMembership:

        self.session.add(
            membership
        )

        self.session.flush()

        return membership

    # ========================================================
    # DOCTOR / PROVIDER SECURITY BOUNDARY
    # ========================================================

    def doctor_belongs_to_provider(
        self,
        *,
        provider_id: UUID,
        doctor_id: UUID,
    ) -> bool:

        statement = (
            select(
                Doctor.id
            )
            .where(
                Doctor.id == doctor_id,
                Doctor.provider_id == provider_id,
                Doctor.is_active == 1,
            )
        )

        return (
            self.session.scalar(
                statement
            )
            is not None
        )

    def get_active_user_by_id(
        self,
        *,
        user_id: UUID,
    ) -> UserAccount | None:

        statement = (
            select(
                UserAccount
            )
            .where(
                UserAccount.id == user_id,
                UserAccount.is_active == 1,
            )
        )

        return self.session.scalar(
            statement
        )


    def get_active_membership_by_identity(
        self,
        *,
        membership_id: UUID,
        user_id: UUID,
        provider_id: UUID,
    ) -> ProviderMembership | None:

        statement = (
            select(
                ProviderMembership
            )
            .where(
                ProviderMembership.id
                == membership_id,

                ProviderMembership.user_id
                == user_id,

                ProviderMembership.provider_id
                == provider_id,

                ProviderMembership.is_active
                == 1,
            )
        )

        return self.session.scalar(
            statement
        )