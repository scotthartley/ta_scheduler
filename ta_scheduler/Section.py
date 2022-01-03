class Section:
    """Defines the section class.
    """

    def __init__(
            self,
            name: str,
            quota: float = 0,
            value: float = 1):
        self.name = name
        self.quota = quota
        self.value = value

