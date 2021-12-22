from ta_scheduler import Section

class Assignee:
    def __init__(
            self,
            name: str,
            quota: int = 0):
        self.name = name
        self.quota = quota
        self.section_priorities = []


    def add_section_priority(self, new_section: Section, priority: int):
        self.section_priorities.append({'sec': new_section, 'priority': priority})
