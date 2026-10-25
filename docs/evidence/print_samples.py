import json

def inspect_saved(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        d = json.load(f)
    print("=====================================================")
    print("DATASET:", d["dataset_name"], "(", d["dataset_id"], ")")
    print("COLUMNS:")
    for c in d["columns"]:
        desc = c.get("description") or ""
        print(f"  - {c.get('name')} [{c.get('fieldName')}] ({c.get('dataTypeName')}): {desc[:80]}")
    print("\nSAMPLE ROW 0:")
    rec0 = d["sample_records"][0]
    for k, v in rec0.items():
        if not k.startswith(":"):
            print(f"  {k}: {repr(v)}")
    print("\nSAMPLE ROW 1:")
    rec1 = d["sample_records"][1]
    for k, v in rec1.items():
        if not k.startswith(":"):
            print(f"  {k}: {repr(v)}")

inspect_saved("docs/evidence/sample_wrvz-psew.json")
inspect_saved("docs/evidence/sample_m6dm-c72p.json")

