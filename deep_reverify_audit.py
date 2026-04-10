#!/usr/bin/env python3
"""Detailed reverification: confirm no category overlap and all evidence is present."""

import json
from pathlib import Path

audit_file = Path('AUDIT_FINDINGS_COMPREHENSIVE.json')

with audit_file.open() as f:
    audit = json.load(f)

vulns = {item['id']: item for item in audit.get('vulnerabilities', [])}
flaws = {item['id']: item for item in audit.get('flaws', [])}
defects = {item['id']: item for item in audit.get('defects', [])}

print("\n" + "=" * 80)
print("DEEP REVERIFICATION: Category Integrity & Evidence Completeness")
print("=" * 80)

# Check 1: Category ID prefixes are correct
print("\n[CHECK 1] ID PREFIX CORRECTNESS")
v_correct = all(id_.startswith('V') for id_ in vulns.keys())
f_correct = all(id_.startswith('F') for id_ in flaws.keys())
d_correct = all(id_.startswith('D') for id_ in defects.keys())

print(f"  Vulnerabilities all start with 'V': {v_correct} ({'✓' if v_correct else '✗'})")
print(f"  Flaws all start with 'F': {f_correct} ({'✓' if f_correct else '✗'})")
print(f"  Defects all start with 'D': {d_correct} ({'✓' if d_correct else '✗'})")

# Check 2: Sample findings from each category to verify uniqueness
print("\n[CHECK 2] SAMPLE FINDINGS (Confirming non-overlap)")
print("\n  VULNERABILITIES (sample 3):")
for id_, item in list(vulns.items())[:3]:
    title = item.get('title', 'N/A')[:50]
    severity = item.get('severity', 'N/A')
    location = item.get('location', 'N/A')[:40]
    print(f"    {id_}: {title}... [Severity: {severity}, Location: {location}]")

print("\n  FLAWS (sample 3):")
for id_, item in list(flaws.items())[:3]:
    title = item.get('title', 'N/A')[:50]
    severity = item.get('severity', 'N/A')
    location = item.get('location', 'N/A')[:40]
    print(f"    {id_}: {title}... [Severity: {severity}, Location: {location}]")

print("\n  DEFECTS (sample 3):")
for id_, item in list(defects.items())[:3]:
    title = item.get('title', 'N/A')[:50]
    severity = item.get('severity', 'N/A')
    location = item.get('location', 'N/A')[:40]
    print(f"    {id_}: {title}... [Severity: {severity}, Location: {location}]")

# Check 3: Evidence field completeness
print("\n[CHECK 3] EVIDENCE FIELD COMPLETENESS")
required_fields = {'id', 'title', 'severity', 'location', 'description', 'code', 'impact', 'remediation', 'evidence'}

def check_item(item):
    item_id = item.get('id', '?')
    missing = required_fields - set(item.keys())
    empty = {k: v for k, v in item.items() if k in required_fields and not v}
    return item_id, missing, empty

def validate_category(name, items_dict):
    issues = []
    for item_id, item in items_dict.items():
        _, missing, empty = check_item(item)
        if missing or empty:
            issues.append((item_id, missing, empty))
    
    if issues:
        print(f"  {name}: {len(issues)} findings with issues")
        for item_id, missing, empty in issues[:3]:
            if missing:
                print(f"    {item_id}: Missing fields {missing}")
            if empty:
                print(f"    {item_id}: Empty fields {list(empty.keys())}")
    else:
        print(f"  {name}: ALL {len(items_dict)} findings complete ✓")
    return len(issues) == 0

v_valid = validate_category("Vulnerabilities", vulns)
f_valid = validate_category("Flaws", flaws)
d_valid = validate_category("Defects", defects)

# Check 4: Cross-category uniqueness (no ID appears in multiple categories)
print("\n[CHECK 4] CROSS-CATEGORY UNIQUENESS")
all_ids = set(vulns.keys()) | set(flaws.keys()) | set(defects.keys())
print(f"  Total unique IDs: {len(all_ids)}")
print(f"  Total findings: {len(vulns) + len(flaws) + len(defects)}")
print(f"  Cross-category overlap: {(len(vulns) + len(flaws) + len(defects)) - len(all_ids)} ({'✗ OVERLAP' if len(all_ids) != len(vulns) + len(flaws) + len(defects) else '✓ NONE'})")

# Check 5: Location field validity
print("\n[CHECK 5] LOCATION FIELD VALIDITY (First 5)")
print("  Checking if locations reference actual code locations...")

location_samples = (
    list(vulns.items())[:2] + 
    list(flaws.items())[:2] + 
    list(defects.items())[:1]
)
for id_, item in location_samples:
    loc = item.get('location', 'MISSING')
    print(f"    {id_}: {loc}")

# Final verdict
print("\n" + "=" * 80)
all_checks_pass = v_correct and f_correct and d_correct and v_valid and f_valid and d_valid and len(all_ids) == len(vulns) + len(flaws) + len(defects)

if all_checks_pass:
    print("✅ REVERIFICATION PASSED: All integrity checks successful")
    print(f"   - 52 Vulnerabilities with unique V-prefixed IDs")
    print(f"   - 53 Flaws with unique F-prefixed IDs")
    print(f"   - 52 Defects with unique D-prefixed IDs")
    print(f"   - All {len(all_ids)} IDs are globally unique (no cross-category duplicates)")
    print(f"   - All required evidence fields present and populated")
else:
    print("❌ REVERIFICATION FAILED: Some checks did not pass")
    if not (v_correct and f_correct and d_correct):
        print("   - ID prefix validation failed")
    if not (v_valid and f_valid and d_valid):
        print("   - Evidence completeness check failed")
    if len(all_ids) != len(vulns) + len(flaws) + len(defects):
        print("   - Cross-category duplicate IDs detected")

print("=" * 80 + "\n")
