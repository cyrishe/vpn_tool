import pytest

from control_plane.errors import APIError
from control_plane.rate_limit import LoginLimiter


def test_login_limit_expires_and_isolates_addresses():
    now = [0]
    limiter = LoginLimiter(lambda: now[0])
    for _ in range(10):
        limiter.check("client-one")
    with pytest.raises(APIError) as error:
        limiter.check("client-one")
    assert error.value.status_code == 429
    limiter.check("client-two")
    now[0] = 61
    limiter.check("client-one")
