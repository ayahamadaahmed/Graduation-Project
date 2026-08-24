from time import perf_counter

from sqlalchemy import text

from app.db.session import SessionLocal


def test_connection(number: int) -> None:
    started = perf_counter()

    db = SessionLocal()

    try:
        result = db.execute(
            text("SELECT 1")
        ).scalar()

        elapsed = perf_counter() - started

        print(
            f"DB connection {number}: "
            f"{elapsed:.2f}s - result={result}"
        )

    finally:
        db.close()


if __name__ == "__main__":
    test_connection(1)
    test_connection(2)
    test_connection(3)