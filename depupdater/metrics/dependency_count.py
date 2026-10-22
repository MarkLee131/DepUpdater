import json

def count_deps(json_path):
    with open(json_path, 'r') as f:
        deps = json.load(f)
    count = 0
    for dep in deps:
        if dep['Dependents']:
            count += 1
    return count