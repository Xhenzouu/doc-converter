"""Base interface for OS shell and desktop integration."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BasePlatformIntegration(ABC):
    """Abstract base class for platform-specific context menu integration."""

    @abstractmethod
    def install_context_menu(self) -> bool:
        """Register the 'Convert to' context sub-menu in the OS file manager."""

    @abstractmethod
    def uninstall_context_menu(self) -> bool:
        """Remove the 'Convert to' context sub-menu from the OS file manager."""

    @abstractmethod
    def is_menu_installed(self) -> bool:
        """Return True if the context menu is currently registered."""
