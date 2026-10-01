"""Original filesystem context shared by live and archived rich history."""

from abc import ABC, abstractmethod
from pathlib import Path


class ProjectPathOwner(ABC):
    @property
    @abstractmethod
    def project_root(self) -> Path: ...
