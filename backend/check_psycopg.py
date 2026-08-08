import sys
import importlib.util
import pkgutil

print('executable:', sys.executable)
print('sys.path first 10:')
for p in sys.path[:10]:
    print('  ', p)
print('find_spec psycopg:', importlib.util.find_spec('psycopg'))
print('find_spec psycopg2:', importlib.util.find_spec('psycopg2'))
print('psycopg modules:', [m.name for m in pkgutil.iter_modules() if m.name.startswith('psycopg')])
