"""Transport-independent authenticated control messages."""
import json


class ControlProtocol:
    REQUEST_TOKEN = "request-token"
    REQUEST_STOP = "request-stop"
    MAX_MESSAGE = 4096
    CLIENT_TIMEOUT = 2.0

    def _dispatch(self, data: str) -> str:
        try:
            message = json.loads(data)
        except (ValueError, TypeError):
            message = None
        response = {"instance_id": self._instance_id}
        if not isinstance(message, dict):
            response["error"] = "invalid-request"
        elif message.get("expected_instance_id") != self._instance_id or not self._instance_id:
            response["error"] = "instance-mismatch"
        elif message.get("action") == self.REQUEST_TOKEN and self._token_provider:
            response["token"] = self._token_provider()
        elif message.get("action") == self.REQUEST_STOP:
            response["stopping"] = True
        else:
            response["error"] = "unknown-action"
        return json.dumps(response)

