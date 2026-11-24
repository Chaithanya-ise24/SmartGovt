function speak(text, lang) {
  if (!('speechSynthesis' in window)) { alert('Voice is not supported in this browser.'); return; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang || 'en-IN';
  u.rate = 0.9;
  const voices = window.speechSynthesis.getVoices();
  const v = voices.find(x => x.lang === u.lang) || voices.find(x => x.lang.startsWith(u.lang.slice(0, 2)));
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
}

function listen(onResult, lang) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { alert('Voice typing works in Chrome or Edge.'); return; }
  const r = new SR();
  r.lang = lang || 'en-IN';
  r.interimResults = false;
  r.onresult = e => onResult(e.results[0][0].transcript);
  r.onerror = () => alert('Could not hear you. Please try again.');
  r.start();
}