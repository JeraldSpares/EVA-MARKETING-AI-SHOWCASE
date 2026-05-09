import sys

with open("dashboard.py", "r", encoding="utf-8") as f:
    content = f.read()

def resolve_conflicts_keep_ours(text):
    result = []
    i = 0
    lines = text.split('\n')
    while i < len(lines):
        if lines[i].startswith('<<<<<<<'):
            i += 1
            while i < len(lines) and not lines[i].startswith('======='):
                i += 1
            i += 1  # skip =======
            ours = []
            while i < len(lines) and not lines[i].startswith('>>>>>>>'):
                ours.append(lines[i])
                i += 1
            i += 1  # skip >>>>>>>
            result.extend(ours)
        else:
            result.append(lines[i])
            i += 1
    return '\n'.join(result)

conflict_count = content.count('<<<<<<<')
print(f"Found {conflict_count} conflicts")
resolved = resolve_conflicts_keep_ours(content)

with open("dashboard.py", "w", encoding="utf-8") as f:
    f.write(resolved)

remaining = resolved.count('<<<<<<<')
print(f"Resolved all. Remaining: {remaining}")
print("Lines:", len(resolved.splitlines()))
