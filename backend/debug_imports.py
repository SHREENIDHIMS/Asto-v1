import sys
sys.path.insert(0, 'backend')
from app.main import app
print("App created successfully")
print("Routes:")
for r in app.routes:
    if hasattr(r, "path"):
        methods = getattr(r, "methods", None)
        if methods:
            print(f"  {methods} {r.path}")
        else:
            print(f"  {r.path}")
