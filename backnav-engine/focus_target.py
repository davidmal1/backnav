from dataclasses import dataclass


@dataclass(frozen=True)
class FocusTarget:
    """
    A single navigable destination.

    This represents one place the user can return to.
    """

    id: str
    app: str
    title: str
