from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class AnonymousUserRateThrottle(AnonRateThrottle):
    """Rate throttle for anonymous users"""
    rate = '15/day'


class AuthenticatedUserRateThrottle(UserRateThrottle):
    """Rate throttle for authenticated users"""
    # This throttle is not actually used for limiting
    # since we use the custom user model's can_send_message method
    rate = '30/day'
