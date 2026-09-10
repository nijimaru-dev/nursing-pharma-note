# -*- coding: utf-8 -*-
"""
pmda_tenpu_parser.py
PMDA「医療用医薬品 添付文書等情報検索」からダウンロードした
新記載要領（XML形式）の添付文書ファイル群を読み込み、
KarteNo用にクレンジングしてSQLiteへ格納するスクリプト。

前提：
- 入力はPMDAサイトから個別にダウンロードしたXMLファイル群（1薬剤=1ファイルが基本、
  ただし1ファイルに複数の販売名・YJコードが含まれる場合がある）
- タグ名は製薬協「医療用医薬品添付文書情報の電子ファイル作成の手引き－XML形式－」
  （2019年5月 暫定版第1版）4.3項目名一覧に基づく（本スクリプト作成時点で確認済み）
- ネットワークダウンロード自体はこのスクリプトでは行わない
  （PMDAサイトから手動または別途スクリプトで取得したXMLを input-dir に置く前提）

使い方：
    python pmda_tenpu_parser.py --input-dir ./tenpu_xml --db ./karteno_drugs.db
    python pmda_tenpu_parser.py --input-dir ./tenpu_xml --db ./karteno_drugs.db --formulary formulary.txt

formulary.txt を渡すと、院内処方リストに載っている薬剤名（一般名 or 販売名、1行1件）
に一致するものだけ is_in_formulary=1 でマークする（未提供時は全件0のまま取り込む）。
写真から起こした院内処方リストが用意でき次第、テキスト化してこのファイルとして渡してください。
"""

import argparse
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from drug_alias import interaction_text_mentions


# ---------------------------------------------------------------------------
# XMLタグ定義（PMDA/製薬協 手引き 4.3 項目名一覧に基づく確認済みタグ）
# ---------------------------------------------------------------------------
TAG = {
    "root": "PackIns",
    "approval_etc": "ApprovalEtc",
    "brand_name": "ApprovalBrandName",
    "yj_code": "YJCode",
    "generic_name": "GenericName",
    "therapeutic_classification": "TherapeuticClassification",
    "sccj": "Sccj",
    "indications": "IndicationsOrEfficacy",
    "dose_admin": "InfoDoseAdmin",
    "contraindications": "ContraIndications",
    "interactions": "Interactions",
    "contra_combi": "ContraIndicatedCombinations",
    "contra_combi_item": "ContraIndication",
    "caution_combi": "PrecautionsForCombinations",
    "caution_combi_item": "PrecautionsForCombi",
    "adverse_events": "AdverseEvents",
    "serious_adverse": "SeriousAdverseEvents",
    "application_precautions": "PrecautionsForApplication",
    "use_in_specific_pop": "UseInSpecificPopulations",
}


def _text_all(elem):
    """要素配下の全テキストを連結して1つの文字列にする（フリーテキスト項目用）。"""
    if elem is None:
        return ""
    parts = [t.strip() for t in elem.itertext() if t and t.strip()]
    return "\n".join(parts)


def _find_all(root, tagname):
    return root.iter(tagname)


def parse_interaction_table(table_elem):
    """
    10.1併用禁忌 / 10.2併用注意 のテーブル1件分（ContraIndication / PrecautionsForCombi）
    から 薬剤名等・臨床症状措置方法・機序危険因子 を抜き出す。
    XMLスキーマ上、列名タグが明示されていないケースがあるため、
    子要素の並び順（薬剤名等→臨床症状・措置方法→機序・危険因子）をフォールバックに使う。
    """
    drug_name, clinical, mechanism = "", "", ""
    children = list(table_elem)
    texts = [_text_all(c) for c in children]
    # 手引きの表定義通り3列想定。列数がずれるファイルもあるため安全に取得する。
    if len(texts) >= 1:
        drug_name = texts[0]
    if len(texts) >= 2:
        clinical = texts[1]
    if len(texts) >= 3:
        mechanism = texts[2]
    return {
        "drug_name_or_class": drug_name,
        "clinical_symptom_action": clinical,
        "mechanism_risk_factor": mechanism,
    }


def parse_tenpu_file(filepath: Path):
    """
    1つの添付文書XMLファイルをパースし、
    (販売名・YJコード単位の基本情報リスト, 共通の相互作用/副作用/禁忌等情報) を返す。
    1ファイルに複数の販売名・YJコードが含まれる場合は、
    共通情報（禁忌・相互作用・副作用等）は全ブランドで共有する前提。
    """
    try:
        tree = ET.parse(filepath)
    except ET.ParseError as e:
        return None, f"XML parse error: {e}"

    root = tree.getroot()

    generic_name = _text_all(root.find(f".//{TAG['generic_name']}"))
    therapeutic_classification = _text_all(root.find(f".//{TAG['therapeutic_classification']}"))
    indications = _text_all(root.find(f".//{TAG['indications']}"))
    dose_admin = _text_all(root.find(f".//{TAG['dose_admin']}"))
    contraindications = _text_all(root.find(f".//{TAG['contraindications']}"))
    application_precautions = _text_all(root.find(f".//{TAG['application_precautions']}"))

    # 販売名・YJコードは ApprovalEtc 配下に複数存在しうる
    brands = []
    for approval in _find_all(root, TAG["approval_etc"]):
        name = _text_all(approval.find(f".//{TAG['brand_name']}"))
        yj = _text_all(approval.find(f".//{TAG['yj_code']}"))
        if name or yj:
            brands.append({"brand_name": name, "yj_code": yj})
    if not brands:
        # ApprovalEtc構造が想定と異なる場合のフォールバック
        name = _text_all(root.find(f".//{TAG['brand_name']}"))
        yj = _text_all(root.find(f".//{TAG['yj_code']}"))
        brands.append({"brand_name": name, "yj_code": yj})

    # 相互作用：併用禁忌・併用注意
    contra_combi_rows = []
    caution_combi_rows = []
    interactions_root = root.find(f".//{TAG['interactions']}")
    if interactions_root is not None:
        contra_block = interactions_root.find(f".//{TAG['contra_combi']}")
        if contra_block is not None:
            for item in contra_block.iter(TAG["contra_combi_item"]):
                contra_combi_rows.append(parse_interaction_table(item))
        caution_block = interactions_root.find(f".//{TAG['caution_combi']}")
        if caution_block is not None:
            for item in caution_block.iter(TAG["caution_combi_item"]):
                caution_combi_rows.append(parse_interaction_table(item))

    # 重大な副作用
    serious_adverse_text = ""
    adverse_root = root.find(f".//{TAG['adverse_events']}")
    if adverse_root is not None:
        serious_elem = adverse_root.find(f".//{TAG['serious_adverse']}")
        serious_adverse_text = _text_all(serious_elem)

    common = {
        "generic_name": generic_name,
        "therapeutic_classification": therapeutic_classification,
        "indications": indications,
        "dose_admin": dose_admin,
        "contraindications": contraindications,
        "application_precautions": application_precautions,
        "serious_adverse_events": serious_adverse_text,
        "contra_combi_rows": contra_combi_rows,
        "caution_combi_rows": caution_combi_rows,
        "source_file": filepath.name,
    }
    return {"brands": brands, "common": common}, None


# ---------------------------------------------------------------------------
# SQLite スキーマ
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS drug_master (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_name TEXT,
    yj_code TEXT,
    generic_name TEXT,
    therapeutic_classification TEXT,
    indications TEXT,
    dose_admin TEXT,
    contraindications TEXT,
    application_precautions TEXT,
    serious_adverse_events TEXT,
    source_file TEXT,
    is_in_formulary INTEGER DEFAULT 0,
    UNIQUE(yj_code, brand_name)
);

CREATE TABLE IF NOT EXISTS drug_interaction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drug_master_id INTEGER NOT NULL,
    interaction_type TEXT CHECK(interaction_type IN ('contraindicated', 'caution')),
    drug_name_or_class TEXT,
    clinical_symptom_action TEXT,
    mechanism_risk_factor TEXT,
    FOREIGN KEY(drug_master_id) REFERENCES drug_master(id)
);

CREATE TABLE IF NOT EXISTS drug_pair_interaction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drug_a_id INTEGER NOT NULL,
    drug_b_id INTEGER NOT NULL,
    interaction_type TEXT CHECK(interaction_type IN ('contraindicated', 'caution')),
    source_text TEXT,
    FOREIGN KEY(drug_a_id) REFERENCES drug_master(id),
    FOREIGN KEY(drug_b_id) REFERENCES drug_master(id)
);

CREATE INDEX IF NOT EXISTS idx_pair_a ON drug_pair_interaction(drug_a_id);
CREATE INDEX IF NOT EXISTS idx_pair_b ON drug_pair_interaction(drug_b_id);
CREATE INDEX IF NOT EXISTS idx_drug_master_brand ON drug_master(brand_name);
CREATE INDEX IF NOT EXISTS idx_drug_master_generic ON drug_master(generic_name);
CREATE INDEX IF NOT EXISTS idx_interaction_drug ON drug_interaction(drug_master_id);
"""


def load_formulary(path: Path):
    if not path:
        return set()
    names = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                names.add(line)
    return names


def ingest(input_dir: Path, db_path: Path, formulary_path: Path = None):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    cur = conn.cursor()

    formulary_names = load_formulary(formulary_path)

    xml_files = sorted(input_dir.glob("*.xml"))
    if not xml_files:
        print(f"[警告] {input_dir} にXMLファイルが見つかりません", file=sys.stderr)

    ok, ng = 0, 0
    for fp in xml_files:
        parsed, err = parse_tenpu_file(fp)
        if err:
            print(f"[エラー] {fp.name}: {err}", file=sys.stderr)
            ng += 1
            continue

        common = parsed["common"]
        for brand in parsed["brands"]:
            in_formulary = int(
                bool(formulary_names)
                and (
                    brand["brand_name"] in formulary_names
                    or common["generic_name"] in formulary_names
                )
            )
            cur.execute(
                """
                INSERT INTO drug_master
                    (brand_name, yj_code, generic_name, therapeutic_classification, indications, dose_admin,
                     contraindications, application_precautions, serious_adverse_events,
                     source_file, is_in_formulary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(yj_code, brand_name) DO UPDATE SET
                    generic_name=excluded.generic_name,
                    therapeutic_classification=excluded.therapeutic_classification,
                    indications=excluded.indications,
                    dose_admin=excluded.dose_admin,
                    contraindications=excluded.contraindications,
                    application_precautions=excluded.application_precautions,
                    serious_adverse_events=excluded.serious_adverse_events,
                    source_file=excluded.source_file,
                    is_in_formulary=excluded.is_in_formulary
                """,
                (
                    brand["brand_name"], brand["yj_code"], common["generic_name"],
                    common["therapeutic_classification"], common["indications"], common["dose_admin"],
                    common["contraindications"], common["application_precautions"],
                    common["serious_adverse_events"], common["source_file"], in_formulary,
                ),
            )
            drug_master_id = cur.execute(
                "SELECT id FROM drug_master WHERE yj_code=? AND brand_name=?",
                (brand["yj_code"], brand["brand_name"]),
            ).fetchone()[0]

            # 既存の相互作用行を入れ替え（再取り込み時の重複防止）
            cur.execute(
                "DELETE FROM drug_interaction WHERE drug_master_id=?", (drug_master_id,)
            )
            for row in common["contra_combi_rows"]:
                cur.execute(
                    """INSERT INTO drug_interaction
                       (drug_master_id, interaction_type, drug_name_or_class,
                        clinical_symptom_action, mechanism_risk_factor)
                       VALUES (?, 'contraindicated', ?, ?, ?)""",
                    (drug_master_id, row["drug_name_or_class"],
                     row["clinical_symptom_action"], row["mechanism_risk_factor"]),
                )
            for row in common["caution_combi_rows"]:
                cur.execute(
                    """INSERT INTO drug_interaction
                       (drug_master_id, interaction_type, drug_name_or_class,
                        clinical_symptom_action, mechanism_risk_factor)
                       VALUES (?, 'caution', ?, ?, ?)""",
                    (drug_master_id, row["drug_name_or_class"],
                     row["clinical_symptom_action"], row["mechanism_risk_factor"]),
                )
        ok += 1

    matched = auto_match_pair_interactions(conn)
    conn.commit()
    conn.close()
    print(f"取り込み完了: 成功 {ok} ファイル / エラー {ng} ファイル -> {db_path}")
    print(f"自動突合した相互作用ペア: {matched} 件")


def auto_match_pair_interactions(conn):
    """
    drug_interaction（各薬が持つ「相手薬剤名・分類名」のテキスト）を、
    drug_master に登録済みの全薬剤の一般名・商品名と突合し、
    実際に組み合わせて選択されたときに警告を出せるペアを
    drug_pair_interaction に自動生成する。

    薬効分類名表記（例:「ジギタリス製剤」）は drug_alias.ALIAS_MAP で
    代表的な一般名に展開してから照合する。
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM drug_pair_interaction")

    drugs = cur.execute(
        "SELECT id, brand_name, generic_name FROM drug_master"
    ).fetchall()

    interactions = cur.execute(
        """SELECT drug_master_id, interaction_type, drug_name_or_class
           FROM drug_interaction"""
    ).fetchall()

    matched = 0
    seen_pairs = set()

    for owner_id, itype, mention_text in interactions:
        for other_id, other_brand, other_generic in drugs:
            if other_id == owner_id:
                continue
            if interaction_text_mentions(mention_text, other_generic, other_brand):
                pair_key = tuple(sorted((owner_id, other_id))) + (itype,)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                a_id, b_id = sorted((owner_id, other_id))
                cur.execute(
                    """INSERT INTO drug_pair_interaction
                       (drug_a_id, drug_b_id, interaction_type, source_text)
                       VALUES (?, ?, ?, ?)""",
                    (a_id, b_id, itype, mention_text),
                )
                matched += 1
    return matched


def main():
    ap = argparse.ArgumentParser(description="PMDA添付文書XML -> KarteNo用SQLite クレンジング")
    ap.add_argument("--input-dir", required=True, type=Path, help="添付文書XMLを置いたディレクトリ")
    ap.add_argument("--db", required=True, type=Path, help="出力先SQLiteファイル")
    ap.add_argument("--formulary", type=Path, default=None,
                     help="院内処方リスト（1行1薬剤名、一般名または販売名）テキストファイル")
    args = ap.parse_args()
    ingest(args.input_dir, args.db, args.formulary)


if __name__ == "__main__":
    main()
