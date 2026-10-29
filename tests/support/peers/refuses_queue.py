"""An external ACP peer refuses a queue request without losing the session."""

from acp.exceptions import RequestError

from base import Peer


class RefusesQueuePeer(Peer):
    async def prompt(self, session_id, prompt, **kwargs):
        self.record(prompt=prompt[0].text)
        raise RequestError.invalid_params({"details": "Queue action refused by peer"})


if __name__ == "__main__":
    RefusesQueuePeer.main()
