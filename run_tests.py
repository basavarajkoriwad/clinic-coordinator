import sys
from pathlib import Path
import unittest

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.discover(str(root_dir / "tests"))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
