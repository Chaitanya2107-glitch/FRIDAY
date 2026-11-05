"""Retain the full run and bind native reruns to the exact tested source."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tasks/passive-validation/source"
EVIDENCE = SOURCE / "tasks"
sys.path.insert(0, str(SOURCE))


def key(case):
    return case.get("classname"), case.get("name")


def counts(cases):
    result = {"tests": len(cases), "errors": sum(c.find("error") is not None for c in cases),
              "failures": sum(c.find("failure") is not None for c in cases),
              "skipped": sum(c.find("skipped") is not None for c in cases)}
    result["passed"] = result["tests"] - result["errors"] - result["failures"] - result["skipped"]
    return result


def main():
    from tasks import verify_passive_assistant as verify
    assert verify.ROOT == SOURCE
    original = json.loads((EVIDENCE / "passive-initial-tested-sources.json").read_text(encoding="utf-8"))
    current = json.loads((EVIDENCE / "passive-tested-sources.json").read_text(encoding="utf-8"))
    assert current["files"] == verify.sources(), "The isolated source changed after native rechecks."
    changed = {name for name in original["files"].keys() | current["files"].keys()
               if original["files"].get(name) != current["files"].get(name)}
    assert changed == {"tests/test_phone_bridge.py", "tests/test_settings_window.py"}
    assert verify.production_identity(original["files"]) == verify.production_identity(current["files"])
    initial = ET.parse(EVIDENCE / "passive-full-initial.xml")
    rerun = ET.parse(EVIDENCE / "passive-native-rechecks.xml")
    cases = list(initial.getroot().iter("testcase"))
    reruns = {key(case): case for case in rerun.getroot().iter("testcase")}
    assert not counts(list(reruns.values()))["errors"] and not counts(list(reruns.values()))["failures"]
    known = {key(case) for case in cases}
    assert reruns.keys() <= known
    for name in changed:
        module = Path(name).stem
        assert all(key(case) in reruns for case in cases if module in case.get("classname", "").split("."))
    failed = {key(case) for case in cases if case.find("failure") is not None or case.find("error") is not None}
    assert failed <= reruns.keys(), "A failing case was not rechecked."
    initial_counts = counts(cases)
    for suite in initial.getroot().iter("testsuite"):
        for index, case in enumerate(list(suite)):
            if case.tag == "testcase" and key(case) in reruns:
                suite.remove(case)
                suite.insert(index, copy.deepcopy(reruns[key(case)]))
        total = counts(suite.findall("testcase"))
        for field in ("tests", "errors", "failures", "skipped"):
            suite.set(field, str(total[field]))
        properties = suite.find("properties")
        if properties is None:
            properties = ET.Element("properties")
            suite.insert(0, properties)
        for name, value in {"initial_report": "passive-full-initial.xml", "native_recheck_report": "passive-native-rechecks.xml",
                            "source_identity": current["identity"],
                            "aggregation": "Full run plus complete affected modules; unchanged production source; original results retained."}.items():
            ET.SubElement(properties, "property", name=name, value=value)
    final = counts(list(initial.getroot().iter("testcase")))
    assert final["tests"] == initial_counts["tests"] and not final["failures"] and not final["errors"]
    initial.write(EVIDENCE / "passive-full.xml", encoding="utf-8", xml_declaration=True)
    receipt = {"source_identity": current["identity"], "initial_source_identity": original["identity"],
               "unchanged_production_identity": verify.production_identity(current["files"]),
               "initial_full": initial_counts, "native_rechecks": counts(list(reruns.values())), "effective_full": final,
               "changed_test_modules_completely_rechecked": sorted(changed),
               "reason": "Sandbox denied Windows Script Host/Tcl access; unit GUI callback was stubbed, and project cwd is checked by absolute path instead of folder name.",
               "raw_reports_retained": True, "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (EVIDENCE / "passive-test-reconciliation.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    verify.receipt()
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
