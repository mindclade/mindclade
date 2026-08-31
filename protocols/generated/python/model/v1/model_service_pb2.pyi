import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from common.v1 import pagination_pb2 as _pagination_pb2
from job.v1 import operation_pb2 as _operation_pb2
from model.v1 import model_pb2 as _model_pb2
from model.v1 import model_commands_pb2 as _model_commands_pb2
from model.v1 import model_release_pb2 as _model_release_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RegisterModelRequest(_message.Message):
    __slots__ = ("command",)
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    command: _model_commands_pb2.RegisterModelCommand
    def __init__(self, command: _Optional[_Union[_model_commands_pb2.RegisterModelCommand, _Mapping]] = ...) -> None: ...

class RegisterModelResponse(_message.Message):
    __slots__ = ("operation",)
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    operation: _operation_pb2.Operation
    def __init__(self, operation: _Optional[_Union[_operation_pb2.Operation, _Mapping]] = ...) -> None: ...

class GetModelRequest(_message.Message):
    __slots__ = ("name", "if_none_match")
    NAME_FIELD_NUMBER: _ClassVar[int]
    IF_NONE_MATCH_FIELD_NUMBER: _ClassVar[int]
    name: str
    if_none_match: str
    def __init__(self, name: _Optional[str] = ..., if_none_match: _Optional[str] = ...) -> None: ...

class GetModelResponse(_message.Message):
    __slots__ = ("model",)
    MODEL_FIELD_NUMBER: _ClassVar[int]
    model: _model_pb2.Model
    def __init__(self, model: _Optional[_Union[_model_pb2.Model, _Mapping]] = ...) -> None: ...

class ListModelsRequest(_message.Message):
    __slots__ = ("parent", "page", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page: _pagination_pb2.PageRequest
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page: _Optional[_Union[_pagination_pb2.PageRequest, _Mapping]] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListModelsResponse(_message.Message):
    __slots__ = ("models", "page", "read_time")
    MODELS_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    models: _containers.RepeatedCompositeFieldContainer[_model_pb2.Model]
    page: _pagination_pb2.PageResponse
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, models: _Optional[_Iterable[_Union[_model_pb2.Model, _Mapping]]] = ..., page: _Optional[_Union[_pagination_pb2.PageResponse, _Mapping]] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class RegisterModelReleaseRequest(_message.Message):
    __slots__ = ("command",)
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    command: _model_commands_pb2.RegisterModelReleaseCommand
    def __init__(self, command: _Optional[_Union[_model_commands_pb2.RegisterModelReleaseCommand, _Mapping]] = ...) -> None: ...

class RegisterModelReleaseResponse(_message.Message):
    __slots__ = ("operation",)
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    operation: _operation_pb2.Operation
    def __init__(self, operation: _Optional[_Union[_operation_pb2.Operation, _Mapping]] = ...) -> None: ...

class GetModelReleaseRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class GetModelReleaseResponse(_message.Message):
    __slots__ = ("model_release",)
    MODEL_RELEASE_FIELD_NUMBER: _ClassVar[int]
    model_release: _model_release_pb2.ModelRelease
    def __init__(self, model_release: _Optional[_Union[_model_release_pb2.ModelRelease, _Mapping]] = ...) -> None: ...

class ListModelReleasesRequest(_message.Message):
    __slots__ = ("parent", "page", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page: _pagination_pb2.PageRequest
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page: _Optional[_Union[_pagination_pb2.PageRequest, _Mapping]] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListModelReleasesResponse(_message.Message):
    __slots__ = ("model_releases", "page", "read_time")
    MODEL_RELEASES_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    model_releases: _containers.RepeatedCompositeFieldContainer[_model_release_pb2.ModelRelease]
    page: _pagination_pb2.PageResponse
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, model_releases: _Optional[_Iterable[_Union[_model_release_pb2.ModelRelease, _Mapping]]] = ..., page: _Optional[_Union[_pagination_pb2.PageResponse, _Mapping]] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class PromoteModelReleaseRequest(_message.Message):
    __slots__ = ("command",)
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    command: _model_commands_pb2.PromoteModelReleaseCommand
    def __init__(self, command: _Optional[_Union[_model_commands_pb2.PromoteModelReleaseCommand, _Mapping]] = ...) -> None: ...

class PromoteModelReleaseResponse(_message.Message):
    __slots__ = ("operation",)
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    operation: _operation_pb2.Operation
    def __init__(self, operation: _Optional[_Union[_operation_pb2.Operation, _Mapping]] = ...) -> None: ...

class RevokeModelReleaseRequest(_message.Message):
    __slots__ = ("command",)
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    command: _model_commands_pb2.RevokeModelReleaseCommand
    def __init__(self, command: _Optional[_Union[_model_commands_pb2.RevokeModelReleaseCommand, _Mapping]] = ...) -> None: ...

class RevokeModelReleaseResponse(_message.Message):
    __slots__ = ("operation",)
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    operation: _operation_pb2.Operation
    def __init__(self, operation: _Optional[_Union[_operation_pb2.Operation, _Mapping]] = ...) -> None: ...
