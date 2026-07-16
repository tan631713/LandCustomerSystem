"""Shared dependency seams for desktop workflow mixins."""

import sys


class DesktopSupportMixin:
    """Resolve replaceable UI components and operation logging."""

    def _app_component(self, name):
        module = sys.modules[self.__class__.__module__]
        return getattr(module, name)

    def _log_operation(self, action_type, summary, detail=None):
        repository = (
            self.active_record_repository()
            if getattr(self, "api_mode", False)
            else self.repository
        )
        return repository.log_operation(action_type, summary, detail)
