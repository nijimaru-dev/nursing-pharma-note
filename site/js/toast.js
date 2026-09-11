/*
 * toast.js
 * 「コピーしました」等の操作結果を知らせる、画面下部の一時的な通知。
 * UI/UX標準機能チェックリスト 4章「成功トーストと結果の持続的表示」に対応。
 */

function showToast(message) {
  let region = document.getElementById("toast-region");
  if (!region) {
    region = document.createElement("div");
    region.id = "toast-region";
    region.setAttribute("aria-live", "polite");
    region.setAttribute("role", "status");
    document.body.appendChild(region);
  }

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  region.appendChild(toast);

  requestAnimationFrame(() => toast.classList.add("toast--visible"));

  setTimeout(() => {
    toast.classList.remove("toast--visible");
    setTimeout(() => toast.remove(), 250);
  }, 2400);
}

/**
 * 確認ダイアログ（confirm()）の代わりに使う、「取り消し」操作つきのトースト。
 * 呼び出し側は破壊的な操作（一括リセット等）を即座に実行してよい。
 * 表示中に「取り消し」が押されたらonUndoを呼ぶ。押されないまま消えたら
 * onUndoは呼ばれず、操作はそのまま確定する。
 */
function showUndoToast(message, onUndo) {
  let region = document.getElementById("toast-region");
  if (!region) {
    region = document.createElement("div");
    region.id = "toast-region";
    region.setAttribute("aria-live", "polite");
    region.setAttribute("role", "status");
    document.body.appendChild(region);
  }

  const toast = document.createElement("div");
  toast.className = "toast";

  const label = document.createElement("span");
  label.textContent = message;
  toast.appendChild(label);

  const undoBtn = document.createElement("button");
  undoBtn.type = "button";
  undoBtn.className = "toast__undo";
  undoBtn.textContent = "取り消す";
  toast.appendChild(undoBtn);

  region.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("toast--visible"));

  let done = false;
  const dismiss = () => {
    if (done) return;
    done = true;
    toast.classList.remove("toast--visible");
    setTimeout(() => toast.remove(), 250);
  };

  const timer = setTimeout(dismiss, 5000);

  undoBtn.addEventListener("click", () => {
    if (done) return;
    clearTimeout(timer);
    dismiss();
    onUndo();
  });
}

function copyTextToClipboard(text, successMessage) {
  const done = () => showToast(successMessage || "コピーしました");
  const fail = () => showToast("コピーできませんでした");

  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done, fail);
    return;
  }

  // フォールバック（古い環境・非HTTPS環境用）
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    document.execCommand("copy");
    done();
  } catch (e) {
    fail();
  }
  textarea.remove();
}
