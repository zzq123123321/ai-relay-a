"""AI Relay role-based clipboard protocol."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import uuid4

V1_MARKER = "AI_RELAY/1"
BEGIN_MARKER = "----- AI_RELAY_BEGIN -----"
END_MARKER = "----- AI_RELAY_END -----"
COMPLETE_MARKER = "AI_RELAY_COMPLETE"
DEFAULT_MAX_ROUNDS = 100

SOURCE_CHATGPT = "CHATGPT"
SOURCE_EXECUTOR = "EXECUTOR"
TARGET_CHATGPT = "CHATGPT"
TARGET_EXECUTOR = "EXECUTOR"


class ProtocolError(ValueError):
    pass


class MessageType(str, Enum):
    TASK = "TASK"
    RESPONSE = "RESPONSE"
    DIAGNOSTIC = "DIAGNOSTIC"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class RelayMessage:
    message_id: str
    source: str
    target: str
    message_type: MessageType
    content: str
    format: str
    round_number: int = 0
    max_rounds: int = DEFAULT_MAX_ROUNDS


def parse(text: str) -> RelayMessage:
    normalized = text.replace("\r\n", "\n")
    if normalized.strip().startswith(V1_MARKER):
        return _parse_v1(normalized)
    if normalized.strip().startswith(BEGIN_MARKER):
        return _parse_legacy(normalized)
    raise ProtocolError("missing AI Relay marker")


def is_relay_text(text: str) -> bool:
    normalized = text.replace("\r\n", "\n").lstrip()
    return normalized.startswith(V1_MARKER + "\n") or normalized.startswith(
        BEGIN_MARKER + "\n"
    )


def is_complete(text: str) -> bool:
    """仅当整个网页回复等于结束标记时确认任务完成。"""
    return text.strip() == COMPLETE_MARKER


def wrap_task(
    content: str,
    task_id: str = "",
    round_number: int = 1,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> str:
    return _frame(
        source=SOURCE_CHATGPT,
        target=TARGET_EXECUTOR,
        message_type=MessageType.TASK,
        task_id=task_id or str(uuid4()),
        content=content,
        round_number=round_number,
        max_rounds=max_rounds,
    )


def wrap_response(
    content: str,
    task_id: str,
    round_number: int = 0,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> str:
    return _frame(
        source=SOURCE_EXECUTOR,
        target=TARGET_CHATGPT,
        message_type=MessageType.RESPONSE,
        task_id=task_id,
        content=content,
        round_number=round_number,
        max_rounds=max_rounds,
    )


def wrap_diagnostic_response(content: str, task_id: str) -> str:
    return _frame(
        source="AI_RELAY",
        target=TARGET_CHATGPT,
        message_type=MessageType.RESPONSE,
        task_id=task_id,
        content=content,
    )


def wrap_busy_error(task_id: str) -> str:
    return _frame(
        source=SOURCE_CHATGPT,
        target=TARGET_EXECUTOR,
        message_type=MessageType.ERROR,
        task_id=task_id,
        content="A_RELAY_BUSY: A端正在处理上一条执行结果。",
    )


def _frame(
    source: str,
    target: str,
    message_type: MessageType,
    task_id: str,
    content: str,
    round_number: int = 0,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> str:
    if not task_id.strip():
        raise ProtocolError("TASK_ID must not be empty")
    if not content.strip():
        raise ProtocolError("CONTENT must not be empty")
    if round_number < 0 or max_rounds < 1 or round_number > max_rounds:
        raise ProtocolError("invalid ROUND/MAX_ROUNDS")
    return "\n".join(
        (
            BEGIN_MARKER,
            f"SOURCE: {source}",
            f"TARGET: {target}",
            f"TYPE: {message_type.value}",
            f"TASK_ID: {task_id}",
            f"ROUND: {round_number}",
            f"MAX_ROUNDS: {max_rounds}",
            f"TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "CONTENT:",
            content,
            END_MARKER,
        )
    )


def _parse_legacy(text: str) -> RelayMessage:
    stripped = text.strip()
    if not stripped.endswith(END_MARKER):
        raise ProtocolError("missing AI_RELAY_END marker")
    payload = stripped[len(BEGIN_MARKER) : -len(END_MARKER)].strip("\n")
    return _parse_lines(payload.splitlines(), "legacy")


def _parse_v1(text: str) -> RelayMessage:
    header, separator, content = text.replace("\r\n", "\n").partition("\n\n")
    if not separator:
        raise ProtocolError("missing blank line before content")
    lines = header.splitlines()
    if not lines or lines[0].strip() != V1_MARKER:
        raise ProtocolError("invalid AI_RELAY/1 marker")
    fields = _headers(lines[1:])
    return _build_message(fields, content, "v1")


def _parse_lines(lines: list[str], format_name: str) -> RelayMessage:
    fields: dict[str, str] = {}
    content_lines: list[str] | None = None
    for line in lines:
        if content_lines is not None:
            content_lines.append(line)
            continue
        key, colon, value = line.partition(":")
        key = key.strip().upper()
        if not colon or not key:
            raise ProtocolError(f"invalid header: {line!r}")
        if key == "CONTENT":
            content_lines = [value.lstrip()] if value.strip() else []
            continue
        if key in fields:
            raise ProtocolError(f"duplicate header: {key}")
        fields[key] = value.strip()
    if content_lines is None:
        raise ProtocolError("missing CONTENT header")
    return _build_message(fields, "\n".join(content_lines), format_name)


def _headers(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in lines:
        key, colon, value = line.partition(":")
        key = key.strip().upper()
        if not colon or not key or not value.strip():
            raise ProtocolError(f"invalid header: {line!r}")
        if key in fields:
            raise ProtocolError(f"duplicate header: {key}")
        fields[key] = value.strip()
    return fields


def _build_message(fields: dict[str, str], content: str, format_name: str) -> RelayMessage:
    message_id = fields.get("MESSAGE_ID") or fields.get("TASK_ID")
    required = {
        "message id": message_id,
        "SOURCE": fields.get("SOURCE"),
        "TARGET": fields.get("TARGET"),
        "TYPE": fields.get("TYPE"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ProtocolError(f"missing headers: {', '.join(missing)}")
    if not content.strip():
        raise ProtocolError("CONTENT must not be empty")
    try:
        message_type = MessageType(fields["TYPE"].upper())
    except ValueError as exc:
        raise ProtocolError(f"unsupported TYPE: {fields['TYPE']}") from exc
    try:
        round_number = int(fields.get("ROUND", "0"))
        max_rounds = int(fields.get("MAX_ROUNDS", str(DEFAULT_MAX_ROUNDS)))
    except ValueError as exc:
        raise ProtocolError("ROUND and MAX_ROUNDS must be integers") from exc
    if round_number < 0 or max_rounds < 1 or round_number > max_rounds:
        raise ProtocolError("invalid ROUND/MAX_ROUNDS")
    return RelayMessage(
        message_id=message_id or "",
        source=fields["SOURCE"].upper(),
        target=fields["TARGET"].upper(),
        message_type=message_type,
        content=content.strip("\n"),
        format=format_name,
        round_number=round_number,
        max_rounds=max_rounds,
    )
