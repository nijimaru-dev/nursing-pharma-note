/*
 * data.js
 * site/data/ 配下のJSON（export_db_to_json.py の生成物）を取得するための
 * 共通ヘルパー。ページ間でのキャッシュも兼ねる。
 */

const DrugData = (() => {
  const DATA_ROOT = "/data";
  let indexPromise = null;
  const detailCache = new Map();
  const interactionIndexCache = new Map();
  const pairInteractionCache = new Map();

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
   * 指定した薬品idが関わる相互作用ペアの「索引」だけを取得する
   * （相手薬のid・注意種別のみ。本文（source_text）は含まない）。
   * 本文はペアごとに1ファイル（pairs/{min}_{max}.json）へ分離してあるため、
   * 実際に表示する必要があるペアが決まってから loadPairInteraction で
   * 別途取得する（2026-09-12：本文の二重持ちをやめるための分離）。
   * interactions/{id}.json が無い薬品は相互作用の記載なし＝空配列。
   */
  function loadDrugInteractionIndex(id) {
    if (!interactionIndexCache.has(id)) {
      const promise = fetch(`${DATA_ROOT}/interactions/${id}.json`).then((res) => {
        if (res.status === 404) return [];
        if (!res.ok) throw new Error(`相互作用索引の取得に失敗しました: id=${id}`);
        return res.json();
      });
      interactionIndexCache.set(id, promise);
    }
    return interactionIndexCache.get(id);
  }

  /**
   * 薬品ペア（idA, idB。順不同でよい）の相互作用本文を取得する。
   * ファイル名は薬品idを小さい順に並べた min_max.json（pairs/{min}_{max}.json）。
   * 同じペアにcontraindicated/cautionが両方記載されていることがあるため配列で返す。
   */
  function loadPairInteraction(idA, idB) {
    const minId = Math.min(idA, idB);
    const maxId = Math.max(idA, idB);
    const key = `${minId}_${maxId}`;
    if (!pairInteractionCache.has(key)) {
      const promise = fetch(`${DATA_ROOT}/interactions/pairs/${key}.json`).then((res) => {
        if (res.status === 404) return [];
        if (!res.ok) throw new Error(`相互作用本文の取得に失敗しました: pair=${key}`);
        return res.json();
      });
      pairInteractionCache.set(key, promise);
    }
    return pairInteractionCache.get(key);
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

  return { loadIndex, loadDrugInteractionIndex, loadPairInteraction, loadDrug, search };
})();
