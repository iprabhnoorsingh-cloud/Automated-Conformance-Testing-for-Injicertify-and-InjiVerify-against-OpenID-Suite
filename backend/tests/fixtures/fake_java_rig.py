#!/usr/bin/env python3
"""Stand-in "java" executable for Inji Test-Rig executor tests.

Invoked directly (via its shebang, with the executable bit set) so its
argv/env are exactly what a real `java -jar -Dmodules=... ... <jar>`
invocation would receive — no real JVM or Inji Test-Rig JAR needed.

FAKE_RIG_SCENARIO (env var) selects behavior:
  pass            -> writes an all-passing testng-report/testng-results.xml, exits 0
  fail            -> writes a mixed pass/fail report, exits 0 (mirrors the
                     real InjiTestRunner, which calls System.exit(0)
                     unconditionally regardless of TestNG outcome)
  crash           -> exits 1 without writing a report
  no_report       -> exits 0 without writing a report
  malformed_report-> writes non-XML garbage as the report, exits 0
  sleep           -> sleeps for FAKE_RIG_SLEEP_SECONDS (to test timeout/kill)

If FAKE_RIG_DUMP_PATH is set, writes {"argv": ..., "env": {...}} as JSON so
tests can assert on exactly what argv/env the executor constructed.
"""

import json
import os
import sys
import time

_CAPTURED_ENV_KEYS = (
    "eSignetbaseurl",
    "injiCertifyBaseURL",
    "mosip_components_base_urls",
    "useCaseToExecute",
    "esignetActuatorPropertySection",
    "usePreConfiguredOtp",
    "sunBirdBaseURL",
    "injiVerifyBaseUrl",
)

_PASS_XML = (
    '<testng-results total="2" passed="2" failed="0" skipped="0">'
    '<suite name="S"><test name="T"><class name="c.Test">'
    '<test-method status="PASS" name="testA"/>'
    '<test-method status="PASS" name="testB"/>'
    "</class></test></suite></testng-results>"
)

_FAIL_XML = (
    '<testng-results total="2" passed="1" failed="1" skipped="0">'
    '<suite name="S"><test name="T"><class name="c.Test">'
    '<test-method status="FAIL" name="testA"/>'
    '<test-method status="PASS" name="testB"/>'
    "</class></test></suite></testng-results>"
)


def main():
    scenario = os.environ.get("FAKE_RIG_SCENARIO", "pass")

    dump_path = os.environ.get("FAKE_RIG_DUMP_PATH")
    if dump_path:
        with open(dump_path, "w") as f:
            json.dump(
                {
                    "argv": sys.argv[1:],
                    "env": {k: os.environ[k] for k in _CAPTURED_ENV_KEYS if k in os.environ},
                },
                f,
            )

    if scenario == "sleep":
        time.sleep(float(os.environ.get("FAKE_RIG_SLEEP_SECONDS", "60")))
        sys.exit(0)

    if scenario == "crash":
        sys.exit(1)

    if scenario == "no_report":
        sys.exit(0)

    report_dir = os.path.join(os.getcwd(), "testng-report")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "testng-results.xml")

    if scenario == "malformed_report":
        with open(report_path, "w") as f:
            f.write("not xml {{{")
        sys.exit(0)

    with open(report_path, "w") as f:
        f.write(_FAIL_XML if scenario == "fail" else _PASS_XML)

    # The real InjiTestRunner.main() calls System.exit(0) unconditionally,
    # regardless of TestNG pass/fail — deliberately replicated here.
    sys.exit(0)


if __name__ == "__main__":
    main()
