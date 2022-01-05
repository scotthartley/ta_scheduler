"""Defines the Schedule class.

"""

# Maximum number of assignments an assignee can have.
MAX_ASSIGNMENTS = 3

import itertools

class Schedules:
    def __init__(self,
                 assignees: list,
                 sections: list):

        self.assignees = assignees
        self.sections = sections

        self.target_loads = {a:a.target_load for a in assignees}
        self.target_quotas = {s:s.quota for s in sections}

        self.all_schedules, _ = self._build_schedules(
                self.assignees, self.target_quotas)


    def _build_schedules(self, assignees, quotas) -> list:
        total_quotas = sum([quotas[x] for x in quotas])

        # We are done if there are no assignees.
        if not assignees and total_quotas == 0:
            overall_success = True
            return ([], overall_success)
        elif not assignees:
            overall_success = False
            return ([], overall_success)

        # Choose the first assignee as the person to assign to sections.
        current_assignee = assignees[0]
        # Generate all possible assignments, taking into account whether
        # the section priorities are None.
        possible_assignments = [(current_assignee, s) for s in self.sections
                if current_assignee.section_priority(s)]

        # Generate a list of all possible combinations of assignments
        # for the assignee.
        all_assignment_combos = []
        for n in range(MAX_ASSIGNMENTS):
            all_assignment_combos += list(itertools.combinations(
                    possible_assignments, n+1))

        # Work out which of these combinations actually satisfy the
        # person's assignment (i.e., the total load is their assigned
        # load).
        candidate_combos = []
        for combo in all_assignment_combos:
            acceptable = True
            for c in combo:
                if (c[1].value > self.target_loads[current_assignee]
                        or quotas[c[1]] == 0):
                    acceptable = False
            if acceptable:
                total_load = sum([c[1].value for c in combo])
                if total_load == self.target_loads[current_assignee]:
                    candidate_combos.append(combo)

        schedules = []
        overall_success = False
        # If there are no possible combinations then the search has
        # failed and do nothing. Otherwise, need to build up the rest of
        # the schedule.
        if candidate_combos:
            for combo in candidate_combos:
                remaining_assignees = assignees[1:]
                sections_used = [c[1] for c in combo]
                new_quotas = quotas.copy()
                for section in new_quotas:
                    if section in sections_used:
                        new_quotas[section] -= 1
                sub_schedules, success = self._build_schedules(
                        remaining_assignees, new_quotas)
                # Overall success if any of the combinations work out.
                if sub_schedules and success:
                    for s in sub_schedules:
                        overall_success = True
                        schedules.append(s + combo)
                elif success:
                    overall_success = True
                    schedules.append(combo)

        return (schedules, overall_success)


    def dump(self):
        print("Total schedules:", len(self.all_schedules), "\n")
        for x in self.all_schedules:
            for y in x:
                print(f"{y[0].name}, {y[1].name}")
            print()
