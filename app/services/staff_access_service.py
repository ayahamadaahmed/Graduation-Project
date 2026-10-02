from uuid import UUID, uuid4

from fastapi import (
    HTTPException,
    status,
)
from sqlalchemy.exc import (
    IntegrityError,
    SQLAlchemyError,
)

from app.models.auth import (
    ProviderMembership,
    UserAccount,
)
from app.repositories.auth_repository import (
    AuthRepository,
)
from app.security.passwords import (
    hash_password,
    verify_password,
)

ALLOWED_STAFF_ROLES = {
    "provider_admin",
    "doctor",
    "receptionist",
    "lab_staff",
}


class StaffAccessService:

    def __init__(
        self,
        repository: AuthRepository,
    ) -> None:

        self.repository = repository

    # ========================================================
    # MEMBERSHIP VALIDATION
    # ========================================================

    def validate_membership_assignment(
        self,
        *,
        provider_id: UUID,
        role: str,
        doctor_id: UUID | None,
    ) -> None:

        if role not in ALLOWED_STAFF_ROLES:

            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail={
                    "code": "INVALID_STAFF_ROLE",
                    "message": (
                        "The requested staff role "
                        "is not supported."
                    ),
                },
            )

        # ----------------------------------------------------
        # Doctor membership
        # ----------------------------------------------------

        if role == "doctor":

            if doctor_id is None:

                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_422_UNPROCESSABLE_ENTITY
                    ),
                    detail={
                        "code":
                            "DOCTOR_ID_REQUIRED",

                        "message": (
                            "doctor_id is required "
                            "for doctor memberships."
                        ),
                    },
                )

            belongs = (
                self.repository
                .doctor_belongs_to_provider(
                    provider_id=provider_id,
                    doctor_id=doctor_id,
                )
            )

            if not belongs:

                raise HTTPException(
                    status_code=(
                        status.HTTP_404_NOT_FOUND
                    ),
                    detail={
                        "code": (
                            "DOCTOR_NOT_FOUND_FOR_PROVIDER"
                        ),
                        "message": (
                            "The doctor does not "
                            "belong to this provider."
                        ),
                    },
                )

            return

        # ----------------------------------------------------
        # Non-doctor membership
        # ----------------------------------------------------

        if doctor_id is not None:

            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail={
                    "code":
                        "DOCTOR_ID_NOT_ALLOWED",

                    "message": (
                        "doctor_id is only valid "
                        "for doctor memberships."
                    ),
                },
            )

    # ========================================================
    # CREATE STAFF ACCOUNT
    # ========================================================

    def create_staff_account(
        self,
        *,
        provider_id: UUID,
        email: str,
        password: str,
        role: str,
        doctor_id: UUID | None = None,
    ) -> tuple[
        UserAccount,
        ProviderMembership,
    ]:

        session = self.repository.session

        normalized_email = (
            email.strip().lower()
        )

        if not normalized_email:

            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail={
                    "code": "EMAIL_REQUIRED",
                    "message": (
                        "A staff email is required."
                    ),
                },
            )

        try:

            # ================================================
            # 1. Duplicate account check
            # ================================================

            existing_user = (
                self.repository
                .get_user_by_email(
                    email=normalized_email,
                )
            )

            if existing_user is not None:

                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code":
                            "STAFF_ACCOUNT_EXISTS",

                        "message": (
                            "A staff account with "
                            "this email already exists."
                        ),
                    },
                )

            # ================================================
            # 2. Tenant / role / doctor validation
            # ================================================

            self.validate_membership_assignment(
                provider_id=provider_id,
                role=role,
                doctor_id=doctor_id,
            )

            # ================================================
            # 3. Password hashing
            # ================================================

            try:

                password_hash = (
                    hash_password(
                        password
                    )
                )

            except (
                ValueError,
                TypeError,
            ) as exc:

                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_422_UNPROCESSABLE_ENTITY
                    ),
                    detail={
                        "code":
                            "INVALID_PASSWORD",

                        "message": (
                            "The supplied password "
                            "is not valid."
                        ),
                    },
                ) from exc

            # ================================================
            # 4. Create global account
            # ================================================

            user = UserAccount(
                id=uuid4(),
                email=normalized_email,
                password_hash=password_hash,
                is_active=True,
            )

            self.repository.add_user(
                user
            )

            # ================================================
            # 5. Create provider membership
            # ================================================

            membership = ProviderMembership(
                id=uuid4(),
                user_id=user.id,
                provider_id=provider_id,
                role=role,
                doctor_id=doctor_id,
                is_active=True,
            )

            self.repository.add_membership(
                membership
            )

            # ================================================
            # 6. ONE atomic commit
            # ================================================

            session.commit()

            session.refresh(
                user
            )

            session.refresh(
                membership
            )

            return (
                user,
                membership,
            )

        except HTTPException:

            session.rollback()
            raise

        except IntegrityError as exc:

            session.rollback()

            raise HTTPException(
                status_code=(
                    status.HTTP_409_CONFLICT
                ),
                detail={
                    "code":
                        "STAFF_ACCOUNT_CONFLICT",

                    "message": (
                        "The staff account could "
                        "not be created because "
                        "of conflicting data."
                    ),
                },
            ) from exc

        except SQLAlchemyError:

            session.rollback()
            raise

        except Exception:

            session.rollback()
            raise

    def authenticate_staff(
        self,
        *,
        provider_id: UUID,
        email: str,
        password: str,
    ) -> tuple[
        UserAccount,
        ProviderMembership,
    ]:

        normalized_email = (
            email.strip().lower()
        )

        # ========================================================
        # 1. Resolve global staff identity
        # ========================================================

        user = (
            self.repository
            .get_user_by_email(
                email=normalized_email,
            )
        )

        # Keep authentication failures generic.
        if (
            user is None
            or not user.is_active
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail={
                    "code":
                        "INVALID_CREDENTIALS",
                    "message": (
                        "Invalid email or password."
                    ),
                },
                headers={
                    "WWW-Authenticate":
                        "Bearer",
                },
            )

        # ========================================================
        # 2. Verify password
        # ========================================================

        if not verify_password(
            password,
            user.password_hash,
        ):

            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail={
                    "code":
                        "INVALID_CREDENTIALS",
                    "message": (
                        "Invalid email or password."
                    ),
                },
                headers={
                    "WWW-Authenticate":
                        "Bearer",
                },
            )

        # ========================================================
        # 3. Resolve provider authorization
        # ========================================================

        membership = (
            self.repository
            .get_active_membership(
                user_id=user.id,
                provider_id=provider_id,
            )
        )

        if membership is None:

            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail={
                    "code":
                        "STAFF_ACCESS_DENIED",
                    "message": (
                        "This staff account does not "
                        "have access to this provider."
                    ),
                },
            )

        return (
            user,
            membership,
        )    

    def resolve_current_staff(
        self,
        *,
        provider_id: UUID,
        user_id: UUID,
        membership_id: UUID,
        token_provider_id: UUID,
    ) -> tuple[
        UserAccount,
        ProviderMembership,
    ]:

        # ========================================================
        # 1. Token tenant must match requested tenant
        # ========================================================

        if token_provider_id != provider_id:

            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail={
                    "code":
                        "STAFF_TENANT_MISMATCH",

                    "message": (
                        "The access token does not "
                        "belong to this provider."
                    ),
                },
            )

        # ========================================================
        # 2. Staff account must still be active
        # ========================================================

        user = (
            self.repository
            .get_active_user_by_id(
                user_id=user_id,
            )
        )

        if user is None:

            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail={
                    "code":
                        "INVALID_STAFF_SESSION",

                    "message": (
                        "The staff session is no "
                        "longer valid."
                    ),
                },
                headers={
                    "WWW-Authenticate":
                        "Bearer",
                },
            )

        # ========================================================
        # 3. Membership must still be active and exact
        # ========================================================

        membership = (
            self.repository
            .get_active_membership_by_identity(
                membership_id=membership_id,
                user_id=user_id,
                provider_id=provider_id,
            )
        )

        if membership is None:

            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail={
                    "code":
                        "INVALID_STAFF_SESSION",

                    "message": (
                        "The staff session is no "
                        "longer valid."
                    ),
                },
                headers={
                    "WWW-Authenticate":
                        "Bearer",
                },
            )

        return (
            user,
            membership,
        )