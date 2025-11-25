#
# The most bare-bone versions of the test runner support
#

from . import launchable


subset = launchable.CommonSubsetImpls(__name__).scan_files()

record_tests = launchable.CommonRecordTestImpls(__name__).file_profile_report_files()

split_subset = launchable.CommonSplitSubsetImpls(__name__).split_subset()

launchable.CommonFlakeDetectionImpls(__name__).detect_flakes()
