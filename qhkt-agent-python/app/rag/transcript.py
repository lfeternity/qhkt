from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptSegment:
    start_moment: int
    end_moment: int | None
    text: str


_TIME_RANGE = re.compile(
    r"(?m)^(?:\d+\s*\n)?\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})(?:[^\r\n]*)\n"
)
_STORED = re.compile(r"^\[\[(\d+):(-?\d*)\]\]\s*(.*)$")


def parse_subtitle(filename: str | None, content: str) -> list[TranscriptSegment]:
    extension = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if extension not in {"srt", "vtt", "txt"}:
        raise ValueError("字幕文件只支持 SRT、VTT 或 TXT")
    normalized = content.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    if extension == "txt":
        text = clean_text(normalized)
        if not text:
            raise ValueError("字幕内容不能为空")
        return [TranscriptSegment(0, None, text)]
    segments: list[TranscriptSegment] = []
    matches = list(_TIME_RANGE.finditer(normalized))
    for index, match in enumerate(matches):
        text_start = match.end()
        text_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        text = clean_text(normalized[text_start:text_end].replace("\n", " "))
        if text:
            segments.append(TranscriptSegment(_seconds(match, 1), _seconds(match, 5), text))
    validate_segments(segments)
    return segments


def encode_segments(segments: list[TranscriptSegment]) -> str:
    validate_segments(segments)
    return "\n".join(
        f"[[{item.start_moment}:{item.end_moment if item.end_moment is not None else ''}]] {item.text}"
        for item in segments
    )


def decode_segments(content: str) -> list[TranscriptSegment]:
    result: list[TranscriptSegment] = []
    for line in content.splitlines():
        match = _STORED.match(line.strip())
        if not match:
            continue
        end = match.group(2)
        result.append(TranscriptSegment(int(match.group(1)), int(end) if end else None, match.group(3).strip()))
    return result


def validate_segments(segments: list[TranscriptSegment]) -> None:
    if not segments:
        raise ValueError("未能从字幕文件解析出时间轴")
    if len(segments) > 10_000:
        raise ValueError("单个转写最多包含 10000 个片段")
    previous = -1
    for segment in segments:
        if not segment.text or segment.start_moment < 0 or segment.start_moment < previous:
            raise ValueError("转写时间轴顺序不正确")
        if segment.end_moment is not None and segment.end_moment < segment.start_moment:
            raise ValueError("转写结束时间不能早于开始时间")
        previous = segment.start_moment


def clean_text(value: str) -> str:
    value = re.sub(r"(?is)<script.*?>.*?</script>", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"[ \t]+", " ", value.replace("\x00", " ")).strip()


def _seconds(match: re.Match[str], offset: int) -> int:
    hours, minutes, seconds, millis = (int(match.group(offset + index)) for index in range(4))
    return hours * 3600 + minutes * 60 + seconds + (1 if millis >= 500 else 0)
