
import unittest
import numpy as np
import json
import sys
import os

# Add backend directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), "."))

from utils.serialization import convert_numpy_types

class TestSerialization(unittest.TestCase):
    def test_numpy_conversion(self):
        # Create a complex structure with numpy types
        data = {
            "int64": np.int64(42),
            "float64": np.float64(3.14),
            "array": np.array([1, 2, 3], dtype=np.int64),
            "nested": {
                "bool": np.bool_(True),
                "list_of_floats": [np.float32(1.1), np.float32(2.2)]
            },
            "mixed_list": [np.int32(10), "string", np.float64(5.5)]
        }
        
        # Verify it fails JSON serialization before conversion
        try:
            json.dumps(data)
            self.fail("Should have failed serialization")
        except TypeError:
            pass # Expected failure
            
        # Convert
        cleaned = convert_numpy_types(data)
        
        # Verify it passes JSON serialization
        try:
            json_str = json.dumps(cleaned)
            print(f"Successfully serialized: {json_str}")
        except TypeError as e:
            self.fail(f"Serialization failed after cleanup: {e}")
            
        # Verify types
        self.assertIsInstance(cleaned["int64"], int)
        self.assertIsInstance(cleaned["float64"], float)
        self.assertIsInstance(cleaned["array"], list)
        self.assertIsInstance(cleaned["array"][0], int)
        self.assertIsInstance(cleaned["nested"]["bool"], bool)

if __name__ == "__main__":
    unittest.main()
