"""Tests for TestRigResultParser against TestNG's standard testng-results.xml
schema (confirmed from the actual inji-certify/inji-verify InjiTestRunner.java
source, which calls TestNG.setOutputDirectory("testng-report") with default
listeners enabled — this is TestNG's own stable report format, not
MOSIP-specific)."""

import pytest

from app.inji_report import (
    MalformedReportError,
    ReportNotFoundError,
    TestRigResultParser,
    locate_report,
)

ALL_PASSING = """<?xml version="1.0" encoding="UTF-8"?>
<testng-results total="3" passed="3" failed="0" skipped="0">
  <suite name="Suite">
    <test name="Test">
      <class name="com.example.MyTest">
        <test-method status="PASS" name="testOne"/>
        <test-method status="PASS" name="testTwo"/>
        <test-method status="PASS" name="testThree"/>
      </class>
    </test>
  </suite>
</testng-results>
"""

MIXED_RESULTS = """<?xml version="1.0" encoding="UTF-8"?>
<testng-results total="4" passed="2" failed="1" skipped="1">
  <suite name="Suite">
    <test name="Test">
      <class name="com.example.MyTest">
        <test-method status="PASS" name="testOne"/>
        <test-method status="FAIL" name="testTwo"/>
        <test-method status="SKIP" name="testThree"/>
        <test-method status="PASS" name="testFour"/>
      </class>
    </test>
  </suite>
</testng-results>
"""

ALL_SKIPPED = """<?xml version="1.0" encoding="UTF-8"?>
<testng-results total="2" passed="0" failed="0" skipped="2">
  <suite name="Suite">
    <test name="Test">
      <class name="com.example.MyTest">
        <test-method status="SKIP" name="testOne"/>
        <test-method status="SKIP" name="testTwo"/>
      </class>
    </test>
  </suite>
</testng-results>
"""

ZERO_TESTS = """<?xml version="1.0" encoding="UTF-8"?>
<testng-results total="0" passed="0" failed="0" skipped="0">
  <suite name="Suite"/>
</testng-results>
"""

MULTIPLE_SUITES = """<?xml version="1.0" encoding="UTF-8"?>
<testng-results total="4" passed="3" failed="1" skipped="0">
  <suite name="PrerequisiteSuite">
    <test name="Test">
      <class name="com.example.PreReqTest">
        <test-method status="PASS" name="setupOne"/>
        <test-method status="PASS" name="setupTwo"/>
      </class>
    </test>
  </suite>
  <suite name="CoreSuite">
    <test name="Test">
      <class name="com.example.CoreTest">
        <test-method status="PASS" name="coreOne"/>
        <test-method status="FAIL" name="coreTwo"/>
      </class>
    </test>
  </suite>
</testng-results>
"""

MISSING_ATTRIBUTES = """<?xml version="1.0" encoding="UTF-8"?>
<testng-results>
  <suite name="Suite"/>
</testng-results>
"""

WRONG_ROOT = """<?xml version="1.0" encoding="UTF-8"?>
<not-testng-results total="1" passed="1" failed="0" skipped="0"/>
"""


def write_report(tmp_path, content):
    report_dir = tmp_path / "testng-report"
    report_dir.mkdir()
    report_path = report_dir / "testng-results.xml"
    report_path.write_text(content)
    return report_path


def test_all_passing(tmp_path):
    path = write_report(tmp_path, ALL_PASSING)
    result = TestRigResultParser().parse(path)
    assert result.tests_total == 3
    assert result.tests_passed == 3
    assert result.tests_failed == 0
    assert result.all_passed is True
    assert result.failure_summary == []


def test_mixed_pass_fail(tmp_path):
    path = write_report(tmp_path, MIXED_RESULTS)
    result = TestRigResultParser().parse(path)
    assert result.tests_total == 4
    assert result.tests_passed == 2
    assert result.tests_failed == 1
    assert result.tests_skipped == 1
    assert result.all_passed is False
    assert result.failure_summary == ["com.example.MyTest.testTwo"]


def test_all_skipped_is_never_treated_as_passed(tmp_path):
    path = write_report(tmp_path, ALL_SKIPPED)
    result = TestRigResultParser().parse(path)
    assert result.tests_failed == 0
    assert result.tests_passed == 0
    # Zero failures but also zero actual passes must never be "PASSED".
    assert result.all_passed is False


def test_zero_tests_is_never_treated_as_passed(tmp_path):
    path = write_report(tmp_path, ZERO_TESTS)
    result = TestRigResultParser().parse(path)
    assert result.tests_total == 0
    assert result.all_passed is False


def test_multiple_suites_aggregates_from_root_attributes(tmp_path):
    path = write_report(tmp_path, MULTIPLE_SUITES)
    result = TestRigResultParser().parse(path)
    assert result.tests_total == 4
    assert result.tests_passed == 3
    assert result.tests_failed == 1
    assert result.failure_summary == ["com.example.CoreTest.coreTwo"]


def test_missing_file_raises_report_not_found(tmp_path):
    with pytest.raises(ReportNotFoundError):
        TestRigResultParser().parse(tmp_path / "does-not-exist.xml")


def test_malformed_xml_raises_malformed_report_error(tmp_path):
    path = tmp_path / "bad.xml"
    path.write_text("not xml at all {{{")
    with pytest.raises(MalformedReportError):
        TestRigResultParser().parse(path)


def test_missing_count_attributes_raises_malformed_report_error(tmp_path):
    path = tmp_path / "bad.xml"
    path.write_text(MISSING_ATTRIBUTES)
    with pytest.raises(MalformedReportError):
        TestRigResultParser().parse(path)


def test_wrong_root_element_raises_malformed_report_error(tmp_path):
    path = tmp_path / "bad.xml"
    path.write_text(WRONG_ROOT)
    with pytest.raises(MalformedReportError):
        TestRigResultParser().parse(path)


def test_empty_file_raises_malformed_report_error(tmp_path):
    path = tmp_path / "empty.xml"
    path.write_text("")
    with pytest.raises(MalformedReportError):
        TestRigResultParser().parse(path)


# --- locate_report ---------------------------------------------------


def test_locate_report_finds_direct_child(tmp_path):
    write_report(tmp_path, ALL_PASSING)
    found = locate_report(tmp_path)
    assert found == tmp_path / "testng-report" / "testng-results.xml"


def test_locate_report_finds_nested_under_subdirectory(tmp_path):
    nested = tmp_path / "target"
    nested.mkdir()
    write_report(nested, ALL_PASSING)
    found = locate_report(tmp_path)
    assert found == nested / "testng-report" / "testng-results.xml"


def test_locate_report_returns_none_when_absent(tmp_path):
    assert locate_report(tmp_path) is None


def test_locate_report_never_escapes_working_directory(tmp_path):
    # A sibling directory with a report must not be found — search is
    # bounded to the working directory's own subtree.
    sibling = tmp_path.parent / f"{tmp_path.name}-sibling-should-not-be-found"
    sibling.mkdir(exist_ok=True)
    try:
        write_report(sibling, ALL_PASSING)
        assert locate_report(tmp_path) is None
    finally:
        import shutil

        shutil.rmtree(sibling, ignore_errors=True)
