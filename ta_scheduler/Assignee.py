from ta_scheduler import Section

class Assignee:
    def __init__(
            self,
            name: str,
            target_load: float = 0):
        self.name = name
        self.target_load = float(target_load)
        self.section_priorities = []


    def add_section_priority(self, new_section: Section, priority: int):
        self.section_priorities.append({'sec': new_section, 'priority': priority})

    def section_priority(self, section: Section):
        for n in self.section_priorities:
            if n['sec'] == section:
                return n['priority']
        return None

