"""Executable script for managing input and the Schedule class.

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
                new_assignee = Assignee(name=row[0], target_load=row[1])
                priorities = row[2:]
                for n in range(len(priorities)):
                    new_assignee.add_section_priority(sections[n], priorities[n])
                assignees.append(new_assignee)
            row_number += 1

    schedules = Schedules(assignees, sections)
    schedules.dump()