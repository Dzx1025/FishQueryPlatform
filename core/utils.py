from datetime import date


def update_chat_usage(user):
    """
    Updates a user's chat usage count and checks quota.
    Returns True if user can chat, False if quota is exceeded.
    """
    # Reset counter if it's a new day
    today = date.today()
    if user.last_message_reset != today:
        user.messages_used_today = 0
        user.last_message_reset = today

    # Check quota and increment if allowed
    if user.messages_used_today < user.daily_message_quota:
        user.messages_used_today += 1
        user.save()
        return True
    return False
