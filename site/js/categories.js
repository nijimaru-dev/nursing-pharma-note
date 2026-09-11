/*
 * categories.js
 * 薬効分類（therapeutic_classification、PMDA添付文書の原文ママ・2,143種類）を、
 * 現場で使いやすい「大分類」約17種類にまとめるための、キーワードベースの分類ルール。
 *
 * PMDAデータには公式の大分類コードが薬品ごとに整理された形では入っていないため
 * （日本標準商品分類番号はSccj要素にあるが本パーサーでは未取得）、
 * v1は薬効分類の文字列にキーワードが含まれるかで判定する「育てる辞書」方式とする
 * （drug_alias.pyのALIAS_MAPと同じ考え方）。上から順に判定し、最初に一致した
 * カテゴリを採用する。どれにも一致しない場合は「その他」に入る。
 *
 * 添付文書のH2・AT1のような下付き文字はXMLパース時に別テキストノードとして
 * 分割されており（例："H\n2\n受容体拮抗剤"）、そのままだとキーワードが一致しない。
 * そのため判定前に空白・改行を除去してから比較する。
 */

const DRUG_CATEGORIES = [
  { id: "circulatory", label: "循環器・血液", icon: "❤️",
    keywords: ["強心", "血圧", "降圧", "狭心", "不整脈", "利尿", "Ca拮抗", "カルシウム拮抗",
      "アンジオテンシン", "AT1", "ACE阻害", "ARB", "血液凝固", "抗血小板", "抗凝固", "血栓", "血漿",
      "血液成分", "昇圧", "高脂血症", "脂質異常", "HMG-CoA", "動脈硬化", "エンドセリン",
      "トロンボキサン", "急性循環不全"] },
  { id: "digestive", label: "消化器", icon: "🍽️",
    keywords: ["胃", "腸", "消化", "潰瘍", "プロトンポンプ", "H2受容体拮抗", "制酸", "制吐", "緩下",
      "下剤", "便秘", "下痢", "肝", "胆", "膵", "痔"] },
  { id: "respiratory", label: "呼吸器", icon: "🌬️",
    keywords: ["気管支", "去痰", "鎮咳", "喘息", "呼吸", "気道", "吸入ガス"] },
  { id: "infection", label: "感染症・抗菌薬", icon: "🦠",
    keywords: ["抗生物質", "抗菌", "セフェム", "ペニシリン", "マクロライド", "キノロン", "アミノグリコシド",
      "抗真菌", "抗ウイルス", "ワクチン", "抗結核", "サルファ", "グリコペプチド", "カルバペネム",
      "殺菌消毒", "深在性真菌症"] },
  { id: "psych-neuro", label: "精神・神経", icon: "🧠",
    keywords: ["抗精神病", "抗うつ", "睡眠", "入眠", "不眠症", "抗不安", "てんかん", "パーキンソン",
      "認知症", "トランキライザー", "セロトニン", "抗めまい", "抗片頭痛", "片頭痛", "鎮静",
      "精神安定剤", "精神神経"] },
  { id: "pain", label: "鎮痛・解熱・麻酔", icon: "💊",
    keywords: ["鎮痛", "解熱", "消炎", "麻酔", "麻薬性", "疼痛", "線維筋痛症"] },
  { id: "endocrine", label: "内分泌・代謝", icon: "⚗️",
    keywords: ["血糖降下", "糖尿病", "インスリン", "食後過血糖", "甲状腺", "副腎皮質ホルモン", "ホルモン",
      "高尿酸血症", "痛風", "代謝", "アルドース還元酵素"] },
  { id: "allergy-immune", label: "アレルギー・免疫", icon: "🤧",
    keywords: ["アレルギー", "抗ヒスタミン", "免疫抑制", "ステロイド", "抗リウマチ"] },
  { id: "urology", label: "泌尿器・腎臓", icon: "💧",
    keywords: ["前立腺", "排尿", "過活動膀胱", "透析", "腎", "勃起", "高リン血症"] },
  { id: "bone-joint", label: "骨・関節", icon: "🦴",
    keywords: ["骨粗鬆症", "骨代謝", "ビスホスホン"] },
  { id: "oncology", label: "抗悪性腫瘍（がん）", icon: "🎗️",
    keywords: ["抗悪性腫瘍", "抗がん", "抗癌"] },
  { id: "dermatology", label: "皮膚・外用", icon: "🩹",
    keywords: ["外用", "外皮用", "軟膏", "皮膚", "褥瘡", "ざ瘡"] },
  { id: "ophthalmology-ent", label: "眼科・耳鼻科", icon: "👁️",
    keywords: ["点眼", "緑内障", "眼科", "眼用", "耳鼻", "点鼻"] },
  { id: "kampo", label: "漢方・生薬", icon: "🌿",
    keywords: ["漢方", "生薬"] },
  { id: "obgyn", label: "産婦人科", icon: "🤰",
    keywords: ["子宮", "卵胞", "黄体", "分娩", "避妊", "月経"] },
  { id: "vaccine-diagnostic", label: "ワクチン・検査薬", icon: "💉",
    keywords: ["検査薬", "造影剤", "診断"] },
];

const OTHER_CATEGORY = { id: "other", label: "その他", icon: "📦" };

/** 薬効分類の文字列から、該当する大分類idを1つ返す（最初に一致したもの）。 */
function categorize(therapeuticClassification) {
  const text = (therapeuticClassification || "").replace(/\s+/g, "");
  for (const cat of DRUG_CATEGORIES) {
    if (cat.keywords.some((kw) => text.includes(kw))) {
      return cat.id;
    }
  }
  return OTHER_CATEGORY.id;
}

function getCategoryById(id) {
  return DRUG_CATEGORIES.find((c) => c.id === id) || OTHER_CATEGORY;
}
