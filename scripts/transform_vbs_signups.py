#!/usr/bin/env python3
"""Reshape the Kingdom Quest VBS 2026 Google Form export (wide: one row per
family, Child 1-6 as repeating columns) into the import_signups long format
(one row per child).

Usage: python3 transform_vbs_signups.py INPUT.csv OUTPUT.csv [--opt-in yes|no]
"""
import csv
import sys

OUT_HEADERS = [
    "parent_first_name", "parent_last_name", "parent_phone", "parent_email",
    "phone_opt_in", "child_first_name", "child_last_name", "child_birthdate",
    "child_grade", "child_allergies", "custody_notes", "unauthorized_pickup",
    "photo_consent",
]
JUNK = {"", "none", "na", "n/a", "-", "n.a."}


def split_name(full):
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def clean(v):
    return (v or "").strip()


def main():
    inp, outp = sys.argv[1], sys.argv[2]
    opt_in = "no"
    if "--opt-in" in sys.argv:
        opt_in = sys.argv[sys.argv.index("--opt-in") + 1].strip().lower()

    with open(inp, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    data = rows[1:]  # row 0 is the (multi-line) header, parsed as one record

    out_rows = []
    for r in data:
        if len(r) < 27 or not clean(r[1]):
            continue
        parent_name = clean(r[1])
        parent_phone = clean(r[2])
        parent_email = clean(r[6])
        custody_raw = clean(r[5])
        photo_raw = clean(r[26]).lower()
        photo = "yes" if "permission to take photos" in photo_raw else "no"
        custody = "" if custody_raw.lower() in {"", "no custody issues", "none", "no"} else custody_raw

        # Collect real children (name present, not a junk placeholder).
        kids = []
        for k in range(6):
            name = clean(r[8 + 3 * k])
            if name.lower() in JUNK:
                continue
            grade = clean(r[9 + 3 * k])
            dietary = clean(r[10 + 3 * k])
            allergies = "" if dietary.lower() in JUNK else dietary
            kids.append((name, grade, allergies))
        if not kids:
            continue

        p_first, p_last = split_name(parent_name)
        if not p_last:  # single-token parent → borrow the first child's last name
            _, p_last = split_name(kids[0][0])

        for name, grade, allergies in kids:
            c_first, c_last = split_name(name)
            out_rows.append({
                "parent_first_name": p_first,
                "parent_last_name": p_last,
                "parent_phone": parent_phone,
                "parent_email": parent_email,
                "phone_opt_in": opt_in,
                "child_first_name": c_first,
                "child_last_name": c_last,  # blank inherits parent last name
                "child_birthdate": "",
                "child_grade": grade,
                "child_allergies": allergies,
                "custody_notes": custody,
                "unauthorized_pickup": "",
                "photo_consent": photo,
            })

    with open(outp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_HEADERS)
        w.writeheader()
        w.writerows(out_rows)

    families = len({(r["parent_first_name"], r["parent_last_name"], r["parent_phone"]) for r in out_rows})
    print(f"wrote {len(out_rows)} child rows across {families} families to {outp}")
    print(f"photo_consent=yes: {sum(1 for r in out_rows if r['photo_consent']=='yes')} children")
    print(f"custody notes: {sum(1 for r in out_rows if r['custody_notes'])} children")
    print(f"allergies noted: {sum(1 for r in out_rows if r['child_allergies'])} children")


if __name__ == "__main__":
    main()
