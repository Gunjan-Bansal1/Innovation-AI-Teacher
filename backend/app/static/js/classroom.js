/**
 * classroom.js — Core classroom session state machine
 *
 * Handles:
 * - Session polling and state management
 * - Smart Board rendering (Mermaid, formula, code, text)
 * - Teacher spoken text display
 * - Student answer submission → adaptive loop
 * - Language switching
 * - Ask/Repeat/Simplify controls
 */

// Initialize Mermaid
mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' });

const sessionId = localStorage.getItem('session_id');
const lessonInfo = JSON.parse(localStorage.getItem('lesson_info') || '{}');
let isPaused = false;
let currentStatus = 'teaching';
let currentLanguage = lessonInfo.language || 'english';
let currentSpokenText = '';
let currentSpokenAudio = null;
let selectedMCQAnswer = null;
let answerStartTime = Date.now();

// ── On load ────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  if (!sessionId) {
    window.location.href = '/';
    return;
  }

  // Populate lesson info
  document.getElementById('lesson-topic').textContent = lessonInfo.topic || lessonInfo.title || 'Lesson';

  // Load initial state and start teaching
  loadState().then(() => {
    if (currentStatus === 'teaching') {
      nextSegment();
    }
  });
});

// ── State management ────────────────────────────────────────────────────────

async function loadState() {
  try {
    const resp = await fetch(`/api/sessions/${sessionId}/state`);
    if (!resp.ok) return;
    const state = await resp.json();
    applyState(state);
  } catch (e) {
    console.error('State load error:', e);
  }
}

function applyState(state) {
  currentStatus = state.status;
  if (state.language) {
    currentLanguage = state.language;
    highlightLanguageBtn(currentLanguage);
  }
  updateTopBar(state);
  updateMasteryPanel(state.mastery_snapshot || {});
  updateStatusBadge(state.status);

  // Show adaptation message
  if (state.adaptation_message) {
    showAdaptationBanner(state.adaptation_message);
  }

  // Handle panels based on status
  switch (state.status) {
    case 'teaching':
    case 'adapting':
      showPanel('next');
      if (state.teacher_output) applyTeacherOutput(state.teacher_output);
      break;
    case 'waiting_for_answer':
      if (state.current_question) renderQuestion(state.current_question);
      if (state.teacher_output) applyTeacherOutput(state.teacher_output);
      break;
    case 'assessment':
      showPanel('assessment');
      break;
    case 'completed':
      showPanel('completed');
      break;
  }
}

// ── Next segment ─────────────────────────────────────────────────────────────

async function nextSegment() {
  if (isPaused) return;
  stopCurrentSpeechAndVideo();
  currentSpokenText = '';

  const spokenEl = document.getElementById('spoken-text');
  if (spokenEl) {
    spokenEl.innerHTML = '<span class="text-indigo-600 font-medium animate-pulse">⏳ AI Teacher is preparing the next segment...</span>';
  }
  const hintEl = document.getElementById('next-hint');
  if (hintEl) {
    hintEl.textContent = 'Preparing next concept...';
  }

  setNextLoading(true);

  try {
    const resp = await fetch(`/api/sessions/${sessionId}/next`, { method: 'POST' });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      showError(err.detail || 'Error advancing lesson');
      return;
    }
    const state = await resp.json();
    applyState(state);
  } catch (e) {
    showError('Network error. Please try again.');
  } finally {
    setNextLoading(false);
  }
}

// ── Answer submission ──────────────────────────────────────────────────────────

async function submitAnswer() {
  stopCurrentSpeechAndVideo();
  currentSpokenText = '';

  const answer = selectedMCQAnswer || document.getElementById('answer-input').value.trim();
  if (!answer) {
    document.getElementById('answer-input').classList.add('border-red-400');
    return;
  }

  const timeTaken = Math.round((Date.now() - answerStartTime) / 1000);
  setAnswerLoading(true);

  const spokenEl = document.getElementById('spoken-text');
  if (spokenEl) {
    spokenEl.innerHTML = '<span class="text-indigo-600 font-medium animate-pulse">🔍 Evaluating your answer...</span>';
  }

  try {
    const resp = await fetch(`/api/sessions/${sessionId}/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer, time_taken_seconds: timeTaken })
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      showError(err.detail || 'Error evaluating answer');
      return;
    }
    const state = await resp.json();

    // Reset answer state
    selectedMCQAnswer = null;
    document.getElementById('answer-input').value = '';
    answerStartTime = Date.now();

    applyState(state);
  } catch (e) {
    showError('Network error submitting answer');
  } finally {
    setAnswerLoading(false);
  }
}

function handleAnswerKeydown(e) {
  if (e.key === 'Enter' && e.ctrlKey) {
    submitAnswer();
  }
}

// ── Teacher output rendering ─────────────────────────────────────────────────

function applyTeacherOutput(output) {
  // Stop previous media cleanly
  stopCurrentSpeechAndVideo();

  // Render spoken explanation text with typewriter effect
  setSpokenText(output.spoken_text || '');

  // Render Smart Board
  if (output.board) {
    renderBoard(output.board);
  } else {
    clearBoard();
  }

  // Play Simli video clip or Edge-TTS speech narration
  startAvatarPlayback(output);

  // Update segment title label
  if (output.segment_title) {
    document.getElementById('next-hint').textContent =
      output.segment_type === 'question' ? 'Answer the question above' :
      `Segment: ${output.segment_title}`;
  }
}

// ── Avatar video & Audio narration ──────────────────────────────────────────

let hlsInstance = null;
let audioContextUnlocked = false;
let currentSpeechId = 0;
let typewriterTimer = null;

// Pre-unlock audio context on user interaction
function ensureAudioUnlocked() {
  if (audioContextUnlocked) return;
  try {
    const silentAudio = new Audio('data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA');
    silentAudio.play().then(() => {
      audioContextUnlocked = true;
    }).catch(() => {});
  } catch (e) {}
}
document.addEventListener('click', ensureAudioUnlocked, { once: false });

function stopAudioOnly() {
  currentSpeechId++; // Invalidate any in-flight speech requests or callbacks

  if (currentSpokenAudio) {
    try {
      currentSpokenAudio.pause();
      currentSpokenAudio.currentTime = 0;
      currentSpokenAudio.removeAttribute('src');
      currentSpokenAudio.load();
    } catch (e) {}
    currentSpokenAudio = null;
  }

  if (window.speechSynthesis) {
    try {
      window.speechSynthesis.cancel();
    } catch (e) {}
  }
}

function stopCurrentSpeechAndVideo() {
  stopAudioOnly();

  if (typewriterTimer) {
    clearTimeout(typewriterTimer);
    typewriterTimer = null;
  }

  if (hlsInstance) {
    try {
      hlsInstance.destroy();
    } catch (e) {}
    hlsInstance = null;
  }

  const video = document.getElementById('avatar-video');
  if (video) {
    try {
      video.pause();
    } catch (e) {}
  }

  showSpeakingIndicator(false);
}

function playSimliAvatarVideo(shouldLoop = true) {
  const videoContainer = document.getElementById('avatar-video-container');
  const cardDisplay = document.getElementById('avatar-card-display');
  const video = document.getElementById('avatar-video');
  if (!video || !videoContainer) return;

  if (cardDisplay) cardDisplay.classList.add('hidden');
  videoContainer.classList.remove('hidden');

  if (!video.src || !video.src.includes('simli_sample.mp4')) {
    video.src = '/static/video/simli_sample.mp4';
  }
  video.loop = shouldLoop;
  video.muted = true; // Video is muted so only clean TTS voice audio is heard
  video.play().catch(() => {});
}

function pauseSimliAvatarVideo() {
  const video = document.getElementById('avatar-video');
  if (video) {
    try {
      video.pause();
    } catch (e) {}
  }
}

function startAvatarPlayback(output) {
  stopAudioOnly();

  const videoContainer = document.getElementById('avatar-video-container');
  const cardDisplay = document.getElementById('avatar-card-display');
  const video = document.getElementById('avatar-video');

  currentSpokenText = (output.spoken_text || '').trim();
  const videoUrl = output.avatar_video_url;
  const thisSpeechId = currentSpeechId;

  let videoPlayStarted = false;
  let fallbackTimer = null;

  function fallbackToAudio() {
    if (fallbackTimer) { clearTimeout(fallbackTimer); fallbackTimer = null; }
    if (thisSpeechId !== currentSpeechId) return;
    if (currentSpokenText) {
      playSpokenAudio(currentSpokenText, currentLanguage);
    }
  }

  if (videoUrl && video && videoContainer) {
    if (cardDisplay) cardDisplay.classList.add('hidden');
    videoContainer.classList.remove('hidden');
    showSpeakingIndicator(true, 'Explaining with video...');

    fallbackTimer = setTimeout(() => {
      if (!videoPlayStarted && thisSpeechId === currentSpeechId) {
        console.warn('Video playback timed out, switching to voice audio.');
        fallbackToAudio();
      }
    }, 3000);

    video.onplaying = () => {
      videoPlayStarted = true;
      if (fallbackTimer) { clearTimeout(fallbackTimer); fallbackTimer = null; }
      if (thisSpeechId === currentSpeechId) {
        showSpeakingIndicator(true, 'Explaining with video...');
      }
    };

    video.onerror = () => {
      fallbackToAudio();
    };

    video.onended = () => {
      if (thisSpeechId === currentSpeechId) {
        showSpeakingIndicator(false);
        pauseSimliAvatarVideo();
      }
    };

    try {
      if (videoUrl.includes('.m3u8') && window.Hls && Hls.isSupported()) {
        hlsInstance = new Hls();
        hlsInstance.loadSource(videoUrl);
        hlsInstance.attachMedia(video);
        hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
          if (thisSpeechId !== currentSpeechId) return;
          video.play().catch(() => {
            video.muted = true;
            video.play().catch(() => fallbackToAudio());
          });
        });
        hlsInstance.on(Hls.Events.ERROR, () => {
          fallbackToAudio();
        });
      } else {
        video.src = videoUrl;
        video.loop = false;
        video.muted = false;
        video.load();
        const p = video.play();
        if (p && p.catch) {
          p.catch(() => {
            video.muted = true;
            video.play().catch(() => fallbackToAudio());
          });
        }
      }
    } catch (e) {
      fallbackToAudio();
    }
  } else {
    // Synchronized Simli avatar video + natural voice narration
    if (currentSpokenText) {
      playSpokenAudio(currentSpokenText, currentLanguage);
    } else {
      showSpeakingIndicator(false);
      pauseSimliAvatarVideo();
    }
  }
}

function playSpokenAudio(text, lang) {
  if (!text) return;
  stopAudioOnly();

  const speechId = ++currentSpeechId;
  const selectedLang = lang || currentLanguage || 'english';

  showSpeakingIndicator(true, 'Explaining concept...');

  const audioUrl = `/api/avatar/speech?text=${encodeURIComponent(text)}&language=${encodeURIComponent(selectedLang)}`;
  const audio = new Audio(audioUrl);
  currentSpokenAudio = audio;

  let fallbackAttempted = false;

  function doFallback() {
    if (fallbackAttempted || speechId !== currentSpeechId) return;
    fallbackAttempted = true;
    if (currentSpokenAudio === audio) {
      try {
        audio.pause();
        audio.removeAttribute('src');
        audio.load();
      } catch (e) {}
      currentSpokenAudio = null;
    }
    speakWithBrowserSynthesis(text, selectedLang, speechId);
  }

  audio.onplay = () => {
    if (speechId !== currentSpeechId) {
      try { audio.pause(); audio.src = ''; } catch (e) {}
      return;
    }
    showSpeakingIndicator(true, 'Explaining concept...');
    playSimliAvatarVideo(true);
  };

  audio.onended = () => {
    if (speechId === currentSpeechId) {
      showSpeakingIndicator(false);
      pauseSimliAvatarVideo();
      currentSpokenAudio = null;
    }
  };

  audio.onerror = () => {
    doFallback();
  };

  const playPromise = audio.play();
  if (playPromise && playPromise.catch) {
    playPromise.catch((err) => {
      if (speechId === currentSpeechId) {
        doFallback();
      }
    });
  }
}

function speakWithBrowserSynthesis(text, lang, speechId) {
  if (speechId !== currentSpeechId || !window.speechSynthesis) {
    showSpeakingIndicator(false);
    return;
  }
  try {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.05;

    const lowerLang = (lang || 'english').toLowerCase();
    if (lowerLang === 'hindi') {
      utterance.lang = 'hi-IN';
    } else {
      utterance.lang = 'en-US';
    }

    utterance.onstart = () => {
      if (speechId === currentSpeechId) {
        showSpeakingIndicator(true, 'Explaining concept...');
        playSimliAvatarVideo(true);
      }
    };
    utterance.onend = () => {
      if (speechId === currentSpeechId) {
        showSpeakingIndicator(false);
        pauseSimliAvatarVideo();
      }
    };
    utterance.onerror = () => {
      if (speechId === currentSpeechId) {
        showSpeakingIndicator(false);
        pauseSimliAvatarVideo();
      }
    };

    window.speechSynthesis.speak(utterance);
  } catch (e) {
    showSpeakingIndicator(false);
    pauseSimliAvatarVideo();
  }
}

function replaySpokenAudio() {
  if (currentSpokenText) {
    ensureAudioUnlocked();
    playSpokenAudio(currentSpokenText, currentLanguage);
  }
}

function setSpokenText(text) {
  const el = document.getElementById('spoken-text');
  if (!el) return;
  const cleanText = (text || '').trim();
  if (!cleanText) {
    el.innerHTML = '<span class="text-slate-400 italic">No explanation for this segment.</span>';
    return;
  }

  // Ensure full explanation text is completely displayed
  const paragraphs = cleanText.split(/\n+/).filter(p => p.trim());
  if (paragraphs.length > 1) {
    el.innerHTML = paragraphs.map(p => `<p class="mb-2 leading-relaxed text-slate-700">${escapeHtml(p)}</p>`).join('');
  } else {
    el.textContent = cleanText;
  }
}

// ── Smart Board Rendering ────────────────────────────────────────────────────

function renderBoard(board) {
  const container = document.getElementById('board-content');
  const typeLabel = document.getElementById('board-type-label');
  typeLabel.textContent = board.type?.toUpperCase() || '';

  switch (board.type) {
    case 'formula':
      renderFormula(container, board);
      break;
    case 'steps':
      renderSteps(container, board);
      break;
    case 'mermaid':
      renderMermaid(container, board);
      break;
    case 'code':
      renderCode(container, board);
      break;
    case 'bullets':
    case 'key_takeaways':
      renderBullets(container, board);
      break;
    case 'timeline':
      renderTimeline(container, board);
      break;
    case 'table':
      renderTable(container, board);
      break;
    default:
      renderText(container, board);
  }
}

function renderFormula(container, board) {
  const caption = board.caption || 'Formula';
  container.innerHTML = `
    <div class="text-center py-8">
      <p class="text-xs text-slate-400 uppercase tracking-wide mb-6">${caption}</p>
      <div id="katex-render" class="text-4xl font-bold text-slate-800 py-6 px-8 bg-gradient-to-r from-indigo-50 to-violet-50 rounded-2xl border border-indigo-200 inline-block">
        ${escapeHtml(board.content)}
      </div>
    </div>`;
  // Try KaTeX rendering
  try {
    const el = document.getElementById('katex-render');
    katex.render(board.content, el, { throwOnError: false, displayMode: true });
  } catch(e) {
    // fallback already shown
  }
}

function renderSteps(container, board) {
  // board.content is a JSON array of { label, expression }.
  let steps = [];
  try {
    const parsed = typeof board.content === 'string' ? JSON.parse(board.content) : board.content;
    steps = Array.isArray(parsed) ? parsed : [];
  } catch {
    // Model didn't return valid JSON — fall back to plain text rather than
    // showing raw braces/JSON syntax to the student.
    renderText(container, board);
    return;
  }
  if (!steps.length) {
    renderText(container, board);
    return;
  }

  container.innerHTML = `
    <div class="py-4">
      ${board.caption ? `<p class="text-xs text-slate-400 uppercase tracking-wide mb-4">${board.caption}</p>` : ''}
      <ol class="space-y-4">
        ${steps.map((s, i) => `
          <li class="flex items-start gap-3">
            <span class="shrink-0 w-6 h-6 rounded-full bg-indigo-100 text-indigo-600 text-xs font-bold flex items-center justify-center mt-0.5">${i + 1}</span>
            <div class="min-w-0 flex-1">
              <p class="text-xs text-slate-500 mb-1">${escapeHtml(s.label || '')}</p>
              <div class="katex-step text-lg text-slate-800 bg-slate-50 rounded-lg px-3 py-2 border border-slate-100 overflow-x-auto" id="katex-step-${i}"></div>
            </div>
          </li>`).join('')}
      </ol>
    </div>`;

  steps.forEach((s, i) => {
    const el = document.getElementById(`katex-step-${i}`);
    if (!el) return;
    try {
      katex.render(s.expression || '', el, { throwOnError: false, displayMode: false });
    } catch (e) {
      el.textContent = s.expression || '';
    }
  });
}

function renderMermaid(container, board) {
  const id = 'mermaid-' + Date.now();
  container.innerHTML = `
    <div class="py-4">
      ${board.caption ? `<p class="text-xs text-slate-400 text-center mb-4">${board.caption}</p>` : ''}
      <div class="mermaid-wrapper overflow-auto">
        <div class="mermaid" id="${id}">${board.content}</div>
      </div>
    </div>`;
  mermaid.run({ nodes: [document.getElementById(id)] }).catch(e => {
    document.getElementById(id).innerHTML =
      `<pre class="text-xs text-slate-500 whitespace-pre-wrap">${escapeHtml(board.content)}</pre>`;
  });
}

function renderCode(container, board) {
  const lang = board.language || 'python';
  container.innerHTML = `
    <div class="py-2">
      ${board.caption ? `<p class="text-xs text-slate-400 mb-3">${board.caption}</p>` : ''}
      <div class="bg-slate-900 rounded-xl overflow-hidden">
        <div class="px-4 py-2 bg-slate-800 flex items-center gap-2">
          <div class="w-2.5 h-2.5 rounded-full bg-red-400"></div>
          <div class="w-2.5 h-2.5 rounded-full bg-amber-400"></div>
          <div class="w-2.5 h-2.5 rounded-full bg-emerald-400"></div>
          <span class="text-slate-400 text-xs ml-2">${lang}</span>
        </div>
        <pre class="text-emerald-300 text-sm p-5 overflow-x-auto leading-relaxed font-mono"><code>${escapeHtml(board.content)}</code></pre>
      </div>
    </div>`;
}

function renderBullets(container, board) {
  let items = [];
  try {
    const parsed = typeof board.content === 'string' ? JSON.parse(board.content) : board.content;
    items = Array.isArray(parsed) ? parsed : [board.content];
  } catch { items = [board.content]; }

  container.innerHTML = `
    <div class="py-4">
      ${board.caption ? `<p class="text-xs text-slate-400 uppercase tracking-wide mb-4">${board.caption}</p>` : ''}
      <ul class="space-y-3">
        ${items.map(item => `
          <li class="flex items-start gap-3 p-3 bg-indigo-50 rounded-xl border border-indigo-100">
            <div class="w-2 h-2 bg-indigo-500 rounded-full mt-1.5 shrink-0"></div>
            <span class="text-slate-700 text-sm leading-relaxed">${escapeHtml(String(item))}</span>
          </li>`).join('')}
      </ul>
    </div>`;
}

function renderTimeline(container, board) {
  let events = [];
  try {
    events = JSON.parse(board.content);
  } catch { events = [{ year: '', event: board.content }]; }

  container.innerHTML = `
    <div class="py-4">
      ${board.caption ? `<p class="text-xs text-slate-400 uppercase tracking-wide mb-4">${board.caption}</p>` : ''}
      <div class="relative pl-6 border-l-2 border-indigo-200 space-y-4">
        ${(Array.isArray(events) ? events : []).map(e => `
          <div class="relative">
            <div class="absolute -left-[25px] w-4 h-4 bg-indigo-500 rounded-full border-2 border-white"></div>
            ${e.year ? `<p class="text-xs font-bold text-indigo-600 mb-0.5">${e.year}</p>` : ''}
            <p class="text-sm text-slate-700">${escapeHtml(e.event || String(e))}</p>
          </div>`).join('')}
      </div>
    </div>`;
}

function renderTable(container, board) {
  // Render markdown table or plain text
  container.innerHTML = `
    <div class="py-4 overflow-x-auto">
      ${board.caption ? `<p class="text-xs text-slate-400 mb-3">${board.caption}</p>` : ''}
      <div class="prose prose-sm max-w-none text-slate-700 text-sm whitespace-pre-wrap font-mono">${escapeHtml(board.content)}</div>
    </div>`;
}

function renderText(container, board) {
  container.innerHTML = `
    <div class="py-4">
      ${board.caption ? `<p class="text-xs text-slate-400 uppercase tracking-wide mb-4">${board.caption}</p>` : ''}
      <div class="text-slate-700 text-sm leading-relaxed whitespace-pre-wrap">${escapeHtml(board.content)}</div>
    </div>`;
}

function clearBoard() {
  document.getElementById('board-content').innerHTML =
    '<div class="text-center text-slate-300 py-10"><p class="text-sm">Smart Board</p></div>';
  document.getElementById('board-type-label').textContent = '';
}

// ── Question rendering ─────────────────────────────────────────────────────

function renderQuestion(question) {
  showPanel('question');
  document.getElementById('question-text').textContent = question.question_text;
  answerStartTime = Date.now();
  selectedMCQAnswer = null;

  const mcqContainer = document.getElementById('mcq-options');
  const textSection = document.getElementById('text-answer-section');

  if (question.options && question.options.length > 0) {
    mcqContainer.classList.remove('hidden');
    mcqContainer.innerHTML = '';
    question.options.forEach(opt => {
      const div = document.createElement('div');
      div.innerHTML = `
        <button onclick="selectMCQ(this, '${escapeHtml(opt)}')"
                class="mcq-option w-full text-left px-4 py-3 rounded-xl border border-slate-200 text-sm text-slate-700 hover:border-indigo-400 hover:bg-indigo-50 transition-all">
          ${escapeHtml(opt)}
        </button>`;
      mcqContainer.appendChild(div);
    });
    textSection.querySelector('textarea').value = '';
  } else {
    mcqContainer.classList.add('hidden');
    textSection.querySelector('textarea').focus();
  }

  // Render question on board too
  renderBoard({
    type: 'text',
    content: question.question_text,
    caption: `❓ ${question.question_type?.replace(/_/g, ' ')} — ${question.concept_key?.replace(/_/g, ' ')}`
  });
}

function selectMCQ(btn, value) {
  selectedMCQAnswer = value;
  document.getElementById('answer-input').value = value;
  document.querySelectorAll('.mcq-option').forEach(b => {
    b.classList.remove('border-indigo-500', 'bg-indigo-50', 'text-indigo-700');
    b.classList.add('border-slate-200', 'text-slate-700');
  });
  btn.classList.remove('border-slate-200', 'text-slate-700');
  btn.classList.add('border-indigo-500', 'bg-indigo-50', 'text-indigo-700');
}

// ── UI helpers ─────────────────────────────────────────────────────────────

function showPanel(name) {
  const panels = ['next', 'question', 'assessment', 'completed'];
  panels.forEach(p => {
    const el = document.getElementById(`${p}-panel`) ||
               document.getElementById(`${p === 'assessment' ? 'assessment-trigger' : p}-panel`);
    if (el) el.classList.add('hidden');
  });

  const targetId = name === 'assessment' ? 'assessment-trigger-panel' : `${name}-panel`;
  const target = document.getElementById(targetId);
  if (target) target.classList.remove('hidden');
}

function updateTopBar(state) {
  const conceptLabel = document.getElementById('current-concept-label');
  if (state.current_concept) {
    conceptLabel.textContent = state.current_concept.replace(/_/g, ' ');
  }
  const bar = document.getElementById('progress-bar');
  const pct = document.getElementById('progress-pct');
  if (bar) bar.style.width = (state.progress_pct || 0) + '%';
  if (pct) pct.textContent = Math.round(state.progress_pct || 0) + '%';
}

function updateStatusBadge(status) {
  const badge = document.getElementById('status-badge');
  const labels = {
    teaching: '📖 Teaching',
    waiting_for_answer: '❓ Question',
    evaluating: '🔍 Evaluating',
    adapting: '🔄 Adapting',
    reteaching: '🔄 Re-teaching',
    assessment: '🎓 Assessment',
    completed: '✅ Complete',
    paused: '⏸ Paused',
  };
  const colors = {
    teaching: 'bg-blue-100 text-blue-700',
    waiting_for_answer: 'bg-rose-100 text-rose-700',
    evaluating: 'bg-amber-100 text-amber-700',
    adapting: 'bg-purple-100 text-purple-700',
    assessment: 'bg-violet-100 text-violet-700',
    completed: 'bg-emerald-100 text-emerald-700',
  };
  badge.textContent = labels[status] || status;
  badge.className = `px-2 py-0.5 rounded-full text-xs font-semibold ${colors[status] || 'bg-slate-100 text-slate-600'}`;
}

function updateMasteryPanel(mastery) {
  const panel = document.getElementById('mastery-panel');
  if (!mastery || Object.keys(mastery).length === 0) return;

  panel.innerHTML = '';
  Object.entries(mastery).forEach(([key, val]) => {
    const pct = Math.round(val * 100);
    const barColor = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-rose-500';
    const div = document.createElement('div');
    div.innerHTML = `
      <div class="flex items-center justify-between mb-1">
        <span class="text-xs text-slate-600">${key.replace(/_/g,' ')}</span>
        <span class="text-xs font-bold text-slate-700">${pct}%</span>
      </div>
      <div class="w-full bg-slate-100 rounded-full h-1.5">
        <div class="${barColor} h-1.5 rounded-full mastery-bar" style="width:${pct}%"></div>
      </div>`;
    panel.appendChild(div);
  });
}

function showAdaptationBanner(msg) {
  const banner = document.getElementById('adaptation-banner');
  document.getElementById('adaptation-text').textContent = msg;
  banner.classList.remove('hidden');
  setTimeout(() => banner.classList.add('hidden'), 6000);
}

function showSpeakingIndicator(show, customStatus) {
  const indicator = document.getElementById('speaking-indicator');
  const soundWaves = document.getElementById('sound-waves');
  const modeBadge = document.getElementById('avatar-mode-badge');
  const statusEl = document.getElementById('avatar-status');
  const avatarGlow = document.getElementById('avatar-glow');

  if (show) {
    if (indicator) indicator.classList.remove('hidden');
    if (soundWaves) soundWaves.classList.remove('hidden');
    if (avatarGlow) avatarGlow.classList.remove('hidden');
    if (statusEl) statusEl.textContent = customStatus || 'Explaining concept...';
    if (modeBadge) {
      modeBadge.textContent = 'Speaking';
      modeBadge.className = 'px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950/80 backdrop-blur-sm text-emerald-300 border border-emerald-500/40';
    }
  } else {
    if (indicator) indicator.classList.add('hidden');
    if (soundWaves) soundWaves.classList.add('hidden');
    if (avatarGlow) avatarGlow.classList.add('hidden');
    if (statusEl) statusEl.textContent = 'Ready to teach';
    if (modeBadge) {
      modeBadge.textContent = 'Simli AI Teacher';
      modeBadge.className = 'px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-900/80 backdrop-blur-sm text-indigo-200 border border-indigo-500/30';
    }
  }
}

function highlightLanguageBtn(lang) {
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('border-indigo-400', btn.dataset.lang === lang);
    btn.classList.toggle('text-indigo-600', btn.dataset.lang === lang);
  });
}

function showError(msg) {
  // Show error in next-hint
  const hint = document.getElementById('next-hint');
  if (hint) { hint.textContent = '⚠ ' + msg; hint.classList.add('text-red-500'); }
}

function setNextLoading(loading) {
  const btn = document.getElementById('next-btn');
  const spinner = document.getElementById('next-spinner');
  if (btn) btn.disabled = loading;
  if (spinner) spinner.classList.toggle('hidden', !loading);
}

function setAnswerLoading(loading) {
  const btn = document.getElementById('submit-answer-btn');
  const spinner = document.getElementById('answer-spinner');
  if (btn) btn.disabled = loading;
  if (spinner) spinner.classList.toggle('hidden', !loading);
}

// ── Controls ──────────────────────────────────────────────────────────────

function togglePause() {
  isPaused = !isPaused;
  if (isPaused) {
    stopCurrentSpeechAndVideo();
  }
  document.getElementById('btn-pause').textContent = isPaused ? '▶ Resume' : '⏸ Pause';
}

async function repeatSegment() {
  stopCurrentSpeechAndVideo();
  currentSpokenText = '';
  const spokenEl = document.getElementById('spoken-text');
  if (spokenEl) {
    spokenEl.innerHTML = '<span class="text-indigo-600 font-medium animate-pulse">⏳ Repeating explanation...</span>';
  }
  setNextLoading(true);
  try {
    const resp = await fetch(`/api/sessions/${sessionId}/repeat`, { method: 'POST' });
    if (!resp.ok) return;
    const state = await resp.json();
    applyState(state);
  } finally {
    setNextLoading(false);
  }
}

async function simplifyExplanation() {
  stopCurrentSpeechAndVideo();
  currentSpokenText = '';
  const spokenEl = document.getElementById('spoken-text');
  if (spokenEl) {
    spokenEl.innerHTML = '<span class="text-indigo-600 font-medium animate-pulse">⏳ Preparing simpler explanation...</span>';
  }
  try {
    const resp = await fetch(`/api/sessions/${sessionId}/simplify`, { method: 'POST' });
    if (!resp.ok) return;
    const output = await resp.json();
    applyTeacherOutput(output);
  } catch (e) {
    console.error('Simplify error:', e);
  }
}

async function switchLanguage(lang) {
  currentLanguage = lang;
  highlightLanguageBtn(lang);
  try {
    await fetch(`/api/sessions/${sessionId}/switch-language`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: lang })
    });
  } catch (e) {
    console.error('Language switch error:', e);
  }
}

// ── Ask Teacher modal ─────────────────────────────────────────────────────

function openAskModal() {
  document.getElementById('ask-modal').classList.remove('hidden');
  document.getElementById('ask-answer').classList.add('hidden');
  document.getElementById('ask-input').focus();
}

function closeAskModal() {
  document.getElementById('ask-modal').classList.add('hidden');
}

async function submitAsk() {
  const question = document.getElementById('ask-input').value.trim();
  if (!question) return;

  const spinner = document.getElementById('ask-spinner');
  const answerEl = document.getElementById('ask-answer');
  spinner.classList.remove('hidden');
  answerEl.classList.add('hidden');

  try {
    const resp = await fetch(`/api/sessions/${sessionId}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question })
    });
    if (!resp.ok) throw new Error('Ask failed');
    const output = await resp.json();

    // Push the real answer onto the avatar (speaking) + Smart Board (worked
    // steps/formula), exactly like a normal teaching segment — this is what
    // actually answers "solve these equations" instead of reading text aloud
    // from a popup.
    applyTeacherOutput(output);

    // Leave a short confirmation in the modal, then get out of the way so
    // the student can see the board and watch the avatar answer.
    answerEl.textContent = '✅ Answered on the Smart Board — watch the teacher explain it.';
    answerEl.classList.remove('hidden');
    setTimeout(() => {
      closeAskModal();
      document.getElementById('ask-input').value = '';
      answerEl.classList.add('hidden');
    }, 1400);
  } catch (e) {
    answerEl.textContent = 'Error: ' + e.message;
    answerEl.classList.remove('hidden');
  } finally {
    spinner.classList.add('hidden');
  }
}

// ── Assessment trigger ──────────────────────────────────────────────────────

async function startAssessment() {
  window.location.href = '/assessment';
}

// ── Utility ───────────────────────────────────────────────────────────────

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
