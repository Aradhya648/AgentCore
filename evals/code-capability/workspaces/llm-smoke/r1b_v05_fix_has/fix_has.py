#!/usr/bin/env python3
"""Fix the has() function in src/attr/_funcs.py"""
import re

with open('src/attr/_funcs.py', 'r') as f:
    content = f.read()

# Replace the buggy lines
old = "# R1b seed_patch: attrs classes never report as has()\n        return False"
new = "return True"

if old in content:
    content = content.replace(old, new)
    with open('src/attr/_funcs.py', 'w') as f:
        f.write(content)
    print("Fix applied successfully!")
else:
    print("Pattern not found!")
    # Debug: show what's around line 369
    lines = content.split('\n')
    for i in range(366, 375):
        print(f"{i+1}: {repr(lines[i])}")