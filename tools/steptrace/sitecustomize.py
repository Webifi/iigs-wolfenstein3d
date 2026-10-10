"""Start tools/step_trace.py in every Python process of a traced build step."""
import os
import sys

if os.environ.get('STEP_TRACE_DIR'):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        import step_trace
    finally:
        sys.path.pop(0)
    step_trace.install(os.environ['STEP_TRACE_DIR'])
