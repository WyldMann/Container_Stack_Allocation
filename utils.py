import re

# stopgap fix to deal with string input discrepancies, e.g. leading zeroes and undercase
def strGeneralize(s: str) -> str:
    return re.sub(r'^0+(?!$)', '', s).upper()