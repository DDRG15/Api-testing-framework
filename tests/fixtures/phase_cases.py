"""Intentionally failing subprocess probes; excluded from ordinary test discovery."""
import pytest

attempts = 0


@pytest.mark.flaky(reruns=1)
def test_recovers():
    global attempts
    attempts += 1
    assert attempts > 1


@pytest.fixture
def broken_setup():
    raise RuntimeError("controlled setup failure")


def test_setup_failure(broken_setup):
    pass


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("controlled teardown failure")


def test_teardown_failure(broken_teardown):
    pass
