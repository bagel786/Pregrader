
import numpy as np

def convert_numpy_types(obj):
    """
    Recursively convert numpy types to native Python types in dictionaries and lists.
    This prevents JSON serialization errors in FastAPI endpoints.
    """
    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_numpy_types(v) for v in obj)
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        # Convert NaN/Inf to None or string, though JSON spec doesn't support NaN
        if np.isnan(obj):
            return None
        if np.isinf(obj):
            return str(obj)
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return convert_numpy_types(obj.tolist())
    elif isinstance(obj, np.bool_):
        return bool(obj)
    return obj
