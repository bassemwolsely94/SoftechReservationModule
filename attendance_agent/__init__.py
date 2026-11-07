"""Standalone attendance collection agent. Standard library only, no Django."""
import logging

# Handlers are added by collector.configure_logging: its rotating file, and the console
# only for --once. Without this, warnings would reach stderr by default.
logging.getLogger('attendance_agent').addHandler(logging.NullHandler())
