"""State management package for desktop application."""

from desktop.state.app_state import AppState
from desktop.state.signals import app_signals

__all__ = ["AppState", "app_signals"]
