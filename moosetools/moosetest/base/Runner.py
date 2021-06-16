#* This file is part of MOOSETOOLS repository
#* https://www.github.com/idaholab/moosetools
#*
#* All rights reserved, see COPYRIGHT for full restrictions
#* https://github.com/idaholab/moosetools/blob/main/COPYRIGHT
#*
#* Licensed under LGPL 2.1, please see LICENSE for details
#* https://www.gnu.org/licenses/lgpl-2.1.html

import os
from moosetools import mooseutils
from .MooseTestObject import MooseTestObject
from .Differ import Differ


def make_runner(cls, controllers=None, **kwargs):
    """
    Create a `Runner` object given the *cls* with the `validObjectParams` of the *controllers*.

    The *controllers* argument, if supplied, should be an iterable of `moosetest.base.Controller`
    objects. The parameters supplied in the static `validObjectParams` method of each controller are
    added as a sub-parameter to the `validParams` of the object being instatiated, using the
    parameter name given in the "prefix" parameter of the `Controller` object.

    For example, consider the `moosetest.controllers.EnvironmentController` object, which has a
    default prefix of "env" defined and a "platform" parameter defined in the `validObjectParams`
    static function. If an instance of this type is passed into this function a sub-parameter with
    the name "env" will added, which contains the "platform" parameter.  Hence, the `Runner` object
    will contain parameters relevant to the environment that can be set.

    The *\*\*kwargs* arguments are applied to the default parameters as done for the base
    `base.MooseObject` class. Implementing the following will demonstrate that the "platform"
    parameter can be set for the `Runner` object, using the "env" prefix.

    ```python
    from moosetools import moosetest
    c = moosetest.controllers.EnvironmentController()
    r = moosetest.base.make_runner(moosetest.base.Runner, [c,], env_platform='Darwin')
    print(r)
    ```

    See `parameters.InputParameters` for details regarding getting/setting values of a
    sub-parameter.
    """
    params = cls.validParams()
    for ctrl in controllers or []:
        params.add(ctrl.getParam('prefix'), default=ctrl.validObjectParams())
    return cls(params, **kwargs)


class Runner(MooseTestObject):
    """
    Base class for defining a task to be "run", via the `moosetest.run` function.

    The `Runner` object is designed to be as simple as possible. Child objects must override a
    single method: `execute`.
    """
    @staticmethod
    def validParams():
        params = MooseTestObject.validParams()
        params.setRequired('name', True)
        params.add('differs',
                   vtype=Differ,
                   array=True,
                   doc="The 'Differ' object(s) to execute after execution of this object.")

        # Parameters associated with file names
        params.add(
            'file',
            default=InputParameters(),
            doc="Parameters for managing file(s) associated with execution of the `Runner` object.")
        f_params = params.getValue('file')
        f_params.add(
            'base',
            vtype=str,
            verify=(Runner.verifyBaseDirectory,
                    "The supplied directory must exist and be an absolute path."),
            doc=
            "The base directory for relative paths of the supplied names in the 'names' parameter.")
        f_params.add(
            'names',
            vtype=str,
            array=True,
            doc=
            "File name(s) that are expected to be created during execution of this object. The file(s) listed here are joined with the 'filenames' parameter from each differ. The combined set is what is used for associated error checking."
        )

        f_params.add(
            'check_created',
            vtype=bool,
            mutable=False,
            doc=
            "Check that all files created are accounted for in the 'names' parameter of this `Runner` object and/or associated `Differ` objects. By default the check will be performed if the 'base' is set."
        )

        f_params.add(
            'clean',
            vtype=bool,
            default=True,
            doc=
            "Delete pre-existing file names defined in the 'names' parameter of this `Runner` object and/or associated `Differ` objects before calling the `execute` method."
        )

        return params

    @staticmethod
    def verifyBaseDirectory(value):
        """
        Verify function for 'base_dir' parameter.

        Usually a lambda is supplied to the verify argument when adding the parameter; however,
        lambda functions cannot be pickled so they fail when being run with multiprocessing.
        """
        return os.path.isdir(value) and os.path.isabs(value)

    def __init__(self, *args, **kwargs):
        MooseTestObject.__init__(self, *args, **kwargs)
        self.__expected_files = None
        self.__pre_execute_files = None

    def preExecute(self):
        """
        Called prior to execution of this object.

        Performs checks regarding the files expected to be created during execution.
        """
        self._preExecuteExpectedFiles()

    def postExecute(self):
        """
        Called after execution of this object.

        This method is always called, even if `preExecute` and/or `execute` raises an exception or
        results in an error.

        Performs checks that the expected files were created.
        """
        self._postExecuteExpectedFiles()

    def execute(self):
        """
        Override this method to define the task to be "run".

        This method is called by the `TestCase` object that expects a return code. The
        return code is not analyzed and may be non-zero. The code, along with the sys.stdout and
        sys.stderr, are passed to any `Differ` object(s) supplied to in the "differs" input
        parameter.

        Refer to `moosetools.base.TestCase` for how this function is called and
        `moosetools.moosetest.runners.RunCommand` for an example implementation.
        """
        raise NotImplementedError("The 'execute' method must be overridden.")

    def _preExecuteExpectedFiles(self):
        """
        Prepare for inspection of expected file prior to execution.
        """

        # Set of expected files from this object and Differ objects, accounting for 'base_dir'
        self.__expected_files = self._getExpectedFiles()

        # Check that all paths are absolute
        non_abs = [fname for fname in self.__expected_files if not os.path.isabs(fname)]
        if non_abs:
            msg = "The following file(s) were not defined as an absolute path or as a relative path to the 'file_base' parameter:\n  {}"
            self.error(msg, '\n  '.join(non_abs))
            return

        # Check that the file is not under version control
        root_dir = mooseutils.git_root_dir()
        if root_dir:
            git_files = set(mooseutils.git_ls_files(self.getParam('file', 'base') or root_dir))
            intersect = git_files.intersection(self.__expected_files)
            if intersect:
                msg = "The following file(s) are being tracked with 'git', thus cannot be expected to be created by the execution of this object:\n  {}."
                self.error(msg, '\n  '.join(intersect))
                return

        # Remove expected output
        if self.getParam('file', 'clean'):
            for fname in self.__expected_files:
                if os.path.isfile(fname):
                    self.info("Removing file: {}", fname)
                    os.remove(fname)

        # Check that expected files do not exist
        exist = [fname for fname in self.__expected_files if os.path.isfile(fname)]
        if exist:
            msg = "The following files(s) are expected to be created, but they already exist:\n  {}"
            self.error(msg, '\n  '.join(exist))
            return

        # Store directory content
        check_created_files = self.getParam('file', 'check_created')
        if check_created_files and not self.isParamValid('file', 'base'):
            msg = "When 'file_check_created' is enabled, the 'file_base' parameter must be defined to limit the check to the correct location."
            self.error(msg)
            return
        elif check_created_files or ((check_created_files is None)
                                     and self.isParamValid('file', 'base')):
            base_dir = self.getParam('file', 'base')
            self.__pre_execute_files = set(os.path.join(base_dir, f) for f in os.listdir())

    def _postExecuteExpectedFiles(self):
        """
        Inspect expected file after execution.
        """

        # check that expected files exist
        do_not_exist = [fname for fname in self.__expected_files if not os.path.isfile(fname)]
        if do_not_exist:
            msg = "The following file(s) were not created as expected:\n  {}"
            self.error(msg, '\n  '.join(do_not_exist))

        # check for other files
        if self.__pre_execute_files is not None:
            post_execute_files = set(os.listdir(self.getParam('file', 'base')))
            diff = post_execute_files.difference(self.__pre_execute_files)
            if diff and set(self.__expected_files) != diff:
                msg = "The following file(s) were created but not expected:\n  {}"
                self.error(msg, '\n  '.join(diff.difference(set(self.__expected_files))))

    def _getExpectedFiles(self):
        """
        Build the list of expected files.
        """
        expected = Runner.filenames(self)
        for differ in self.getParam('differs') or set():
            expected += Runner.filenames(differ)
        return expected

    @staticmethod
    def filenames(obj):
        """
        Return a set of filenames gathered from the 'filenames' parameters, with relative paths
        being prefixed with the 'base_dir' parameter (if it exists).
        """
        filenames = set(obj.getParam('file', 'names') or list())
        base_dir = obj.getParam('file', 'base')
        if base_dir is not None:
            filenames_abs = list()
            for fname in filenames:
                if os.path.isabs(fname):
                    filenames_abs.append(fname)
                else:
                    filenames_abs.append(os.path.join(base_dir, fname))
            filenames = filenames_abs

        return filenames
