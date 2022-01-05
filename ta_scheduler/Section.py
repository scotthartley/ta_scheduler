class Section:
    """Defines the section class.
    """

    def __init__(
            self,
            course_name: str,
            section_name: str,
            quota: float = 0,
            value: float = 1):
        self.course_name = course_name
        self.section_name = section_name
        self.name = course_name + " (" + section_name + ")"
        self.quota = float(quota)
        self.value = float(value)

