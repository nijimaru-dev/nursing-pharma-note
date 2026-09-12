/*
 * settings.js
 * ヘッダーの「表示設定」パネル（テーマ・文字サイズ）の開閉とボタン操作を扱う。
 *
 * ちらつき防止のため、実際の適用（html[data-theme]/html[data-fontsize]の付与）は
 * 各ページ<head>のインラインスクリプト（apply-settings、CSS読み込み前に実行）で
 * 先に行っている。ここではパネルの開閉と、ボタン操作時の再適用・保存のみを担当する。
 */
(function () {
  var THEME_KEY = "npn-theme";
  var FONTSIZE_KEY = "npn-fontsize";

  var toggle = document.getElementById("settings-toggle");
  var panel = document.getElementById("settings-panel");
  if (!toggle || !panel) return;

  function currentTheme() {
    try { return localStorage.getItem(THEME_KEY) || "system"; } catch (e) { return "system"; }
  }
  function currentFontSize() {
    try { return localStorage.getItem(FONTSIZE_KEY) || "medium"; } catch (e) { return "medium"; }
  }

  function applyTheme(choice) {
    if (choice === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = choice;
    try { localStorage.setItem(THEME_KEY, choice); } catch (e) {}
  }
  function applyFontSize(choice) {
    if (choice === "medium") delete document.documentElement.dataset.fontsize;
    else document.documentElement.dataset.fontsize = choice;
    try { localStorage.setItem(FONTSIZE_KEY, choice); } catch (e) {}
  }

  function syncButtons() {
    var theme = currentTheme();
    var fontsize = currentFontSize();
    panel.querySelectorAll("[data-theme-choice]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", String(btn.dataset.themeChoice === theme));
    });
    panel.querySelectorAll("[data-fontsize-choice]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", String(btn.dataset.fontsizeChoice === fontsize));
    });
  }

  panel.querySelectorAll("[data-theme-choice]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      applyTheme(btn.dataset.themeChoice);
      syncButtons();
    });
  });
  panel.querySelectorAll("[data-fontsize-choice]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      applyFontSize(btn.dataset.fontsizeChoice);
      syncButtons();
    });
  });

  toggle.addEventListener("click", function () {
    var willOpen = panel.hidden;
    panel.hidden = !willOpen;
    toggle.setAttribute("aria-expanded", String(willOpen));
  });

  document.addEventListener("click", function (e) {
    // トグルボタンの中のsvgアイコンをタップした場合、e.targetはbutton自体ではなく
    // svg（またはその子のpath/circle）になる。e.target !== toggleの比較だけでは
    // これを「ボタンの外側」と誤判定し、開いた直後の同じクリックでこのハンドラが
    // 即座にパネルを閉じてしまい、1回目のタップでパネルが開かないように見える
    // 不具合があった。toggle.contains(e.target)で子要素へのクリックも
    // 「トグルボタン自身への操作」として扱う。
    if (!panel.hidden && !panel.contains(e.target) && !toggle.contains(e.target)) {
      panel.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !panel.hidden) {
      panel.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    }
  });

  syncButtons();
})();
