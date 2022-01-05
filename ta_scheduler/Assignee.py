from ta_scheduler import Section

class Assignee:
    """An assignee (person to be assigned to sections). Has a name,
    target load, and priorities by section.

    """
    def __init__(
            self,
            name: str,
            exp: str,
            target_load: float = 0):
        self.name = name
        self.exp = exp
        self.target_load = float(target_load)
        self.section_priorities = []


    def add_section_priority(self, new_section: Section, priority: str):
        self.section_priorities.append(
                {'sec': new_section,
                 'priority': float(priority) if priority else None})

    def section_priority(self, section: Section):
        for n in self.section_priorities:
            if n['sec'] == section:
                return n['priority']
        return None

