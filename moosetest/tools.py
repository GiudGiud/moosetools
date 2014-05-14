import sys, os

plugin_dir = '/TestHarness/testers'

#module_path = os.path.dirname(__file__)
#if os.environ.has_key("FRAMEWORK_DIR"):
#  FRAMEWORK_DIR = os.environ['FRAMEWORK_DIR']
#elif os.environ.has_key("MOOSE_DIR"):
#  FRAMEWORK_DIR = os.path.join(os.environ['MOOSE_DIR'], 'framework')
#else:
#  FRAMEWORK_DIR = os.path.abspath(module_path) + '/../..'
#sys.path.append(os.path.join(MOOSE_DIR, 'python', 'TestHarness')
#sys.path.append(FRAMEWORK_DIR + plugin_dir)

# Import the Two Harness classes
from TestTimer import TestTimer
from TestHarness import TestHarness

# Tester Base Class
from Tester import Tester
# New Testers can be created and automatically registered with the
# TestHarness if you follow these two steps:
# 1. Create a class inheriting from "Tester" or any of its descendents
# 2. Place your new class in the plugin_dir directory (see def above)
#    under your application

def runTests(argv, app_name, moose_dir):
  if '--store-timing' in argv:
    # Pass control to TestTimer class for Test Timing
    harness = TestTimer(argv, app_name, moose_dir)
  else:
    harness = TestHarness(argv, app_name, moose_dir)

  # Get a reference to the factory out of the TestHarness
  factory = harness.getFactory()

  # TODO: We need to cascade the testers so that each app can use any
  # tester available in each parent application
  dirs = [os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), 'scripts')), os.path.join(moose_dir, 'python')]

  # Load the tester plugins into the factory reference
  factory.loadPlugins(dirs, plugin_dir, Tester)

  # Finally find and run the tests
  harness.findAndRunTests()
