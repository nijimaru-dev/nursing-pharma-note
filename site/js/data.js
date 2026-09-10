/*
 * data.js
 * site/data/ 配下のJSON（export_db_to_json.py の生成物）を取得するための
 * 共通ヘルパー。ページ間でのキャッシュも兼ねる。
 */

const DrugData = (() => {
  const DATA_ROOT = "/data";
  let indexPromise = null;
  let interactionsPromise = null;
  const detailCache = new Map();

  function fetchJSON(path) {
    return fetch(path).then((res) => {
      if (!res.ok) throw new Error(`データの取得に失敗しました: ${path}`);
      return res.json();
    });
  }

  function loadIndex() {
    if (!indexPromise) indexPromise = fetchJSON(`${DATA_ROOT}/index.json`);
    return indexPromise;
  }

  function loadInteractions() {
    if (!interactionsPromise) interactionsPromise = fetchJSON(`${DATA_ROOT}/interactions.json`);
    return interactionsPromise;
  }

  function loadDrug(id) {
    if (!detailCache.has(id)) {
      detailCache.set(id, fetchJSON(`${DATA_ROOT}/drugs/${id}.json`));
    }
    return detailCache.get(id);
  }

  /** 商品名・一般名の部分一致検索（先頭一致を優先して並べる） */
  function search(list, query) {
    const q = query.trim();
    if (!q) return [];
    const lower = q.toLowerCase();
    return list
      .filter(
        (d) =>
          (d.brand_name && d.brand_name.includes(q)) ||
          (d.generic_name && d.generic_name.includes(q)) ||
          (d.therapeutic_classification && d.therapeutic_classification.includes(q))
      )
      .sort((a, b) => {
        const aStarts = (a.brand_name || "").startsWith(q) || (a.generic_name || "").startsWith(q);
        const bStarts = (b.brand_name || "").startsWith(q) || (b.generic_name || "").startsWith(q);
        if (aStarts !== bStarts) return aStarts ? -1 : 1;
        return (a.brand_name || "").localeCompare(b.brand_name || "", "ja");
      })
      .slice(0, 20);
  }

  return { loadIndex, loadInteractions, loadDrug, search };
})();
