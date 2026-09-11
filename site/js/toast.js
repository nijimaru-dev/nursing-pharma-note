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
