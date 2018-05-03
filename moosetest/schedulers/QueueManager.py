#* This file is part of the MOOSE framework
#* https://www.mooseframework.org
#*
#* All rights reserved, see COPYRIGHT for full restrictions
#* https://github.com/idaholab/moose/blob/master/COPYRIGHT
#*
#* Licensed under LGPL 2.1, please see LICENSE for details
#* https://www.gnu.org/licenses/lgpl-2.1.html

import sys, os, json, shutil
from collections import namedtuple
from Scheduler import Scheduler

class QueueManager(Scheduler):
    """
    QueueManager is a Scheduler plugin responsible for allowing the testers to be scheduled via a
    third-party queue system (like PBS).

    The QueueManager works by intercepting and altering the statuses of all but one job contained
    in the group to a finished state. This affords us the behavior of only using the runner thread
    pool once per group (see augmentJobs).

    Using this one unmodified job, the spec file involved is noted, and instructs the derived
    scheduler how to launch this one single spec file (--spec-file), along with any supplied/allowable
    command line arguments (--re, --cli-args).

    The third-party queueing manager then executes `run_tests --spec-file /path/to/spec_file`.

    It is the results of this additional ./run_tests run, that is captured and presented to the user as
    the finished result of the test.
    """
    @staticmethod
    def validParams():
        params = Scheduler.validParams()
        return params

    def __init__(self, harness, params):
        Scheduler.__init__(self, harness, params)
        self.harness = harness
        self.options = self.harness.getOptions()
        self.__job_storage_file = self.harness.original_storage
        self.__clean_args = None

    def augmentJobs(self, Jobs):
        """
        Filter through incomming jobs and figure out if we are launching them
        or attempting to process finished results.
        """
        # Flatten the DAG. We want to easily iterate over all jobs produced by the spec file
        Jobs.removeAllDependencies()

        # Perform cleanup operations and return if thats what the user wants
        if self.options.queue_cleanup:
            self._cleanupFiles(Jobs)
            return

        # Create a namedtuple of frequently used information contained within Jobs, so we can
        # more easily pass this information among our methods
        job_list = Jobs.getJobs()
        if job_list:
            queue_data = namedtuple('JobData', ['jobs', 'job_dir', 'json_data', 'plugin'])
            job_data = queue_data(jobs=Jobs,
                                  job_dir=job_list[0].getTestDir(),
                                  json_data=self.options.results_storage,
                                  plugin=self.harness.scheduler.__class__.__name__)

            if self._isProcessReady(job_data):
                self._setJobStatus(job_data)

            elif self._isLaunchable(job_data):
                self._prepareJobs(job_data)

    def createQueueScript(self, job, template):
        """ Write the launch script to disc """
        # Get a list of prereq tests this test may have
        try:
            with open(self.params['queue_template'], 'r') as f:
                content = f.read()

                with open(template['launch_script'], 'w') as queue_script:

                    # Do all of the replacements for valid parameters
                    for key in template.keys():
                        if key.upper() in content:
                            content = content.replace('<' + key.upper() + '>', str(template[key]))

                    # Strip out parameters that were not supplied
                    for key in template.keys():
                        if key.upper() not in content:
                            content = content.replace('<' + key.upper() + '>', '')

                    queue_script.write(content)
        except IOError as e:
            print(e)
            sys.exit(1)

    def reserveSlots(self, job, j_lock):
        """
        Inherited method from the Scheduler to handle slot allocation.
        QueueManager does not need an allocation system, so this method simply returns True
        """
        return True

    def getBadArgs(self):
        """ Arguments which should be removed from the launch script invoking ./run_tests """
        return []

    def getBadKeyArgs(self):
        """ Key/Value arguments which should be removed from the launch script invoking ./run_tests """
        return []

    def getCores(self, job_data):
        """ iterate over Jobs and collect the maximum core requirement from the group of jobs which will run """
        slots = 1
        for job in [x for x in job_data.jobs.getJobs() if not x.isSkip()]:
            slots = max(slots, job.getSlots())

        return slots

    def getMaxTime(self, job_data):
        """ iterate over Jobs and increment the total allowable time needed to complete the entire group """
        total_time = 0
        for job in [x for x in job_data.jobs.getJobs() if not x.isSkip()]:
            tester = job.getTester()
            total_time += int(tester.getMaxTime())

        return total_time

    def addDirtyFiles(self, job, file_list=[]):
        """ append list of files which will be generated by derived scheduler """
        job_data = job.getMetaData()
        file_list.extend(job_data.get('QUEUE_FILES', []))
        job.addMetaData(QUEUE_FILES=file_list)

    def getDirtyFiles(self, job):
        """ return list of files not indigenous to the repository which was created by third party schedulers """
        dirty_files = []
        if self.options.results_storage and self.options.results_storage.get(job.getTestDir(), {}):
            dirty_files = self.options.results_storage[job.getTestDir()].get('QUEUE_FILES', [])
        return dirty_files

    def cleanAndModifyArgs(self):
        """
        Filter out any arguments that will otherwise break the TestHarness when launched _within_
        the third party queueing system (such as --pbs)
        """
        # return cached args if we have already produced clean args
        if not self.__clean_args:
            current_args = list(sys.argv[1:])

            # Ask derived schedulers for any additional args we should strip from sys.args
            bad_args = self.getBadArgs()
            bad_keyword_args = self.getBadKeyArgs()

            # Split keyword args so we can match/remove them (the key, and its value pair)
            key_value_args = [x for x in current_args if '=' in x]
            for arg in key_value_args:
                current_args.remove(arg)
                current_args.extend(arg.split('='))

            # Note: we are removing cli-args because we need to re-encapsulate them below
            bad_keyword_args.extend(['--spec-file', '-i', '--cli-args', '-j', '-l'])

            # remove the key=value pair argument
            for arg in bad_keyword_args:
                if arg in current_args:
                    key = current_args.index(arg)
                    del current_args[key:key+2]

            # Special: re-encapsulate --cli-args
            if self.options.cli_args:
                current_args.extend(['--cli-args', '"%s"' % self.options.cli_args])

            # remove any specified positional arguments
            for arg in bad_args:
                if arg in current_args:
                    current_args.remove(arg)

            self.__clean_args = current_args

        return self.__clean_args

    def getRunTestsCommand(self, job):
        """ return the command necessary to launch the TestHarness within the third party queue manager """

        # Build ['/path/to/run_tests', '-j', '#']
        command = [os.path.join(self.harness.run_tests_dir, 'run_tests'),
                   '-j', str(job.getMetaData().get('QUEUEING_NCPUS', 1) )]

        # get current sys.args we are allowed to include when we launch run_tests
        args = list(self.cleanAndModifyArgs())

        # Build [<args>, '--spec-file' ,/path/to/tests', '-o', '/path/to']
        args.extend(['--spec-file', os.path.join(job.getTestDir(), self.options.input_file_name),
                     '-o', job.getTestDir()])

        # Build [<command>, <args>]
        command.extend(args)

        # Add the second results file we should remove when performing cleanup operations
        self.addDirtyFiles(job, [os.path.join(job.getTestDir(), self.__job_storage_file)])

        return command

    def _isProcessReady(self, job_data):
        """
        Return bool on `run_tests --spec_file` submission results being available. Due to the
        way the TestHarness writes to this results file (when the TestHarness exits), this file
        when available, means every test contained therein is finished in some form or another.
        """
        # Immediate reason to return false (no session file)
        if not job_data.json_data:
            return False

        # job(s) were launched but results file does not yet exist (QUEUED)
        if (job_data.json_data.get(job_data.job_dir, {})
            and not os.path.exists(os.path.join(job_data.job_dir, self.__job_storage_file))):
            for job in job_data.jobs.getJobs():
                tester = job.getTester()
                if tester.isNoStatus():
                    tester.setStatus(tester.no_status, 'QUEUED')
                job.setStatus(job.finished)
            return False

        # job(s) were specifically silently skipped during initial launch
        if not job_data.json_data.get(job_data.job_dir, {}):
            self._finishAllJobs(job_data)
            return False

        # results file exists, but job was launched using a different scheduler
        if (job_data.json_data.get(job_data.job_dir, {})
            and not job_data.json_data[job_data.job_dir].get(job_data.plugin, {})):
            self._finishAllJobs(job_data)
            return False

        return True

    def _finishAllJobs(self, job_data):
        """ iterate over jobs and set their status to finished """
        for job in job_data.jobs.getJobs():
            job.setStatus(job.finished)

    def _isLaunchable(self, job_data):
        """ bool if jobs are ready to launch """
        # results file exists (set during scheduler plugin initialization), so do no launch again
        if job_data.json_data:
            return False

        return True

    def _prepareJobs(self, job_data):
        """
        Prepare jobs for launch.

        Grab an arbitrary job and record any necessary information the third party
        queueing systems requires for launch (walltime, ncpus, etc). Set all other
        jobs to a finished state. The arbitrary job selected will be the only job
        which enters the runner thread pool, and executes the commands neccessary
        for job submission.
        """
        job_list = job_data.jobs.getJobs()

        # Clear any caveats set (except skips). As they do not apply during job submission
        for job in [x for x in job_list if not x.isSkip()]:
            job.clearCaveats()

        if job_list:
            launchable_jobs = [x for x in job_list if not x.isFinished()]
            if launchable_jobs:
                executor_job = job_list.pop(job_list.index(launchable_jobs.pop(0)))

                executor_job.addMetaData(QUEUEING=job_data.plugin,
                                         QUEUEING_NCPUS=self.getCores(job_data),
                                         QUEUEING_MAXTIME=self.getMaxTime(job_data))

                for job in launchable_jobs:
                    tester = job.getTester()
                    # Preserves silent, skipped, deleted tests
                    if tester.isNoStatus():
                        tester.setStatus(tester.no_status, 'LAUNCHING')
                    job.setStatus(job.finished)

    def _setJobStatus(self, job_data):
        """
        Read the json results file for the finished submitted job group, and match our
        job statuses with the results found therein.
        """
        job_list = job_data.jobs.getJobs()
        if job_list:
            testdir_json = os.path.join(job_data.job_dir, self.__job_storage_file)

            with open(testdir_json, 'r') as f:
                try:
                    results = json.load(f)
                except ValueError:
                    print('Unable to parse json file: %s' (testdir_json))
                    sys.exit(1)

            group_results = results[job_data.job_dir]

            # Continue to store previous third-party queueing data
            job_list[0].addMetaData(**{job_data.plugin : self.options.results_storage[job_data.job_dir][job_data.plugin]})

            for job in job_list:
                # No matter what the case may be, this job is finished.
                job.setStatus(job.finished)

                tester = job.getTester()

                # # Perhaps the user is silencing this job (--re, --failed-tests, etc)
                if tester.isSilent():
                    continue

                if group_results.get(job.getTestName(), {}):
                    job_results = group_results[job.getTestName()]

                    # Instance a compatible status and align our status accordingly
                    test_status = tester.createStatus()
                    result_status = job_results['STATUS'].encode('ascii', 'ignore')
                    result_color = job_results['COLOR'].encode('ascii', 'ignore')
                    new_status = test_status(status=result_status, color=result_color)
                    tester.setStatus(new_status)

                    # Recover useful job information from results storage
                    job.setPreviousTime(job_results['TIMING'])
                    if job_results['CAVEATS']:
                        tester.addCaveats(' '.join(job_results['CAVEATS']))

                    job.setOutput(job_results['OUTPUT'])

                # This is a new tester, which was not a part of original launch
                else:
                    tester.addCaveats('not originally launched')
                    tester.setStatus(tester.skip)

    def _cleanupFiles(self, Jobs):
        """ Silence all Jobs and perform cleanup operations """
        job_list = Jobs.getJobs()
        # Set each tester to be silent
        for job in job_list:
            tester = job.getTester()
            tester.setStatus(tester.silent)
            job.setStatus(job.finished)
        # Delete files generated by a job
        if job_list:
            for dirty_file in self.getDirtyFiles(job_list[0]):
                # Safty check. Any generated queue file/dir should only exist in the tester directory
                if os.path.dirname(dirty_file) == job_list[0].getTestDir():
                    try:
                        if os.path.isdir(dirty_file):
                            shutil.rmtree(dirty_file)
                        else:
                            os.remove(dirty_file)
                    except OSError:
                        pass
