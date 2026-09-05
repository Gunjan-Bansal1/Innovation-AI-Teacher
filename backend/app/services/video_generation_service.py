"""
Local lesson video generator.

Creates a topic/lesson-specific MP4 with a dynamic teaching board and a small
teacher video panel. This makes each generated video visibly match the user's
topic instead of simply replaying the same avatar clip.
"""
import asyncio
import hashlib
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from textwrap import shorten, wrap

from app.core.logging import get_logger

logger = get_logger(__name__)

APP_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = APP_DIR / "static"
SOURCE_VIDEO = STATIC_DIR / "video" / "simli_sample.mp4"
OUTPUT_DIR = STATIC_DIR / "generated_videos"

PALETTES = [
    {"bg": "0xF8FAFC", "accent": "0x2563EB", "soft": "0xDBEAFE", "dark": "0x0F172A"},
    {"bg": "0xF7FEE7", "accent": "0x16A34A", "soft": "0xDCFCE7", "dark": "0x14532D"},
    {"bg": "0xFFF7ED", "accent": "0xEA580C", "soft": "0xFED7AA", "dark": "0x431407"},
    {"bg": "0xFDF2F8", "accent": "0xDB2777", "soft": "0xFBCFE8", "dark": "0x500724"},
    {"bg": "0xF0FDFA", "accent": "0x0D9488", "soft": "0xCCFBF1", "dark": "0x134E4A"},
]


class VideoGenerationError(Exception):
    """Raised when a local lesson video cannot be generated."""


def _palette_for_topic(topic: str) -> dict[str, str]:
    digest = hashlib.sha1(topic.encode("utf-8")).hexdigest()
    return PALETTES[int(digest[:2], 16) % len(PALETTES)]


def _safe_drawtext(value: str) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = text.translate(str.maketrans({
        "'": "",
        "\u2018": "",
        "\u2019": "",
        "\u201c": '"',
        "\u201d": '"',
    }))
    text = text.replace("\\", "\\\\")
    text = text.replace(":", r"\:")
    text = text.replace(",", r"\,")
    text = text.replace(";", r"\;")
    text = text.replace("%", r"\%")
    return text


def _font_arg() -> str:
    return "font='Arial'"


def _enable_between(start: int, end: int) -> str:
    return f"enable=between(t\\,{start}\\,{end})"


def _segment_detail(segment: dict) -> str:
    return str(
        segment.get("description")
        or segment.get("example_description")
        or segment.get("analogy_description")
        or segment.get("diagram_description")
        or segment.get("graph_description")
        or segment.get("formula")
        or segment.get("question_type")
        or ""
    )


def _visual_hint(segment: dict, topic: str) -> str:
    segment_type = str(segment.get("type", "concept"))
    if segment_type == "formula":
        return str(segment.get("formula") or "Formula / key relationship")
    if segment_type == "code":
        return "Code flow -> input -> process -> output"
    if segment_type in {"diagram", "graph"}:
        return f"{topic} -> key parts -> how they connect"
    if segment_type == "question":
        return "Think -> Answer -> Teacher adapts"
    if segment_type == "summary":
        return "Revise weak points -> Practice -> Next topic"
    return f"{topic} -> Concept -> Example -> Check"


def _caption_for_segment(segment: dict, topic: str) -> dict[str, str]:
    segment_type = str(segment.get("type", "lesson")).replace("_", " ").title()
    title = str(segment.get("title") or topic or "Lesson")
    concept = str(segment.get("concept_key") or "").replace("_", " ").strip()
    detail = _segment_detail(segment)
    body = concept or detail or "A personalized explanation based on your selected topic."
    return {
        "type": segment_type,
        "title": shorten(title, width=58, placeholder="..."),
        "body": shorten(body, width=120, placeholder="..."),
        "visual": shorten(_visual_hint(segment, topic), width=92, placeholder="..."),
    }


def _build_timeline(segments: list[dict], topic: str, max_duration_seconds: int) -> tuple[list[dict], int]:
    fallback = [
        {"type": "introduction", "title": f"Welcome to {topic}", "duration_seconds": 8},
        {"type": "concept", "title": f"Core idea of {topic}", "duration_seconds": 8},
        {"type": "example", "title": f"Simple example for {topic}", "duration_seconds": 8},
        {"type": "question", "title": f"Check understanding of {topic}", "duration_seconds": 8},
        {"type": "summary", "title": f"Revise {topic}", "duration_seconds": 8},
    ]

    timeline = []
    cursor = 0
    usable_segments = segments or fallback
    for index, segment in enumerate(usable_segments, start=1):
        if cursor >= max_duration_seconds:
            break
        seconds = int(segment.get("duration_seconds") or 8)
        seconds = max(5, min(seconds, 14, max_duration_seconds - cursor))
        caption = _caption_for_segment(segment, topic)
        timeline.append({
            "index": index,
            "start": cursor,
            "end": cursor + seconds,
            **caption,
        })
        cursor += seconds

    return timeline, max(cursor, 5)


def _drawtext(text: str, x: int, y: int, size: int, color: str, start: int, end: int) -> str:
    return (
        f"drawtext={_font_arg()}:text='{_safe_drawtext(text)}':"
        f"x={x}:y={y}:fontsize={size}:fontcolor={color}:"
        f"{_enable_between(start, end)}"
    )


def _slide_filters(timeline: list[dict], topic: str, palette: dict[str, str]) -> list[str]:
    filters = [
        f"drawbox=x=0:y=0:w=1280:h=720:color={palette['bg']}:t=fill",
        f"drawbox=x=42:y=42:w=740:h=636:color=white@0.94:t=fill",
        f"drawbox=x=42:y=42:w=740:h=636:color={palette['accent']}:t=4",
        f"drawbox=x=830:y=40:w=410:h=300:color={palette['dark']}:t=fill",
        f"drawbox=x=830:y=372:w=410:h=188:color={palette['soft']}:t=fill",
        _drawtext(f"AI Teacher: {topic}", 76, 74, 30, palette["dark"], 0, 9999),
        _drawtext("Generated lesson video", 76, 118, 18, "0x475569", 0, 9999),
        _drawtext("Teacher video", 970, 350, 16, "0x475569", 0, 9999),
    ]

    for item in timeline:
        start = item["start"]
        end = item["end"]
        filters.append(
            f"drawbox=x=76:y=174:w=164:h=40:color={palette['accent']}:t=fill:"
            f"{_enable_between(start, end)}"
        )
        filters.append(_drawtext(item["type"], 96, 183, 18, "#FFFFFF", start, end))
        filters.append(_drawtext(item["title"], 76, 240, 34, palette["dark"], start, end))

        body_lines = wrap(item["body"], width=48)[:4]
        for line_index, line in enumerate(body_lines):
            filters.append(_drawtext(line, 76, 306 + (line_index * 34), 22, "0x334155", start, end))

        visual_lines = wrap(item["visual"], width=36)[:3]
        filters.append(_drawtext("Smart board visual", 862, 404, 20, palette["dark"], start, end))
        for line_index, line in enumerate(visual_lines):
            filters.append(_drawtext(line, 862, 448 + (line_index * 30), 19, "0x334155", start, end))

        filters.extend(_diagram_shape_filters(item["type"].lower(), item["visual"], palette, start, end))
        filters.append(_drawtext(f"Segment {item['index']} of {len(timeline)}", 76, 610, 18, "0x64748B", start, end))

    return filters


def _write_storyboard(path: Path, timeline: list[dict], topic: str) -> None:
    lines = [f"Topic: {topic}", ""]
    for item in timeline:
        lines.append(f"{item['start']:02}s-{item['end']:02}s | {item['type']} | {item['title']}")
        lines.append(f"  {item['body']}")
        lines.append(f"  Visual: {item['visual']}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _visual_storyboard_to_segments(storyboard: list[dict], topic: str, duration: int) -> list[dict]:
    if not storyboard:
        storyboard = [
            {"type": "flow", "title": f"{topic}: flow chart", "description": "Main idea -> key parts -> check"},
            {"type": "diagram", "title": "Concept diagram", "description": "Input -> process -> result"},
            {"type": "chart", "title": "Comparison chart", "description": "Definition, example, and common mistake"},
            {"type": "summary", "title": "Revision map", "description": "Remember, practice, and learn next"},
        ]

    seconds = max(6, duration // max(len(storyboard), 1))
    segments = []
    cursor = 0
    previous_end = 0
    for index, item in enumerate(storyboard):
        if cursor >= duration:
            break
        start = int(item.get("start", previous_end))
        end = int(item.get("end", start + seconds))
        start = max(0, min(start, duration - 1))
        end = max(start + 1, min(end, duration))
        previous_end = end
        labels = item.get("labels") or []
        label_text = " -> ".join(str(label) for label in labels[:4]) if labels else str(item.get("description") or "")
        segments.append({
            "type": str(item.get("type") or "visual").replace("_", " ").title(),
            "title": str(item.get("title") or topic),
            "body": str(item.get("description") or ""),
            "visual": label_text,
            "start": start,
            "end": end,
            "index": len(segments) + 1,
        })
        cursor = end
    return segments


def _visual_board_filters(timeline: list[dict], topic: str, palette: dict[str, str]) -> list[str]:
    filters = [
        "drawbox=x=0:y=0:w=1280:h=720:color=0xDCEFF2:t=fill",
        "drawbox=x=0:y=0:w=1280:h=92:color=0xB7DCE3@0.42:t=fill",
        "drawbox=x=0:y=628:w=1280:h=92:color=0xB7DCE3@0.34:t=fill",
        "drawbox=x=44:y=54:w=1192:h=612:color=0xEAFBFF@0.24:t=fill",
        "drawbox=x=44:y=54:w=1192:h=612:color=0xB9F6FF@0.78:t=3",
        "drawbox=x=82:y=104:w=330:h=468:color=0xF8FEFF@0.36:t=fill",
        "drawbox=x=82:y=104:w=330:h=468:color=0xB9F6FF@0.70:t=2",
        "drawbox=x=858:y=104:w=330:h=468:color=0xF8FEFF@0.30:t=fill",
        "drawbox=x=858:y=104:w=330:h=468:color=0xB9F6FF@0.64:t=2",
        "drawbox=x=486:y=44:w=308:h=12:color=0xFFFFFF@0.72:t=fill",
        "drawbox=x=0:y=0:w=8:h=720:color=0xA5F3FC@0.55:t=fill",
        "drawbox=x=1272:y=0:w=8:h=720:color=0xA5F3FC@0.55:t=fill",
        _drawtext(shorten(topic, width=34, placeholder="..."), 118, 132, 30, "0x0F172A", 0, 9999),
        _drawtext("Holographic teaching board", 904, 132, 18, "0x155E75", 0, 9999),
    ]

    for item in timeline:
        start = item["start"]
        end = item["end"]
        filters.append(
            f"drawbox=x=116:y=172:w=170:h=40:color=0x0EA5E9@0.82:t=fill:"
            f"{_enable_between(start, end)}"
        )
        filters.append(_drawtext(item["type"], 136, 181, 18, "#FFFFFF", start, end))
        filters.append(_drawtext(shorten(item["title"], width=26, placeholder="..."), 116, 240, 25, "0x0F172A", start, end))

        body_lines = wrap(item["body"], width=28)[:4]
        for line_index, line in enumerate(body_lines):
            filters.append(_drawtext(line, 116, 294 + (line_index * 30), 18, "0x334155", start, end))

        filters.extend(_hologram_shape_filters(item["type"].lower(), item["visual"], start, end))
        filters.append(_drawtext(f"Scene {item['index']} / {len(timeline)}", 922, 552, 18, "0x155E75", start, end))

    return filters


def _hologram_shape_filters(visual_type: str, label_text: str, start: int, end: int) -> list[str]:
    labels = [shorten(part.strip(), width=11, placeholder="...") for part in label_text.split("->") if part.strip()]
    while len(labels) < 3:
        labels.append(["Concept", "Example", "Check"][len(labels)])

    enable = _enable_between(start, end)
    pulse = _enable_between(start + 1, end)
    step_two = _enable_between(start + 2, end)
    scanner = _enable_between(start + 1, end)
    if "chart" in visual_type:
        return [
            f"drawbox=x=910:y=248:w=220:h=210:color=0xE0F7FA@0.58:t=fill:{enable}",
            f"drawbox=x=944:y='430-min(70\\,(t-{start})*30)':w=34:h='min(70\\,(t-{start})*30)':color=0x06B6D4@0.88:t=fill:{enable}",
            f"drawbox=x=1018:y='430-min(122\\,max(0\\,(t-{start}-0.8)*38))':w=34:h='min(122\\,max(0\\,(t-{start}-0.8)*38))':color=0x2563EB@0.82:t=fill:{enable}",
            f"drawbox=x=1092:y='430-min(52\\,max(0\\,(t-{start}-1.6)*26))':w=34:h='min(52\\,max(0\\,(t-{start}-1.6)*26))':color=0x10B981@0.82:t=fill:{step_two}",
            f"drawbox=x='920+mod((t-{start})*70\\,198)':y=238:w=30:h=5:color=0xFFFFFF@0.82:t=fill:{scanner}",
            _drawtext(labels[0], 924, 472, 14, "0x0F172A", start, end),
            _drawtext(labels[1], 998, 472, 14, "0x0F172A", start, end),
            _drawtext(labels[2], 1072, 472, 14, "0x0F172A", start, end),
        ]
    if "diagram" in visual_type:
        return [
            f"drawbox=x=908:y=268:w=84:h=54:color=0xCCFBF1@0.82:t=fill:{enable}",
            f"drawbox=x=1012:y=236:w=92:h=86:color=0xDBEAFE@0.80:t=fill:{pulse}",
            f"drawbox=x=1122:y=268:w=84:h=54:color=0xFEF3C7@0.84:t=fill:{step_two}",
            f"drawbox=x=1002:y=226:w=112:h=106:color=0x67E8F9@0.20:t=fill:{pulse}",
            _drawtext("-->", 994, 282, 20, "0x0891B2", start + 1, end),
            _drawtext("-->", 1106, 282, 20, "0x0891B2", start + 2, end),
            _drawtext(labels[0], 918, 290, 14, "0x0F172A", start, end),
            _drawtext(labels[1], 1020, 276, 14, "0x0F172A", start, end),
            _drawtext(labels[2], 1132, 290, 14, "0x0F172A", start, end),
        ]
    return [
        f"drawbox=x=910:y=282:w=78:h=50:color=0x06B6D4@0.84:t=fill:{enable}",
        f"drawbox=x=1018:y=282:w=78:h=50:color=0x3B82F6@0.82:t=fill:{pulse}",
        f"drawbox=x=1126:y=282:w=78:h=50:color=0x10B981@0.82:t=fill:{step_two}",
        f"drawbox=x='916+mod((t-{start})*82\\,260)':y=352:w=36:h=6:color=0xFFFFFF@0.88:t=fill:{scanner}",
        _drawtext("-->", 992, 298, 20, "0x0891B2", start + 1, end),
        _drawtext("-->", 1100, 298, 20, "0x0891B2", start + 2, end),
        _drawtext(labels[0], 920, 303, 13, "#FFFFFF", start, end),
        _drawtext(labels[1], 1028, 303, 13, "#FFFFFF", start + 1, end),
        _drawtext(labels[2], 1136, 303, 13, "#FFFFFF", start + 2, end),
    ]


def _diagram_shape_filters(visual_type: str, label_text: str, palette: dict[str, str], start: int, end: int) -> list[str]:
    labels = [shorten(part.strip(), width=14, placeholder="...") for part in label_text.split("->") if part.strip()]
    while len(labels) < 3:
        labels.append(["Input", "Process", "Result"][len(labels)])

    enable = _enable_between(start, end)
    pulse = _enable_between(start + 1, end)
    progress_one = _enable_between(start + 1, end)
    progress_two = _enable_between(start + 2, end)
    progress_three = _enable_between(start + 3, end)
    if "chart" in visual_type:
        return [
            f"drawbox=x=110:y=454:w=480:h=124:color=0xECFDF5:t=fill:{enable}",
            f"drawbox=x=166:y='578-min(66\\,(t-{start})*28)':w=44:h='min(66\\,(t-{start})*28)':color=0x10B981:t=fill:{enable}",
            f"drawbox=x=318:y='578-min(102\\,max(0\\,(t-{start}-0.8)*34))':w=44:h='min(102\\,max(0\\,(t-{start}-0.8)*34))':color=0x3B82F6:t=fill:{progress_one}",
            f"drawbox=x=470:y='578-min(46\\,max(0\\,(t-{start}-1.6)*28))':w=44:h='min(46\\,max(0\\,(t-{start}-1.6)*28))':color=0xF59E0B:t=fill:{progress_two}",
            f"drawbox=x='118+mod((t-{start})*80\\,430)':y=450:w=26:h=6:color={palette['accent']}@0.8:t=fill:{pulse}",
            _drawtext(labels[0], 142, 594, 16, "0x334155", start, end),
            _drawtext(labels[1], 294, 594, 16, "0x334155", start, end),
            _drawtext(labels[2], 446, 594, 16, "0x334155", start, end),
        ]
    if "diagram" in visual_type:
        return [
            f"drawbox=x=106:y=440:w=130:h=64:color=0xCCFBF1:t=fill:{enable}",
            f"drawbox=x=306:y=422:w=112:h=96:color=0xDBEAFE:t=fill:{progress_one}",
            f"drawbox=x=500:y=440:w=130:h=64:color=0xFEF3C7:t=fill:{progress_two}",
            f"drawbox=x=296:y=412:w=132:h=116:color={palette['accent']}@0.18:t=fill:{pulse}",
            _drawtext(labels[0], 132, 464, 17, "0x0F172A", start, end),
            _drawtext(labels[1], 328, 464, 17, "0x0F172A", start, end),
            _drawtext(labels[2], 526, 464, 17, "0x0F172A", start, end),
            _drawtext("-->", 252, 468, 24, "0x64748B", start + 1, end),
            _drawtext("-->", 446, 468, 24, "0x64748B", start + 2, end),
        ]
    return [
        f"drawbox=x=106:y=448:w=118:h=58:color=0x10B981:t=fill:{enable}",
        f"drawbox=x=310:y=448:w=118:h=58:color=0x3B82F6:t=fill:{progress_one}",
        f"drawbox=x=514:y=448:w=118:h=58:color=0x8B5CF6:t=fill:{progress_two}",
        f"drawbox=x='108+mod((t-{start})*96\\,408)':y=520:w=42:h=7:color={palette['accent']}@0.85:t=fill:{progress_three}",
        _drawtext(labels[0], 128, 470, 17, "#FFFFFF", start, end),
        _drawtext(labels[1], 332, 470, 17, "#FFFFFF", start + 1, end),
        _drawtext(labels[2], 536, 470, 17, "#FFFFFF", start + 2, end),
        _drawtext("-->", 248, 470, 24, "0x64748B", start + 1, end),
        _drawtext("-->", 452, 470, 24, "0x64748B", start + 2, end),
    ]


class VideoGenerationService:
    async def generate_visual_avatar_video(
        self,
        source_video_url: str,
        topic: str,
        visual_storyboard: list[dict],
        max_duration_seconds: int = 90,
    ) -> dict:
        """Compose a Simli avatar stream or MP4 with an in-video visual board."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise VideoGenerationError("ffmpeg is not installed or not available on PATH.")
        if not source_video_url:
            raise VideoGenerationError("Simli video URL is missing, so visual composition cannot run.")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        video_id = str(uuid.uuid4())
        output_path = OUTPUT_DIR / f"{video_id}.visual.mp4"
        storyboard_path = OUTPUT_DIR / f"{video_id}.visual.txt"

        duration = max(20, min(max_duration_seconds, 180))
        palette = _palette_for_topic(topic)
        timeline = _visual_storyboard_to_segments(visual_storyboard, topic, duration)
        _write_storyboard(storyboard_path, timeline, topic)

        slide_chain = ",".join(_visual_board_filters(timeline, topic, palette))
        filter_complex = (
            f"[1:v]{slide_chain}[board];"
            "[0:v]scale=430:520:force_original_aspect_ratio=increase,"
            "crop=430:520,setpts=PTS-STARTPTS[avatar];"
            "[board][avatar]overlay=x=425:y=118:shortest=1,format=yuv420p[v]"
        )

        cmd = [
            ffmpeg,
            "-y",
            "-protocol_whitelist",
            "file,http,https,tcp,tls,crypto",
            "-i",
            source_video_url,
            "-f",
            "lavfi",
            "-i",
            f"color=c={palette['bg']}:s=1280x720:r=30:d={duration}",
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-t",
            str(duration),
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(output_path),
        ]

        process = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(OUTPUT_DIR),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if process.returncode != 0:
            output_path.unlink(missing_ok=True)
            logger.error("ffmpeg visual avatar composition failed", extra={"stderr": process.stderr[-1000:]})
            raise VideoGenerationError(process.stderr[-800:] or "ffmpeg failed to compose visual avatar video.")

        return {
            "video_id": video_id,
            "status": "complete",
            "provider": "simli_static_audio_visual_mp4",
            "video_url": f"/static/generated_videos/{video_id}.visual.mp4",
            "storyboard_url": f"/static/generated_videos/{video_id}.visual.txt",
            "duration_seconds": duration,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "note": "Generated a Simli avatar video with diagrams and charts inside the MP4 frame.",
        }

    async def generate_lesson_video(
        self,
        lesson: dict,
        max_duration_seconds: int = 90,
    ) -> dict:
        """Generate a topic-specific MP4 preview for a planned lesson."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise VideoGenerationError("ffmpeg is not installed or not available on PATH.")
        if not SOURCE_VIDEO.exists():
            raise VideoGenerationError(f"Source teacher video not found: {SOURCE_VIDEO}")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        video_id = str(uuid.uuid4())
        output_path = OUTPUT_DIR / f"{video_id}.mp4"
        storyboard_path = OUTPUT_DIR / f"{video_id}.txt"

        topic = str(lesson.get("topic") or lesson.get("title") or "Lesson")
        lesson_duration = int(lesson.get("duration_seconds") or max_duration_seconds)
        duration = max(20, min(max_duration_seconds, lesson_duration, 180))
        timeline, actual_duration = _build_timeline(lesson.get("segments", []), topic, duration)
        palette = _palette_for_topic(topic)
        _write_storyboard(storyboard_path, timeline, topic)

        slide_chain = ",".join(_slide_filters(timeline, topic, palette))
        filter_complex = (
            f"[1:v]{slide_chain}[slides];"
            "[0:v]scale=410:300:force_original_aspect_ratio=increase,"
            "crop=410:300,setpts=PTS-STARTPTS[teacher];"
            "[slides][teacher]overlay=x=830:y=40:shortest=1,format=yuv420p[v]"
        )

        cmd = [
            ffmpeg,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(SOURCE_VIDEO),
            "-f",
            "lavfi",
            "-i",
            f"color=c={palette['bg']}:s=1280x720:r=30:d={actual_duration}",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-t",
            str(actual_duration),
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(output_path),
        ]

        logger.info("Generating topic-specific lesson video", extra={"lesson_id": lesson.get("_id"), "video_id": video_id})
        process = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(OUTPUT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if process.returncode != 0:
            storyboard_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            logger.error("ffmpeg video generation failed", extra={"stderr": process.stderr[-1000:]})
            raise VideoGenerationError(process.stderr[-800:] or "ffmpeg failed to generate video.")

        return {
            "video_id": video_id,
            "status": "complete",
            "provider": "local_ffmpeg_storyboard",
            "video_url": f"/static/generated_videos/{video_id}.mp4",
            "storyboard_url": f"/static/generated_videos/{video_id}.txt",
            "duration_seconds": actual_duration,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "note": "Generated a topic-specific teaching video with dynamic board visuals and teacher video panel.",
        }


video_generation_service = VideoGenerationService()
