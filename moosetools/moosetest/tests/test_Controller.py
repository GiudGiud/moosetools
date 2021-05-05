#!/usr/bin/env python3
import io
import logging
import unittest
from moosetools.parameters import InputParameters
from moosetools.base import MooseException
from moosetools import moosetest

class TestController(unittest.TestCase):
    def testDefault(self):

        with self.assertRaises(MooseException) as ex:
            moosetest.base.Controller()
        self.assertIn("The parameter 'prefix' is marked as required", str(ex.exception))

        ctrl = moosetest.base.Controller(prefix="foo")
        self.assertEqual(ctrl.name(), 'Controller')
        self.assertTrue(ctrl.isRunnable())

        with self.assertRaises(NotImplementedError) as ex:
            ctrl.execute(None, None)
        self.assertIn("The 'execute' method must be overridden.", str(ex.exception))

    def testControllers(self):
        ctrl = moosetest.base.Controller(prefix="foo")
        self.assertTrue(ctrl.isRunnable())
        ctrl.skip("Don't do it!")
        self.assertFalse(ctrl.isRunnable())

        ctrl.reset()
        self.assertTrue(ctrl.isRunnable())
