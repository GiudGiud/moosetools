#* This file is part of the MOOSE framework
#* https://www.mooseframework.org
#*
#* All rights reserved, see COPYRIGHT for full restrictions
#* https://github.com/idaholab/moose/blob/master/COPYRIGHT
#*
#* Licensed under LGPL 2.1, please see LICENSE for details
#* https://www.gnu.org/licenses/lgpl-2.1.html

from moosetools.testharness.testers.FileTester import FileTester
from moosetools.testharness import util
import os

class CSVDiff(FileTester):

    @staticmethod
    def validParams():
        params = FileTester.validParams()
        params.add('csvdiff', vtype=str, array=True, doc="A list of files to run CSVDiff on.")
        params.add('override_columns', array=True, vtype=str, doc="A list of variable names to customize the CSVDiff tolerances.")
        params.add('override_rel_err',  array=True, doc="A list of customized relative error tolerances.")
        params.add('override_abs_zero',  array=True, doc="A list of customized absolute zero tolerances.")
        params.addParam('comparison_file', "Use supplied custom comparison config file.")
        #params.addParam('rel_err', "A customized relative error tolerances.")
        #params.addParam('abs_zero', "A customized relative error tolerances.")

        return params

    def __init__(self, *args, **kwargs):
        FileTester.__init__(self, *args, **kwargs)

    def getOutputFiles(self):
        return self.specs['csvdiff']

    # Check that override parameter lists are the same length
    def checkRunnable(self, options):
        #if (((self.specs['override_columns'] is not None) != len(self.specs['override_rel_err']))
        #or ((self.specs['override_columns'] is not None) != len(self.specs['override_abs_zero']))
        #or ((self.specs['override_rel_err'] is not None) != len(self.specs['override_abs_zero']))):
        #   self.setStatus(self.fail, 'Override inputs not the same length')
        #   return False
        return FileTester.checkRunnable(self, options)

    def processResultsCommand(self, moose_dir, options):
        commands = []

        for file in self.specs['csvdiff']:
            csvdiff = [os.path.join(self.specs['moose_python_dir'], 'mooseutils', 'csvdiff.py')]

            # Due to required positional nargs with the ability to support custom positional args (--argument), we need to specify the required ones first
            csvdiff.append(os.path.join(self.getTestDir(), self.specs['gold_dir'], file) + ' ' + os.path.join(self.getTestDir(), file))

            if self.specs.isValid('rel_err'):
                csvdiff.append('--relative-tolerance %s' % (self.specs['rel_err']))

            if self.specs.isValid('abs_zero'):
                csvdiff.append('--abs-zero %s' % (self.specs['abs_zero']))

            if self.specs.isValid('comparison_file'):
                comparison_file = os.path.join(self.getTestDir(), self.specs['comparison_file'])
                if os.path.exists(comparison_file):
                    csvdiff.append('--comparison-file %s' % (comparison_file))
                else:
                    self.setStatus(self.fail, 'MISSING COMPARISON FILE')
                    return commands

            if self.specs.isValid('override_columns'):
                csvdiff.append('--custom-columns %s' % (' '.join(self.specs['override_columns'])))

            if self.specs.isValid('override_rel_err'):
                csvdiff.append('--custom-rel-err %s' % (' '.join(self.specs['override_rel_err'])))

            if self.specs.isValid('override_abs_zero'):
                csvdiff.append('--custom-abs-zero %s' % (' '.join(self.specs['override_abs_zero'])))

            commands.append(' '.join(csvdiff))

        return commands

    def processResults(self, moose_dir, options, output):
        output += FileTester.processResults(self, moose_dir, options, output)

        if self.isFail() or self.specs['skip_checks']:
            return output

        # Don't Run CSVDiff on Scaled Tests
        if options.scaling and self.specs['scale_refine']:
            return output

        # Make sure that all of the Exodiff files are actually available
        for file in self.specs['csvdiff']:
            if not os.path.exists(os.path.join(self.getTestDir(), self.specs['gold_dir'], file)):
                output += "File Not Found: " + os.path.join(self.getTestDir(), self.specs['gold_dir'], file)
                self.setStatus(self.fail, 'MISSING GOLD FILE')
                break

        if not self.isFail():
            # Retrieve the commands
            commands = self.processResultsCommand(moose_dir, options)

            for command in commands:
                exo_output = util.runCommand(command)
                output += 'Running csvdiff: ' + command + '\n' + exo_output
                if not "Files are the same" in exo_output:
                    self.setStatus(self.diff, 'CSVDIFF')
                    break

        return output
