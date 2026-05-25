from data_plane.engine.outputs import Output
from data_plane.ports.channel_adapter import ChannelAdapter, ChannelCapabilities
from shared.domain.messages import InternalMessage


class MockChannelAdapter(ChannelAdapter):
    def __init__(
        self,
        preset_message: InternalMessage | None = None,
        verify_always: bool = True,
        caps: ChannelCapabilities | None = None,
    ) -> None:
        self._preset_message = preset_message
        self._verify_always = verify_always
        self._caps = caps or ChannelCapabilities(
            supports_interactive_buttons=True,
            supports_interactive_lists=True,
            max_buttons=3,
            max_list_rows=10,
        )
        self.sent: list[tuple[str, Output]] = []

    def receive(self, raw_payload: dict) -> InternalMessage | None:
        return self._preset_message

    def send(self, contact_id: str, output: Output) -> None:
        self.sent.append((contact_id, output))

    def verify_signature(self, body: bytes, signature_header: str) -> bool:
        return self._verify_always

    @property
    def capabilities(self) -> ChannelCapabilities:
        return self._caps
