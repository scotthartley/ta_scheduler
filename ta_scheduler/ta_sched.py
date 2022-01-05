"""Executable script for managing input and the Schedule class.

    Input is a csv file of the following format:
    - Row 1: Course names (must match for identical courses)
    - Row 2: Course section names
    - Row 3: Course TA quotas (number of people)
    - Row 4: Course section values (credit that TAs get for assignment)
    - Remaining rows are TAs in following format:
        - Col 1: Name
        - Col 2: "i" (inexperienced), "n" (neutral), or "e" (experienced)
        - Col 3: Total load (sum of section values)
        - Remaining columns give scores for particular assignments.
          Leave blank (not 0) if TA is unavailable.

"""

from ta_scheduler import Schedules
from ta_scheduler import Assignee
from ta_scheduler import Section
import argparse
import csv

CSV_ENC = "utf-8-sig"


def ta_sched():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "filename",
        help="Name of CSV file")
    parser.add_argument(
        "-sp", "--split_penalty",
        help="Penalty to apply to split assignments",
        type=float, default=5.0)
    parser.add_argument(
        "-mb", "--match_bonus",
        help="Bonus to apply to experienced/inexperienced combinations",
        type=float, default=5.0)
    parser.add_argument(
        "-m", "--max_assignments",
        help="Maximum number of assignments to consider per person",
        type=int, default=3)
    args = parser.parse_args()

    assignees = []
    sections = []

    with open(args.filename, mode='r', encoding=CSV_ENC) as file:
        reader = csv.reader(file)
        row_number = 0
        for row in reader:
            if row_number == 0:
                course_names = [x for x in row if x]
            elif row_number == 1:
                section_names = [x for x in row if x]
            elif row_number == 2:
                section_quotas = [x for x in row if x]
            elif row_number == 3:
                section_values = [x for x in row if x]
                if not (len(course_names)
                        == len(section_names)
                        == len(section_quotas)
                        == len(section_values)):
                    raise Exception("Course names, section names, quotas, and values do not match!")
                for n in range(len(section_names)):
                    sections.append(
                            Section(course_name=course_names[n],
                                    section_name=section_names[n],
                                    quota=section_quotas[n],
                                    value=section_values[n]))
            else:
                new_assignee = Assignee(name=row[0], exp=row[1], target_load=row[2])
                priorities = row[3:]
                for n in range(len(priorities)):
                    new_assignee.add_section_priority(sections[n], priorities[n])
                assignees.append(new_assignee)
            row_number += 1

    schedules = Schedules(assignees, sections, args.split_penalty,
            args.match_bonus, args.max_assignments)
    print(schedules.dump())