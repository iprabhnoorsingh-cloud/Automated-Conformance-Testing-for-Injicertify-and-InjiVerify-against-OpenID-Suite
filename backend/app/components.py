"""Catalog of selectable MOSIP/Inji components.

This is a configuration catalog only — it does not imply these components
are actually reachable or under test yet. Add new entries here as they
become available; nothing else needs to change to support a new component.
"""

ALLOWED_COMPONENTS: dict[str, str] = {
    "inji-certify": "Inji Certify",
    "inji-verify": "Inji Verify",
}
