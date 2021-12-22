"""Executable script for managing input and the Schedule class.

"""

from ta_scheduler import Schedules
from ta_scheduler import Assignee
from ta_scheduler import Section
import argparse

def ta_sched():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "filename",
        help="Name of CSV file")
    args = parser.parse_args()

