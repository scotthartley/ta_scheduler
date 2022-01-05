"""Defines the Schedules class.

"""

import itertools

class Schedules:
    """Class that organizes sets of assignees and sections into
    schedules, which are lists of tuples of the form (assignee,
    section).

    """
    def __init__(self,
                 assignees: list,
                 sections: list,
                 split_penalty: float,
                 match_bonus: float,
                 max_assignments: int):

        self.assignees = assignees
        self.sections = sections
        self.split_penalty = split_penalty
        self.match_bonus = match_bonus
        self.max_assignments = max_assignments

        # For convenience, dictionaries of target loads by assignee and
        # target quotas by section.
        self.target_loads = {a:a.target_load for a in assignees}
        self.target_quotas = {s:s.quota for s in sections}

        self.all_schedules, _ = self._build_schedules(
                assignees=self.assignees,
                quotas=self.target_quotas)
        self.scored_schedules = self._score()


    def _build_schedules(self,
                         assignees: list,
                         quotas: dict) -> list:
        """Recursive function that builds out the schedule. Takes a list
        of assignees remaining to be assigned and quotas for sections
        that need to be filled.

        """
        total_quotas = sum([quotas[x] for x in quotas])

        # We are done if there are no assignees.
        if not assignees and total_quotas == 0:
            overall_success = True
            return ([], overall_success)
        # If we no longer have assignees but quotas are unsatisfied, we
        # have failed.
        elif not assignees:
            overall_success = False
            return ([], overall_success)

        # Choose the first assignee as the person to assign to sections.
        current_assignee = assignees[0]
        # Generate all possible assignments, taking into account whether
        # the section priorities are None.
        possible_assignments = [(current_assignee, s) for s in self.sections
                if current_assignee.section_priority(s) != None]

        # Generate a list of all possible combinations of assignments
        # for the assignee.
        all_assignment_combos = []
        for n in range(self.max_assignments):
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
                        assignees=remaining_assignees,
                        quotas=new_quotas)
                # Overall success if any of the combinations work out.
                if sub_schedules and success:
                    for s in sub_schedules:
                        overall_success = True
                        schedules.append(s + combo)
                elif success:
                    overall_success = True
                    schedules.append(combo)

        return (schedules, overall_success)


    def _score(self) -> list:
        """Returns a list of schedules sorted by their scores, applying
        the input priorities (from the Assignee class) and the split
        penalty.

        """
        scored_schedules = []

        for schedule in self.all_schedules:
            points = 0
            assignee_courses = {}
            section_assignees = {}
            for assignment in schedule:
                assignee = assignment[0]
                section = assignment[1]
                points += assignee.section_priority(section)

                if assignee not in assignee_courses:
                    assignee_courses[assignee] = []
                assignee_courses[assignee].append(section.course_name)

                if section not in section_assignees:
                    section_assignees[section] = []
                section_assignees[section].append(assignee)

            for a in assignee_courses:
                # Set removes duplicates from the list.
                points -= ((len(set(assignee_courses[a]))-1)
                        * self.split_penalty)

            # Count numbers of experienced and inexperienced TAs.
            # Apply bonus for pairing them.
            for s in section_assignees:
                num_exp = 0
                num_inexp = 0
                for a in section_assignees[s]:
                    if a.exp == 'e':
                        num_exp += 1
                    if a.exp == 'i':
                        num_inexp += 1
                points += min(num_exp, num_inexp) * self.match_bonus

            scored_schedules.append({'points':points, 'schedule':schedule})

        scored_schedules = sorted(scored_schedules,
                                  key = lambda x: x['points'],
                                  reverse=True)

        return scored_schedules


    def dump(self) -> str:
        """Return a string of formatted output.

        """
        output = f"Total schedules: {len(self.all_schedules)}\n\n"
        for x in self.scored_schedules:

            sch_by_assignee = {}
            sch_by_section = {}
            for assignment in x['schedule']:
                name = assignment[0].name
                section = assignment[1].name
                if name not in sch_by_assignee:
                    sch_by_assignee[name] = []
                sch_by_assignee[name].append(section)
                if section not in sch_by_section:
                    sch_by_section[section] = []
                sch_by_section[section].append(name)
            output += f"Points: {x['points']}\n"
            for sec in sch_by_section:
                output += f"{sec}: {', '.join(sch_by_section[sec])}\n"
            output += "\n"
            for name in sch_by_assignee:
                output += f"{name}: {', '.join(sch_by_assignee[name])}\n"
            output += "\n\n"
        return output
