# Fixes applied — Sep 2026

Three reported bugs, root-caused against the extracted submission and fixed
in place. Nothing existing was removed; every change fails soft to prior
behavior if a dependency (Simli/ElevenLabs/Ollama) is unavailable.

## 1. Classroom showed a generic looping avatar clip, unrelated to the lesson

**Root cause:** `templates/classroom.html` hardcoded
`<source src="/static/video/real_ai_teacher.mp4">` — a static filler clip.
That file is actually the raw *input* clip used by the separate `/video`
page's compositing pipeline (`video_generation_service.py`), not model
output. The live classroom never called any `/api/avatar/*` endpoint or
`simli_service.create_text_to_video_stream()`.

**Fix:**
- `orchestration/teacher_orchestrator.py`: new `_attach_avatar()` helper —
  best-effort TTS→Simli render of `teacher_output.spoken_text`, 25s timeout,
  never raises. Wired into every place a `TeacherOutput` is returned
  (teaching segments, questions, feedback, reteach/adaptation, Ask Teacher,
  Simplify).
- `schemas/session.py`: `TeacherOutput.avatar_video_url` / `avatar_status`.
- `templates/classroom.html` + `static/js/classroom.js`: the avatar
  `<video>` now has a stable idle loop (unchanged default) that gets swapped
  to the real generated clip (`updateAvatarVideo()`), unmuted, when one comes
  back, and reverts to the idle loop when playback ends or nothing was
  generated (missing keys, timeout, provider error).

**Trade-off to know about:** this generates the clip synchronously inside
the request (same pattern the existing `/video` page already uses), so a
"Next" click now takes as long as the TTS+Simli render. If that latency
becomes a UX problem, the next iteration is background generation + polling
instead of in-request generation.

## 2. Report showed 100% accuracy next to an F grade / low score

Two separate, real causes:

**(a) Grading reliability.** All answers — including MCQs, which have one
objectively correct option — were graded by asking the LLM to "semantically"
judge correctness. LLM graders are known to be lenient, especially on math:
confident-sounding wrong answers can get scored as correct.
**Fix:** `agents/evaluator_agent.py` now grades MCQs (and blank answers)
*deterministically* — exact match after normalization, no LLM call at all —
in both the in-lesson path (`evaluate()`) and the final-assessment path
(`evaluate_assessment_answer()`). Free-text answers still use the LLM, but
`prompts/evaluator.py` now has explicit anti-leniency grading rules (extract
the student's final result, compare it directly, confident tone ≠ correct).

**(b) Misleading report scope.** `accuracy_pct` was computed only from
in-lesson comprehension-check answers, while `final_score`/`grade` come only
from the separate final assessment (averaged across all quiz questions,
including unanswered ones as zero). These are different-sized pools shown
side by side as if directly comparable.
**Fix:** `api/students_reports.py` now computes `accuracy_pct` across BOTH
pools (same scope as `final_score`/`grade`), and returns `null` instead of a
misleading `0%`/`F` when the final assessment hasn't been taken yet.
`templates/report.html` renders that as "—" / "Not assessed".

## 3. "Ask Teacher" answered in a wall of raw, unrendered text

**Root cause:** `handle_ask()` called plain-text `ollama_service.generate()`
and stuffed the raw response into a `BoardType.text` block — never rendered
through KaTeX (hence literal `$...$` / `\frac{}{}` on screen) and never
spoken through the avatar.

**Fix:**
- `schemas/session.py`: new `BoardType.steps`.
- `prompts/teaching.py`: `build_ask_prompt()` asks Gemma for a SHORT spoken
  narration plus a separately structured board (`steps` for worked math,
  `formula`/`text`/`bullets`/`code` otherwise).
- `orchestration/teacher_orchestrator.py`: `handle_ask()` rewritten to use
  structured generation, attaches an avatar clip via `_attach_avatar()`.
- `static/js/classroom.js`: new `renderSteps()` (KaTeX-renders each step),
  and `submitAsk()` now routes the answer through the same avatar+board
  pipeline as a normal teaching segment instead of dumping text into the
  modal — the modal just shows a brief confirmation and gets out of the way.

## Also fixed: leaked credentials in `.env.example`

`.env.example` is explicitly un-ignored in `.gitignore` and contained real,
live-looking ElevenLabs/Simli/LiveKit API keys. Replaced with placeholders.
**If this repository has been pushed anywhere public, rotate those keys —
this fix does not undo an existing exposure.**

## What was NOT changed

- Session state machine, mastery formula, MongoDB schema, all page routes,
  document/RAG pipeline, lesson planning, dashboard — untouched.
- No new external dependency was added; the Simli/ElevenLabs calls now used
  by the classroom were already implemented in `simli_service.py`, just
  never called from the live teaching loop.

## Known limitation of this fix pass

Verified by: `python -m py_compile` on every touched file, a full import
smoke test of every touched module, and a standalone script exercising the
new deterministic MCQ/blank grading logic directly (all assertions pass —
see conversation for the test output). This environment has no running
MongoDB, Ollama, or reachable Simli/ElevenLabs endpoints, so the avatar
generation path and the full request/response cycle through FastAPI could
not be exercised end-to-end. Test this against your real `.env` before
relying on it, particularly the avatar latency/timeout behavior and the
`steps` JSON output from your actual Gemma model.
