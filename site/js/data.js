/*
 * data.js
 * site/data/ 配下のJSON（export_db_to_json.py の生成物）を取得するための
 * 共通ヘルパー。ページ間でのキャッシュも兼ねる。
 */

const DrugData = (() => {
  const DATA_ROOT = "/data";
  let indexPromise = null;
  const detailCache = new Map();
  const interactionCache = new Map();

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

  /**
   * 指定した薬品idが関わる相互作用ペアだけを取得する。
   * 全薬剤分の相互作用をまとめた1ファイルは45万件規模になりGitHubの
   * ファイルサイズ上限を超えるため、薬品ごとに分割している
   * （interactions/{id}.json、無ければ相互作用の記載なし＝空配列）。
   */
  function loadDrugInteractions(id) {
    if (!interactionCache.has(id)) {
      const promise = fetch(`${DATA_ROOT}/interactions/${id}.json`).then((res) => {
        if (res.status === 404) return [];
        if (!res.ok) throw new Error(`相互作用データの取得に失敗しました: id=${id}`);
        return res.json();
      });
      interactionCache.set(id, promise);
    }
    return interactionCache.get(id);
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

  return { loadIndex, loadDrugInteractions, loadDrug, search };
})();
