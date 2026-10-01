from pathlib import Path
import sys, tempfile, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from junit_profile import analyze,ReportError
class ProfileTests(unittest.TestCase):
    def run_xml(self,xml):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.xml';p.write_text(xml);return analyze(p)
    def test_simple(self):
        r=self.run_xml('<testsuite><testcase name="a" time="1.2"/></testsuite>')
        self.assertEqual(r['counts'],{'passed':1})
    def test_skipped(self):
        r=self.run_xml('<testsuite><testcase name="a"><skipped/></testcase></testsuite>')
        self.assertEqual(r['counts'],{'skipped':1})
    def test_failed(self):
        r=self.run_xml('<testsuites><testsuite><testcase name="a"><failure type="AssertionError"/></testcase></testsuite></testsuites>')
        self.assertEqual(r['failure_families'][0]['records'],1)
    def test_error(self):
        r=self.run_xml('<testsuite><testcase name="a"><error/></testcase></testsuite>')
        self.assertEqual(r['counts'],{'error':1})
    def test_empty(self):
        with self.assertRaises(ReportError):self.run_xml('<testsuite tests="10"/>')
    def test_corrupt(self):
        with self.assertRaises(ReportError):self.run_xml('<testsuite>')
    def test_missing(self):
        with self.assertRaises(ReportError):analyze(Path('/definitely-absent-0927V1.xml'))
    def test_duplicates_are_explicit(self):
        r=self.run_xml('<testsuite><testcase name="a"/><testcase name="a"/></testsuite>')
        self.assertEqual(r['case_records'],2);self.assertEqual(r['duplicate_diagnostic_ids'],['::a'])
    def test_native_node_id(self):
        r=self.run_xml('<testsuite><testcase name="a"><properties><property name="pytest_nodeid" value="tests/t.py::a[x]"/></properties></testcase></testsuite>')
        self.assertEqual(r['native_nodeid_missing_records'],0)
    def test_no_wall_clock_inference(self):
        r=self.run_xml('<testsuite><testcase name="a" time="2"/><testcase name="b" time="3"/></testsuite>')
        self.assertEqual(r['case_time_sum_seconds'],5);self.assertIsNone(r['wall_clock_seconds'])
    def test_nonfinite(self):
        with self.assertRaises(ReportError):self.run_xml('<testsuite><testcase time="NaN"/></testsuite>')
    def test_negative(self):
        with self.assertRaises(ReportError):self.run_xml('<testsuite><testcase time="-1"/></testsuite>')
if __name__=='__main__':unittest.main()
