/*
 * mydrugs.js
 * 「マイ薬箱」（お気に入り）と「最近見た薬」（閲覧履歴）を扱う共通モジュール。
 * ログイン機能が無いため、どちらもlocalStorageのみに保存する
 * （ブラウザ・端末をまたいでは共有されない）。
 */

const MyDrugs = (() => {
  const FAV_KEY = "npn-favorites";
  const HISTORY_KEY = "npn-history";
  const HISTORY_LIMIT = 20;

  function readList(key) {
    try {
      const raw = localStorage.getItem(key);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function writeList(key, list) {
    try {
      localStorage.setItem(key, JSON.stringify(list));
    } catch (e) {
      // localStorageが使えない環境（プライベートモード等）では保存をあきらめる
    }
  }

  function snapshot(drug) {
    return {
      id: drug.id,
      brand_name: drug.brand_name || "",
      generic_name: drug.generic_name || "",
    };
  }

  function getFavorites() {
    return readList(FAV_KEY);
  }

  function isFavorite(id) {
    return getFavorites().some((d) => d.id === id);
  }

  /** お気に入り登録状態を反転する。戻り値は反転後の状態（true=登録済み）。 */
  function toggleFavorite(drug) {
    const list = getFavorites();
    const idx = list.findIndex((d) => d.id === drug.id);
    if (idx >= 0) {
      list.splice(idx, 1);
      writeList(FAV_KEY, list);
      return false;
    }
    list.unshift({ ...snapshot(drug), added_at: Date.now() });
    writeList(FAV_KEY, list);
    return true;
  }

  function removeFavorite(id) {
    writeList(FAV_KEY, getFavorites().filter((d) => d.id !== id));
  }

  function getHistory() {
    return readList(HISTORY_KEY);
  }

  /** 薬品詳細ページの閲覧を履歴に記録する（同じ薬は先頭へ移動、上限件数を超えたら古いものから削除）。 */
  function recordView(drug) {
    const list = getHistory().filter((d) => d.id !== drug.id);
    list.unshift({ ...snapshot(drug), viewed_at: Date.now() });
    writeList(HISTORY_KEY, list.slice(0, HISTORY_LIMIT));
  }

  function clearHistory() {
    writeList(HISTORY_KEY, []);
  }

  function setHistory(list) {
    writeList(HISTORY_KEY, list);
  }

  return { getFavorites, isFavorite, toggleFavorite, removeFavorite, getHistory, recordView, clearHistory, setHistory };
})();
