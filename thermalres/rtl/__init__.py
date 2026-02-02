"""
RTL integration layer.

Provides adapter functions to run RTL simulations and return results.
"""

from .adapter import RtlLinkSample, run_link_monitor_rtl

__all__ = ["RtlLinkSample", "run_link_monitor_rtl"]
