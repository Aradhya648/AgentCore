import sys
sys.path.insert(0, 'lib')
import yaml
result = yaml.dump(['foo'])
print('Result:', repr(result))
assert result, 'yaml.dump returned empty string'
print('OK')
