class IdempotencyError(
    Exception
):
    pass


class IdempotencyConflictError(
    IdempotencyError
):
    """
    Same idempotency key was used
    with a different request payload.
    """

    pass


class IdempotencyInProgressError(
    IdempotencyError
):
    """
    Another request currently owns
    this idempotency operation.
    """

    pass