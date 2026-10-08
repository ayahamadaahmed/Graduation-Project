import asyncio

import src.api.app as app_module


class FakeRadiologyProcessor:

    def __init__(
        self,
    ) -> None:
        self.calls = 0

    def warm_up(
        self,
    ) -> dict[str, float]:
        self.calls += 1

        return {
            "chest_xray": 101.0,
            "brain_mri": 202.0,
            "kidney_ct": 303.0,
        }

def test_startup_warms_radiology_models(
    monkeypatch,
):

    fake_processor = FakeRadiologyProcessor()

    monkeypatch.setattr(
        app_module,
        "radiology_processor",
        fake_processor,
    )

    monkeypatch.setenv(
        "DIAGNOSTIC_RADIOLOGY_WARMUP_ENABLED",
        "1",
    )

    asyncio.run(
        app_module.warm_up_radiology_models()
    )

    assert fake_processor.calls == 1

    state = (
        app_module.app.state.radiology_warmup
    )

    assert state["enabled"] is True

    assert state["timings_ms"] == {
        "chest_xray": 101.0,
        "brain_mri": 202.0,
        "kidney_ct": 303.0,
    }

    assert state["total_ms"] >= 0.0



def test_startup_warmup_can_be_disabled(
    monkeypatch,
):

    fake_processor = FakeRadiologyProcessor()

    monkeypatch.setattr(
        app_module,
        "radiology_processor",
        fake_processor,
    )

    monkeypatch.setenv(
        "DIAGNOSTIC_RADIOLOGY_WARMUP_ENABLED",
        "0",
    )

    asyncio.run(
        app_module.warm_up_radiology_models()
    )

    assert fake_processor.calls == 0

    state = (
        app_module.app.state.radiology_warmup
    )

    assert state == {
        "enabled": False,
        "timings_ms": {},
        "total_ms": 0.0,
    }