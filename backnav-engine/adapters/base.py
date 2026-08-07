from abc import ABC, abstractmethod


class RestoreAdapter(ABC):

    @abstractmethod
    def supports(self, focus_item):
        pass

    @abstractmethod
    def capture(self, focus_item):
        """
        Enrich a FocusItem with any application-specific
        information needed to restore it later.
        """
        pass

    @abstractmethod
    def restore(self, focus_item):
        pass
