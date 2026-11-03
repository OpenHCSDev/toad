"""The rich surface that schedules context compaction and can explain refusal."""

from abc import abstractmethod

from agent_comms.acp_extension import CompactRequest
from textual.worker import Worker

from toad.native_node_meta import NativeNodeMeta
from toad.status_view import StatusView


class CompactionView(StatusView, metaclass=NativeNodeMeta):
    @abstractmethod
    def compact_context(self, request: CompactRequest) -> Worker[None]: ...
