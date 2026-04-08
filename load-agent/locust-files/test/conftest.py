import os
import sys

test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, test_dir)
sys.path.insert(0, os.path.dirname(test_dir))
sys.path.insert(0, os.path.dirname(os.path.dirname(test_dir)))
