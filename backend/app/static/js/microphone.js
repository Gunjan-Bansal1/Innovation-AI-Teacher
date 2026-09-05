/**
 * microphone.js — Web Speech API wrapper for voice input
 *
 * Features:
 * - Graceful degradation if permission denied
 * - Never mandatory — text input always available
 * - Handles browser compatibility (Chrome/Edge)
 */

let recognition = null;
let isListening = false;

function initMicrophone() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.info('Web Speech API not supported in this browser. Text input available.');
    const micBtn = document.getElementById('mic-btn');
    if (micBtn) {
      micBtn.title = 'Voice input not supported in this browser';
      micBtn.style.opacity = '0.4';
      micBtn.disabled = true;
    }
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = getRecognitionLanguage();

  recognition.onstart = () => {
    isListening = true;
    updateMicButton(true);
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    const answerInput = document.getElementById('answer-input');
    if (answerInput) {
      answerInput.value = transcript;
      answerInput.dispatchEvent(new Event('input'));
    }
  };

  recognition.onerror = (event) => {
    isListening = false;
    updateMicButton(false);
    if (event.error === 'not-allowed') {
      showToast('Microphone access denied. Please use text input.', 'warning');
    } else if (event.error === 'no-speech') {
      showToast('No speech detected. Try again.', 'info');
    }
  };

  recognition.onend = () => {
    isListening = false;
    updateMicButton(false);
  };
}

function toggleMic() {
  if (!recognition) {
    showToast('Voice input not available. Please type your answer.', 'info');
    return;
  }

  if (isListening) {
    recognition.stop();
  } else {
    // Update language based on current session
    recognition.lang = getRecognitionLanguage();
    try {
      recognition.start();
    } catch (e) {
      showToast('Could not start microphone. Please type your answer.', 'warning');
    }
  }
}

function updateMicButton(active) {
  const btn = document.getElementById('mic-btn');
  if (!btn) return;
  btn.textContent = active ? '⏹' : '🎤';
  btn.title = active ? 'Stop recording' : 'Voice input';
  btn.classList.toggle('border-red-400', active);
  btn.classList.toggle('text-red-500', active);
}

function getRecognitionLanguage() {
  // Map app language to BCP-47 code
  const lang = localStorage.getItem('learner_prefs')
    ? JSON.parse(localStorage.getItem('learner_prefs')).language
    : 'english';

  const langMap = {
    english: 'en-IN',
    hindi: 'hi-IN',
    hinglish: 'hi-IN',  // Hinglish uses Hindi recognition
  };
  return langMap[lang] || 'en-IN';
}

// Initialize on load
document.addEventListener('DOMContentLoaded', initMicrophone);
