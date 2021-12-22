class Section:
    """Defines the section class.
    """

    def __init__(
            self,
            name: str,
            total_assignments: int = 0):
        self.name = name
        self.total_assignments = total_assignments
