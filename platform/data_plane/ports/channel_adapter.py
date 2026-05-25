from abc import ABC, abstractmethod
from dataclasses import dataclass

from data_plane.engine.outputs import Output
from shared.domain.messages import InternalMessage


@dataclass(frozen=True)
class ChannelCapabilities:
    supports_interactive_buttons: bool
    supports_interactive_lists: bool
    max_buttons: int
    max_list_rows: int


class ChannelAdapter(ABC):
    @abstractmethod
    def receive(self, raw_payload: dict) -> InternalMessage | None: ...

    @abstractmethod
    def send(self, contact_id: str, output: Output) -> None: ...

    @abstractmethod
    def verify_signature(self, body: bytes, signature_header: str) -> bool: ...

    @property
    @abstractmethod
    def capabilities(self) -> ChannelCapabilities: ...

    def close(self) -> None:
        pass
