"""Standalone attendance collection agent. Standard library only, no Django."""
import logging

# The agent logs to its rotating file (collector.configure_logging), never the console.
logging.getLogger('attendance_agent').addHandler(logging.NullHandler())
