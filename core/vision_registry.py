# core/vision_registry.py
from .vision_manager import VisionManager


class VisionRegistry:
    def __init__(self):
        self.instances = []  # List of VisionManager

    def add(self, manager: VisionManager):
        self.instances.append(manager)

    def unload_all(self):
        for manager in self.instances:
            manager.unload()
        self.instances.clear()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def get_count(self) -> int:
        return len(self.instances)

    def get_loaded_count(self) -> int:
        """Return the number of currently loaded (active) instances."""
        return sum(1 for mgr in self.instances if mgr.is_loaded())
