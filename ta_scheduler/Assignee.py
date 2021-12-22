from ta_scheduler import Section

class Assignee:
    def __init__(
            self,
            name: str,
            total_assignments: int = 0):
        self.name = name
        self.total_assignments = total_assignments
        self.sections = []


    def add_section(self, new_section: Section, priority: int):
        self.sections.append({'sec': new_section, 'priority': priority})
