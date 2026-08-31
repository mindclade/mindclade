import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from agent.v1 import tool_receipt_pb2 as _tool_receipt_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ToolReceiptCommitted(_message.Message):
    __slots__ = ("receipt", "run_receipt_sequence", "committed_at")
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    RUN_RECEIPT_SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    COMMITTED_AT_FIELD_NUMBER: _ClassVar[int]
    receipt: _tool_receipt_pb2.ToolReceipt
    run_receipt_sequence: int
    committed_at: _timestamp_pb2.Timestamp
    def __init__(self, receipt: _Optional[_Union[_tool_receipt_pb2.ToolReceipt, _Mapping]] = ..., run_receipt_sequence: _Optional[int] = ..., committed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
