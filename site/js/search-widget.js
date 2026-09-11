/*
 * search-widget.js
 * 検索窓＋候補リストの共通コンポーネント。
 * onSelect の実装をページごとに変えることで、
 * 「クリックで薬品ページへ遷移」（トップページ）と
 * 「クリックで服用中リストに追加」（複数薬チェックページ）の両方に使う。
 */

function createSearchWidget({ inputEl, resultsEl, onSelect, placeholder }) {
  let allDrugs = [];
  let activeIndex = -1;

  if (placeholder) inputEl.placeholder = placeholder;

  DrugData.loadIndex()
    .then((list) => {
      allDrugs = list;
      inputEl.disabled = false;
    })
    .catch(() => {
      inputEl.placeholder = "データの読み込みに失敗しました";
    });

  function render(matches, query) {
    resultsEl.innerHTML = "";
    activeIndex = -1;

    if (matches.length === 0) {
      if (query) {
        const empty = document.createElement("div");
        empty.className = "search-no-results";
        empty.textContent = `「${query}」に一致する薬品は見つかりませんでした。別の表記（一般名・商品名）もお試しください。`;
        resultsEl.appendChild(empty);
      }
      positionResults();
      return;
    }

    matches.forEach((drug) => {
      const a = document.createElement(onSelect ? "button" : "a");
      if (onSelect) a.type = "button";
      a.className = "search-result";
      if (!onSelect) a.href = `/drug.html?id=${drug.id}`;
      a.innerHTML = `<span class="name">${escapeHTML(drug.brand_name || drug.generic_name)}</span>
        <span class="meta">${escapeHTML(drug.generic_name || "")}${
        drug.therapeutic_classification ? " ・ " + escapeHTML(drug.therapeutic_classification) : ""
      }</span>`;
      a.addEventListener("click", (e) => {
        if (onSelect) {
          e.preventDefault();
          onSelect(drug);
          inputEl.value = "";
          resultsEl.innerHTML = "";
        }
      });
      resultsEl.appendChild(a);
    });
    positionResults();
  }

  function escapeHTML(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  /**
   * 画面下端に近く候補一覧を下に開くスペースが無い場合、
   * 検索欄の上に開く（UI/UX標準機能チェックリスト 9章「画面端での見切れ回避」対応）。
   */
  function positionResults() {
    if (!resultsEl.children.length) return;
    resultsEl.classList.remove("search-results--up");
    const inputRect = inputEl.getBoundingClientRect();
    const estimatedHeight = Math.min(resultsEl.scrollHeight || 200, 340);
    const spaceBelow = window.innerHeight - inputRect.bottom;
    if (spaceBelow < estimatedHeight + 16 && inputRect.top > estimatedHeight) {
      resultsEl.classList.add("search-results--up");
    }
  }

  inputEl.addEventListener("input", () => {
    const query = inputEl.value.trim();
    const matches = DrugData.search(allDrugs, query);
    render(matches, query);
  });

  /**
   * ArrowDownで最初の候補にフォーカスを移すと、以降のキー入力は
   * フォーカス中の候補（<a>/<button>）で発生する。inputEl側にだけ
   * keydownを登録すると、1件目にフォーカスが移った時点でそれ以降の
   * ArrowDown/ArrowUpが効かなくなる不具合があったため、resultsEl側にも
   * 同じハンドラをイベント委譲で登録し、候補にフォーカスがある状態でも
   * 矢印キー操作を継続できるようにする。
   */
  function handleListKeydown(e) {
    const items = Array.from(resultsEl.children).filter((el) => el.classList.contains("search-result"));
    if (!items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = Math.min(activeIndex + 1, items.length - 1);
      items[activeIndex].focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex -= 1;
      if (activeIndex < 0) {
        activeIndex = -1;
        inputEl.focus();
      } else {
        items[activeIndex].focus();
      }
    } else if (e.key === "Escape") {
      resultsEl.innerHTML = "";
      inputEl.focus();
    }
  }

  inputEl.addEventListener("keydown", handleListKeydown);
  resultsEl.addEventListener("keydown", handleListKeydown);

  document.addEventListener("click", (e) => {
    if (!resultsEl.contains(e.target) && e.target !== inputEl) {
      resultsEl.innerHTML = "";
    }
  });
}
