from rest_framework.throttling import AnonRateThrottle


class RegisterThrottle(AnonRateThrottle):
    """Strict throttle for registration endpoint"""

    scope = "register"


class LoginThrottle(AnonRateThrottle):
    """Throttle for login endpoint"""

    scope = "login"


class TokenRefreshThrottle(AnonRateThrottle):
    """Throttle for token refresh endpoint"""

    scope = "token_refresh"
