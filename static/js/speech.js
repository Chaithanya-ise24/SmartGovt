function _isKannada(text) {
  return /[\u0C80-\u0CFF]/.test(text);
}

let _audio = null;

function stopSpeaking() {
  if (_audio) { _audio.pause(); _audio = null; }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

function speak(text, lang) {
  if (!text) return;
  stopSpeaking();

  if (_isKannada(text) || (lang && lang.toLowerCase().startsWith('kn'))) {
    // Kannada: audio is made by the server
    _audio = new Audio('/student/tts?text=' + encodeURIComponent(text.slice(0, 400)));
    _audio.play().catch(function () {
      alert('Kannada voice needs an internet connection. Please check and try again.');
    });
    return;
  }

  if (!window.speechSynthesis) { alert('Voice is not supported in this browser.'); return; }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang || 'en-IN';
  u.rate = 0.9;
  window.speechSynthesis.speak(u);
}

function listen(onResult, lang) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { alert('Voice typing works in Chrome or Edge.'); return; }
  const r = new SR();
  r.lang = lang || 'en-IN';
  r.interimResults = false;
  r.onresult = function (e) { onResult(e.results[0][0].transcript); };
  r.onerror = function () { alert('Could not hear you. Please try again.'); };
  r.start();
}