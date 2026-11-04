"""dmy 子进程替身：记录 argv，按预设返回 --json 输出，不碰真实治理记录。"""
from __future__ import annotations

import json
import subprocess


# 最小 capabilities 形状：含 actions 键即可让 negotiate_surface 正常判定。
_EMPTY_ACTIONS: dict = {}


class RecordingDmy:
    def __init__(self, data=None, error=None, returncode=0, raise_from=None, capabilities=None):
        self.data = {} if data is None else data
        self.error = error          # (code, message) 或 (code, message, details, next_action)
        self.returncode = returncode
        self.raise_from = raise_from
        self.capabilities = capabilities  # capabilities 命令返回的 data；None 则用最小形状
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if self.raise_from is not None:
            raise self.raise_from
        if self.error is not None:
            code, message, *rest = self.error
            details = rest[0] if len(rest) > 0 else {}
            next_action = rest[1] if len(rest) > 1 else None
            payload = {'schema_version': 1, 'tool_version': '0.1.0', 'error': {
                'code': code, 'message': message, 'details': details,
                'next_action': next_action}}
            return subprocess.CompletedProcess(cmd, 2, json.dumps(payload, ensure_ascii=False), '')
        data = self.data
        if 'capabilities' in cmd:
            data = self.capabilities if self.capabilities is not None else {
                'version': '0.1.0', 'contract_version': 2, 'actions': dict(_EMPTY_ACTIONS),
                'transitions': {}, 'error_codes': []}
        payload = {'schema_version': 1, 'tool_version': '0.1.0', 'data': data}
        return subprocess.CompletedProcess(cmd, self.returncode,
                                           json.dumps(payload, ensure_ascii=False), '')

    @property
    def last(self) -> list[str]:
        return self.calls[-1]

    def flags(self, name: str, index: int = -1) -> list[str]:
        """取最近一次调用里某个 --flag 的所有取值。"""
        argv = self.calls[index]
        return [argv[i + 1] for i, token in enumerate(argv[:-1]) if token == name]
