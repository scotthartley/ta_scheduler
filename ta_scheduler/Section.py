class Section:
    """Defines the section class.
    """

    def __init__(
            self,
            name: str,
            quota: int = 0):
        self.name = name
        self.quota = quota

