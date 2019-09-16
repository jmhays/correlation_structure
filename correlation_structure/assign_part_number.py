"""Backs up files according to gmx conventions.
"""

import os, shutil
import re


class AssignPartNumber:
    def __init__(self, working_dir):
        self.working_dir = working_dir
        self.max_part_number = 0
        # Use gromacs log files to figure out the current part number
        for _, _, fnms in os.walk(self.working_dir):
            for fnm in fnms:
                regex = re.search("\d{4}", fnm)
                if regex:
                    part_num = int(regex.group(0))
                    if part_num > self.max_part_number:
                        self.max_part_number = part_num
    def assign_part_number(self, filename):
        if self.working_dir not in filename:
            filename = "{}/{}".format(self.working_dir, filename)

        new_filename = "{}.part{:04d}.{}".format(filename[:-4], self.max_part_number, filename[-3:])
        shutil.copy(filename, new_filename)
