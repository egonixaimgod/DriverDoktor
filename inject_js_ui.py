import io
with open('ui.html', 'r', encoding='utf-8') as f:
    text = f.read()

js_addon = """
/* ========== ULTIMATE LOGGING BRIDGE ========== */
const originalLog = console.log;
const originalWarn = console.warn;
const originalError = console.error;

console.log = function() {
  const args = Array.from(arguments);
  if (window.pywebview && window.pywebview.api) {
      try { window.pywebview.api.js_log('INFO', args.join(' ')); } catch(e) {}
  }
  originalLog.apply(console, arguments);
};

console.warn = function() {
  const args = Array.from(arguments);
  if (window.pywebview && window.pywebview.api) {
      try { window.pywebview.api.js_log('WARN', args.join(' ')); } catch(e) {}
  }
  originalWarn.apply(console, arguments);
};

console.error = function() {
  const args = Array.from(arguments);
  if (window.pywebview && window.pywebview.api) {
      try { window.pywebview.api.js_log('ERROR', args.join(' ')); } catch(e) {}
  }
  originalError.apply(console, arguments);
};

window.onerror = function(message, source, lineno, colno, error) {
  const info = `${message} @ ${source}:${lineno}:${colno}`;
  if (window.pywebview && window.pywebview.api) {
      try { window.pywebview.api.js_log('ERROR', 'Uncaught JS Hiba: ' + info); } catch(e) {}
  }
  return false;
};

window.addEventListener('unhandledrejection', function(event) {
  if (window.pywebview && window.pywebview.api) {
      try { window.pywebview.api.js_log('ERROR', 'Unhandled Promise Rejection JS oldalon: ' + event.reason); } catch(e) {}
  }
});

function api() { return window.pywebview ? window.pywebview.api : null; }"""

text = text.replace("function api() { return window.pywebview ? window.pywebview.api : null; }", js_addon)

with open('ui.html', 'w', encoding='utf-8') as f:
    f.write(text)
