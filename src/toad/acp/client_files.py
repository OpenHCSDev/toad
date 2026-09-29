"""The active ACP session owns project file effects."""
from toad import jsonrpc
from acp import schema
from .client_session import ClientRequestOwner


class FileClientRequestOwner(ClientRequestOwner):
    @jsonrpc.expose('fs/read_text_file')
    def read_text_file(self, sessionId: str, path: str, line: int | None = None,
                       limit: int | None = None) -> schema.ReadTextFileResponse:
        self.session_request(sessionId)
        read_path = self.agent.project_root_path / path
        try:
            text = read_path.read_text(encoding='utf-8', errors='ignore')
        except IOError:
            text = ''
        if line is not None:
            start = max(0, line - 1)
            end = None if limit is None else start + limit
            text = '\n'.join(text.splitlines()[start:end])
        return schema.ReadTextFileResponse(content=text)

    @jsonrpc.expose('fs/write_text_file')
    def write_text_file(self, sessionId: str, path: str, content: str) -> schema.WriteTextFileResponse:
        self.session_request(sessionId)
        write_path = self.agent.project_root_path / path
        write_path.write_text(content, encoding='utf-8', errors='ignore')
        return schema.WriteTextFileResponse()
