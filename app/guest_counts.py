"""Invitation membership comes only from names maintained by the couple."""


def invitation_names(name):
    return [' '.join(part.split()) for part in (name or '').split('&') if part.strip()]
