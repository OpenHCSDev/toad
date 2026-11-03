"""External ACP responses for the picker, without replacing a Toad method."""

from acp.exceptions import RequestError
from acp.schema import NewSessionResponse, SessionConfigOptionSelect, SetSessionConfigOptionResponse

from base import Peer
from model_catalogue import GLM, catalogue


class ModelPickerPeer(Peer):
    def model(self, current: str) -> SessionConfigOptionSelect:
        return SessionConfigOptionSelect(
            id="model", name="Model", category="model", type="select",
            current_value=current, options=list(catalogue().values()))

    async def new_session(self, cwd: str, **kwargs):
        response = await super().new_session(cwd, **kwargs)
        return NewSessionResponse(session_id=response.session_id, config_options=[self.model(GLM)])

    async def set_config_option(self, config_id, session_id, value, **kwargs):
        assert config_id == "model" and session_id == self.session_id
        self.record(config_id=config_id, value=value)
        if value == "test/unavailable":
            raise RequestError(-32602, "Model unavailable")
        return SetSessionConfigOptionResponse(config_options=[self.model(value)])


if __name__ == "__main__":
    ModelPickerPeer.main()
