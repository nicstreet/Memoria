"""
Default subject categories and values for the EXIF Subject field.

The live list is stored in ui_settings.json under "subject_categories".
Call get_categories() / get_flat() for the current live list.
The module-level SUBJECT_CATEGORIES / ALL_SUBJECTS are kept for
backwards compatibility but reflect the list at import time.
"""

from __future__ import annotations

_BUILTIN: list[tuple[str, list[str]]] = [
    ("Life Milestones", [
        "Births & Infancy",
        "Coming of Age",
        "Graduations",
        "Weddings & Romance",
        "Career & Achievements",
    ]),
    ("Annual Celebrations", [
        "Holidays",
        "Birthdays",
        "Seasonal Events",
    ]),
    ("Family Gatherings & Scenarios", [
        "Reunions",
        "Casual Visits",
        "Daily Life",
        "Portraits",
    ]),
    ("Travel & Leisure", [
        "Vacations",
        "Day Trips",
        "Outdoor Activities",
        "Sports & Hobbies",
    ]),
    ("Homes & Places", [
        "Residences",
        "Schools & Workplaces",
        "Ancestral Places",
    ]),
    ("Pets & Animals", [
        "Family Pets",
        "Animal Encounters",
    ]),
    ("Outliers & Special Collections", [
        "Mystery Photos",
        "Document Scans",
        "Heirlooms & Objects",
        "Sad Milestones",
        "Accidental/Technical",
        "Historical Ephemera",
    ]),
]


def get_categories() -> list[tuple[str, list[str]]]:
    """Return live subject categories (from settings, or built-in defaults)."""
    try:
        from memoria.ui.settings_store import load
        data = load().get("subject_categories")
        if data:
            return [(d["category"], list(d["subjects"])) for d in data]
    except Exception:
        pass
    return [(_c, list(_s)) for _c, _s in _BUILTIN]


def get_flat() -> list[str]:
    """Flat list of all subjects — used by QCompleter."""
    return [s for _, subs in get_categories() for s in subs]


def save_categories(cats: list[tuple[str, list[str]]]) -> None:
    """Persist updated subject categories to settings."""
    from memoria.ui.settings_store import load, save
    s = load()
    s["subject_categories"] = [
        {"category": cat, "subjects": list(subs)}
        for cat, subs in cats
    ]
    save(s)


# Module-level aliases — evaluated at import time (fine for initial load)
SUBJECT_CATEGORIES: list[tuple[str, list[str]]] = get_categories()
ALL_SUBJECTS: list[str] = get_flat()
