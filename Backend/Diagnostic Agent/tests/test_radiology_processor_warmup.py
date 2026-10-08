from src.diagnostics.radiology.radiology_processor import (
    RadiologyProcessor,
)


class FakeModel:

    def __init__(
        self,
        latency_ms: float,
    ) -> None:
        self.latency_ms = latency_ms
        self.calls = 0

    def warm_up(
        self,
    ) -> float:
        self.calls += 1
        return self.latency_ms


def test_warm_up_calls_each_model_once():

    chest = FakeModel(
        101.0
    )

    brain = FakeModel(
        202.0
    )

    kidney = FakeModel(
        303.0
    )

    processor = RadiologyProcessor(
        chest_xray_model=chest,
        brain_mri_model=brain,
        kidney_ct_model=kidney,
    )

    timings = (
        processor.warm_up()
    )

    assert chest.calls == 1
    assert brain.calls == 1
    assert kidney.calls == 1

    assert timings == {
        "chest_xray": 101.0,
        "brain_mri": 202.0,
        "kidney_ct": 303.0,
    }


def test_warm_up_returns_float_timings():

    processor = RadiologyProcessor(
        chest_xray_model=(
            FakeModel(1)
        ),
        brain_mri_model=(
            FakeModel(2)
        ),
        kidney_ct_model=(
            FakeModel(3)
        ),
    )

    timings = (
        processor.warm_up()
    )

    assert all(
        isinstance(
            value,
            float,
        )
        for value
        in timings.values()
    )