"""
Reserved usernames that must never be claimable by public signup.

Per PRD Chapter 3 sec 4: usernames must "not use reserved system names"
and must "not impersonate official platform accounts." This list is
intentionally small and easy to extend — it is not a moderation
blocklist, just system/brand-identity protection.
"""

RESERVED_USERNAMES: frozenset[str] = frozenset({
    "admin", "administrator", "root", "system", "support", "help",
    "api", "cartflow", "official", "staff", "moderator", "mod",
    "security", "billing", "payments", "info", "contact", "null",
    "undefined", "test", "cartflow_official", "cartflowafrica",
})
