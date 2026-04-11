from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class AtomMessage(_message.Message):
    __slots__ = ("msg_id", "source", "target", "payload", "timestamp", "ttl", "meta")
    class MetaEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    MSG_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    TTL_FIELD_NUMBER: _ClassVar[int]
    META_FIELD_NUMBER: _ClassVar[int]
    msg_id: str
    source: str
    target: str
    payload: str
    timestamp: int
    ttl: int
    meta: _containers.ScalarMap[str, str]
    def __init__(self, msg_id: _Optional[str] = ..., source: _Optional[str] = ..., target: _Optional[str] = ..., payload: _Optional[str] = ..., timestamp: _Optional[int] = ..., ttl: _Optional[int] = ..., meta: _Optional[_Mapping[str, str]] = ...) -> None: ...

class Ack(_message.Message):
    __slots__ = ("ok", "msg_id", "error", "seq")
    OK_FIELD_NUMBER: _ClassVar[int]
    MSG_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    msg_id: str
    error: str
    seq: int
    def __init__(self, ok: bool = ..., msg_id: _Optional[str] = ..., error: _Optional[str] = ..., seq: _Optional[int] = ...) -> None: ...

class AtomAck(_message.Message):
    __slots__ = ("msg_id", "ok", "error", "server_ts")
    MSG_ID_FIELD_NUMBER: _ClassVar[int]
    OK_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    SERVER_TS_FIELD_NUMBER: _ClassVar[int]
    msg_id: str
    ok: bool
    error: str
    server_ts: int
    def __init__(self, msg_id: _Optional[str] = ..., ok: bool = ..., error: _Optional[str] = ..., server_ts: _Optional[int] = ...) -> None: ...
