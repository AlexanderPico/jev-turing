"""JEV as a diode-like primitive: gates -> latch -> Rule 110.

Every logic decision is one binary JEV judgment. Offline work uses FakeJEV,
whose results are NOT JEV results.
"""
from .backend import FakeJEV, JevAdapter, JevNotConfiguredError, judge

__all__ = ["FakeJEV", "JevAdapter", "JevNotConfiguredError", "judge"]
__version__ = "0.1.0"
