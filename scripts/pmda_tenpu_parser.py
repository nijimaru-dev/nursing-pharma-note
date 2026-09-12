# -*- coding: utf-8 -*-
"""
pmda_tenpu_parser.py
PMDA「医療用医薬品 添付文書等情報検索」からダウンロードした
新記載要領（XML形式）の添付文書ファイル群を読み込み、
KarteNo用にクレンジングしてSQLiteへ格納するスクリプト。

前提：
- 入力はPMDAサイトから個別にダウンロードしたXMLファイル群（1薬剤=1ファイルが基本、
  ただし1ファイルに複数の販売名・YJコードが含まれる場合がある）
- PMDAの一括ダウンロードデータは「薬品名フォルダ1つにつきXML1つ」という
  サブフォルダ構造になっているため、--input-dir 配下は再帰的に検索する
  （画像ファイル等は無視し、拡張子.xmlのみを対象とする）
- タグ名は製薬協「医療用医薬品添付文書情報の電子ファイル作成の手引き－XML形式－」
  （2019年5月 暫定版第1版）4.3項目名一覧に基づく。ただし実データはルート要素に
  XML名前空間が付与されているため、パース時に名前空間プレフィックスを除去してから
  タグ名で検索している（_strip_namespaces参照）
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
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from drug_alias import expand_aliases


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
    "other_adverse_events": "OtherAdverseEvents",
    "other_adverse_table": "OtherAdverse",
    "date_of_revision": "DateOfPreparationOrRevision",
    "preparation_or_revision": "PreparationOrRevision",
    "year_month": "YearMonth",
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


def _strip_namespaces(root):
    """
    実際のPMDA添付文書XMLはルート要素に
    xmlns="http://info.pmda.go.jp/namespace/prescription_drugs/package_insert/1.0"
    のような名前空間が付与されており、素のタグ名（"GenericName"等）での
    find/iter が一致しない（該当項目が静かに空文字になる）。
    将来の名前空間URI変更にも耐えられるよう、URIをハードコードせず
    "{...}"プレフィックスを機械的に剥がす。
    """
    for elem in root.iter():
        if isinstance(elem.tag, str) and elem.tag.startswith("{"):
            elem.tag = elem.tag.split("}", 1)[1]
    return root


def parse_interaction_item(item_elem):
    """
    10.1併用禁忌 / 10.2併用注意 のテーブル1件分（ContraIndication / PrecautionsForCombi）
    から 薬剤名等・臨床症状措置方法・機序危険因子 を抜き出す。

    実データの構造は
        <ContraIndication>/<PrecautionsForCombi>
          <WidthDefinition>...</WidthDefinition>   列幅定義。データではない
          <Drug>
            <DrugName>...</DrugName>
            <ClinSymptomsAndMeasures>...</ClinSymptomsAndMeasures>
            <MechanismAndRiskFactors>...</MechanismAndRiskFactors>
          </Drug>
          （<Drug>が複数並ぶ場合もある）
        </ContraIndication>
    のように、実データは<Drug>配下にタグ名で3項目が入っている。
    1テーブル項目につき複数<Drug>があり得るため、Drugごとに1行を返す（リスト）。

    <Drug>が見つからない未知の構造のファイル向けに、旧来の「直接の子要素の
    並び順（薬剤名→臨床症状・措置方法→機序・危険因子）」をフォールバックとして残す。
    """
    rows = []
    drug_elems = item_elem.findall("Drug")
    if drug_elems:
        for drug in drug_elems:
            rows.append({
                "drug_name_or_class": _text_all(drug.find("DrugName")),
                "clinical_symptom_action": _text_all(drug.find("ClinSymptomsAndMeasures")),
                "mechanism_risk_factor": _text_all(drug.find("MechanismAndRiskFactors")),
            })
        return rows

    # フォールバック：位置ベース（WidthDefinition等を除いた直接の子要素の並び順）
    children = [c for c in list(item_elem) if c.tag != "WidthDefinition"]
    texts = [_text_all(c) for c in children]
    drug_name = texts[0] if len(texts) >= 1 else ""
    clinical = texts[1] if len(texts) >= 2 else ""
    mechanism = texts[2] if len(texts) >= 3 else ""
    return [{
        "drug_name_or_class": drug_name,
        "clinical_symptom_action": clinical,
        "mechanism_risk_factor": mechanism,
    }]


def parse_other_adverse_events(adverse_root):
    """
    11.2 その他の副作用（重大な副作用に至らない、頻度の高い一般的な副作用）を抽出する。

    実データは「器官別分類（Category）× 頻度区分（Frequency）」のマトリクス表で、
        <OtherAdverseEvents>
          <OtherAdverseEvent>
            <OtherAdverse>
              <CategoryDefinition><Category id="OTHER1_TYPE1">循環器</Category>...</CategoryDefinition>
              <FrequencyDefinition><Frequency id="OTHER1_FRQ1">2%以上</Frequency>...</FrequencyDefinition>
              <AdverseReactions>
                <AdverseReactionDescription categoryRef="OTHER1_TYPE1" frequencyRef="OTHER1_FRQ2">
                  めまい・ふらつき、動悸
                </AdverseReactionDescription>
                ...
              </AdverseReactions>
            </OtherAdverse>
          </OtherAdverseEvent>
        </OtherAdverseEvents>
    のように、症状テキスト（AdverseReactionDescription）がcategoryRef属性で
    分類（Category）を参照する構造になっている。個別の頻度％は症状テキスト本文に
    含まれていることが多いため、frequencyRef（頻度区分）は使わず、
    「分類：症状」の形でテキスト化する（分類が無い場合は症状のみ）。
    """
    if adverse_root is None:
        return ""
    other_root = adverse_root.find(f".//{TAG['other_adverse_events']}")
    if other_root is None:
        return ""

    lines = []
    for table in other_root.iter(TAG["other_adverse_table"]):
        category_map = {}
        cat_def = table.find("CategoryDefinition")
        if cat_def is not None:
            for cat in cat_def.findall("Category"):
                cat_id = cat.get("id")
                if cat_id:
                    category_map[cat_id] = _text_all(cat)

        reactions_root = table.find("AdverseReactions")
        if reactions_root is None:
            continue
        for reaction in reactions_root.findall("AdverseReactionDescription"):
            text = _text_all(reaction)
            if not text:
                continue
            category = category_map.get(reaction.get("categoryRef"), "")
            lines.append(f"{category}：{text}" if category else text)

    return "\n".join(lines)


def parse_revision_date(root):
    """
    添付文書の「作成又は改訂年月」（DateOfPreparationOrRevision）から、
    最新の改訂年月（id="今回"のPreparationOrRevision配下のYearMonth、
    "YYYY-MM"形式）を抽出する。id="前回"/"今回"の出現順は一定でないため、
    idで明示的に引く（位置に依存しない）。
    """
    dor = root.find(f".//{TAG['date_of_revision']}")
    if dor is None:
        return ""
    entries = dor.findall(TAG["preparation_or_revision"])
    for entry in entries:
        if entry.get("id") == "今回":
            return _text_all(entry.find(TAG["year_month"]))
    # id="今回"が見つからない未知の構造向けフォールバック：先頭要素を使う
    if entries:
        return _text_all(entries[0].find(TAG["year_month"]))
    return ""


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

    root = _strip_namespaces(tree.getroot())

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
                contra_combi_rows.extend(parse_interaction_item(item))
        caution_block = interactions_root.find(f".//{TAG['caution_combi']}")
        if caution_block is not None:
            for item in caution_block.iter(TAG["caution_combi_item"]):
                caution_combi_rows.extend(parse_interaction_item(item))

    # 重大な副作用 / その他の副作用
    serious_adverse_text = ""
    other_adverse_text = ""
    adverse_root = root.find(f".//{TAG['adverse_events']}")
    if adverse_root is not None:
        serious_elem = adverse_root.find(f".//{TAG['serious_adverse']}")
        serious_adverse_text = _text_all(serious_elem)
        other_adverse_text = parse_other_adverse_events(adverse_root)

    revision_date = parse_revision_date(root)

    common = {
        "generic_name": generic_name,
        "therapeutic_classification": therapeutic_classification,
        "indications": indications,
        "dose_admin": dose_admin,
        "contraindications": contraindications,
        "application_precautions": application_precautions,
        "serious_adverse_events": serious_adverse_text,
        "other_adverse_events": other_adverse_text,
        "revision_date": revision_date,
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
    other_adverse_events TEXT,
    revision_date TEXT,
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

-- 【2026-09-12改称】旧称drug_a_id/drug_b_idから min_id/max_id に改称。
-- 突合ロジック側は元々 sorted() で常に小さいidをa、大きいidをbに入れており、
-- 実質min/max運用だったため、その不変条件をスキーマ上でも明示・強制する
-- （CHECKで min_id < max_id を保証し、「同じペアをA視点・B視点の2通りで
-- 持ててしまう」余地自体を無くす）。既存DBの移行はmigrate_pair_interaction_schema参照。
CREATE TABLE IF NOT EXISTS drug_pair_interaction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    min_id INTEGER NOT NULL,
    max_id INTEGER NOT NULL,
    interaction_type TEXT CHECK(interaction_type IN ('contraindicated', 'caution')),
    source_text TEXT,
    CHECK(min_id < max_id),
    FOREIGN KEY(min_id) REFERENCES drug_master(id),
    FOREIGN KEY(max_id) REFERENCES drug_master(id)
);

CREATE INDEX IF NOT EXISTS idx_pair_min ON drug_pair_interaction(min_id);
CREATE INDEX IF NOT EXISTS idx_pair_max ON drug_pair_interaction(max_id);
CREATE INDEX IF NOT EXISTS idx_drug_master_brand ON drug_master(brand_name);
CREATE INDEX IF NOT EXISTS idx_drug_master_generic ON drug_master(generic_name);
CREATE INDEX IF NOT EXISTS idx_interaction_drug ON drug_interaction(drug_master_id);
"""


def ensure_column(conn, table, column, coltype="TEXT"):
    """
    CREATE TABLE IF NOT EXISTSは既存テーブルには効かない（新規カラムが増えない）ため、
    既存のkarteno_drugs.dbに対してスキーマ変更を反映するための簡易マイグレーション。
    """
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def migrate_pair_interaction_schema(conn):
    """
    2026-09-12：drug_pair_interactionの列名をdrug_a_id/drug_b_idから
    min_id/max_idへ改称するマイグレーション。

    元々auto_match_pair_interactions()はsorted()で常に小さいidをa、
    大きいidをbに入れており（＝同じペアをA視点・B視点の2通りで持つことは
    DBレベルでは元から無かった）、実質min/max運用だった。それをスキーマ上でも
    明示するための改称であり、データの意味自体は変わらない。

    SQLiteはCHECK制約を既存テーブルへ後から追加できないため、新しいテーブルを
    作ってデータをコピーし、入れ替える方式を取る。既に新スキーマ（min_id列が
    存在）なら何もしない（何度呼んでも安全＝冪等）。
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(drug_pair_interaction)").fetchall()}
    if not cols or "min_id" in cols:
        return
    if "drug_a_id" not in cols:
        # 想定外のスキーマ。安全側に倒して何もしない。
        return

    conn.execute(
        """
        CREATE TABLE drug_pair_interaction_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            min_id INTEGER NOT NULL,
            max_id INTEGER NOT NULL,
            interaction_type TEXT CHECK(interaction_type IN ('contraindicated', 'caution')),
            source_text TEXT,
            CHECK(min_id < max_id),
            FOREIGN KEY(min_id) REFERENCES drug_master(id),
            FOREIGN KEY(max_id) REFERENCES drug_master(id)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO drug_pair_interaction_new (id, min_id, max_id, interaction_type, source_text)
        SELECT id, MIN(drug_a_id, drug_b_id), MAX(drug_a_id, drug_b_id), interaction_type, source_text
        FROM drug_pair_interaction
        """
    )
    conn.execute("DROP TABLE drug_pair_interaction")
    conn.execute("ALTER TABLE drug_pair_interaction_new RENAME TO drug_pair_interaction")
    conn.execute("DROP INDEX IF EXISTS idx_pair_a")
    conn.execute("DROP INDEX IF EXISTS idx_pair_b")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pair_min ON drug_pair_interaction(min_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pair_max ON drug_pair_interaction(max_id)")
    conn.commit()
    print(
        "[移行] drug_pair_interactionをdrug_a_id/drug_b_id -> min_id/max_id形式へ変換しました",
        file=sys.stderr,
    )


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
    ensure_column(conn, "drug_master", "other_adverse_events")
    ensure_column(conn, "drug_master", "revision_date")
    cur = conn.cursor()

    formulary_names = load_formulary(formulary_path)

    # 実際のPMDA一括ダウンロードデータは「1薬剤=1サブフォルダ」構造のため再帰的に探索する
    xml_files = sorted(input_dir.rglob("*.xml"))
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
                     contraindications, application_precautions, serious_adverse_events, other_adverse_events,
                     revision_date, source_file, is_in_formulary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(yj_code, brand_name) DO UPDATE SET
                    generic_name=excluded.generic_name,
                    therapeutic_classification=excluded.therapeutic_classification,
                    indications=excluded.indications,
                    dose_admin=excluded.dose_admin,
                    contraindications=excluded.contraindications,
                    application_precautions=excluded.application_precautions,
                    serious_adverse_events=excluded.serious_adverse_events,
                    other_adverse_events=excluded.other_adverse_events,
                    revision_date=excluded.revision_date,
                    source_file=excluded.source_file,
                    is_in_formulary=excluded.is_in_formulary
                """,
                (
                    brand["brand_name"], brand["yj_code"], common["generic_name"],
                    common["therapeutic_classification"], common["indications"], common["dose_admin"],
                    common["contraindications"], common["application_precautions"],
                    common["serious_adverse_events"], common["other_adverse_events"],
                    common["revision_date"], common["source_file"], in_formulary,
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


def _build_alias_lookup(drugs):
    """
    全薬剤の一般名・商品名・drug_alias.pyのエイリアス展開結果を集約し、
    「候補文字列 -> それを名乗りうる薬剤idの集合」の辞書と、
    それら候補文字列すべてを1本にまとめた事前コンパイル済み正規表現を作る。

    drugsは (id, brand_name, generic_name) のタプルのリスト。
    候補文字列が1つも無い場合はpatternにNoneを返す。
    """
    name_to_drug_ids = {}
    for drug_id, brand_name, generic_name in drugs:
        candidates = expand_aliases(generic_name)
        if brand_name:
            candidates |= expand_aliases(brand_name)
        for name in candidates:
            if not name:
                continue
            name_to_drug_ids.setdefault(name, set()).add(drug_id)

    if not name_to_drug_ids:
        return None, name_to_drug_ids

    # 【重要】候補文字列どうしが「同じ開始位置」で競合するケースへの対処。
    # 例：「フェキソフェナジン塩酸塩」（単剤）と「フェキソフェナジン塩酸塩・塩酸
    # プソイドエフェドリン」（合剤）は本文中で同じ文字位置から始まりうる。
    # 正規表現の選択（|）は最初にマッチした選択肢しか採用しないため、単純に
    # 「1文字ずつ位置をずらして毎回1つだけ拾う」実装だと、同じ開始位置にある
    # 短い候補（単剤側）が長い候補（合剤側）に完全に隠れて検出漏れになる。
    # テキスト中の同じ開始位置に2つの候補文字列が両方とも一致しうるのは、
    # 数学的に「短い方が長い方の接頭辞である場合」に限られる。そこで、
    # 各候補文字列について「それ自身も候補集合に含まれる真の接頭辞」を
    # あらかじめ全列挙しておき、長い候補がマッチした時点で、接頭辞側の
    # 薬剤idもまとめて拾えるようにする。
    prefix_drug_ids = {}
    for name in name_to_drug_ids:
        extra = set()
        for k in range(1, len(name)):
            prefix = name[:k]
            if prefix in name_to_drug_ids:
                extra |= name_to_drug_ids[prefix]
        if extra:
            prefix_drug_ids[name] = extra

    # 長い候補文字列を先に試すことで、同じ開始位置で複数の候補が一致しうる
    # ときに、より長い（＝より具体的な）候補を正規表現に拾わせる。
    # 短い候補（接頭辞）側の薬剤idはprefix_drug_idsで別途補完する。
    ordered_names = sorted(name_to_drug_ids.keys(), key=len, reverse=True)
    alternation = "|".join(re.escape(name) for name in ordered_names)
    # ゼロ幅の先読みにすることで、マッチした文字列の内側の別位置から始まる
    # 別候補（例：合剤名の途中から始まる他の薬剤名）も取りこぼさずに検出できる
    # ようにする（finditerは1文字ずつ開始位置をずらしながら全位置を走査する）。
    pattern = re.compile(f"(?=({alternation}))")
    return pattern, name_to_drug_ids, prefix_drug_ids


def auto_match_pair_interactions(conn):
    """
    drug_interaction（各薬が持つ「相手薬剤名・分類名」のテキスト）を、
    drug_master に登録済みの全薬剤の一般名・商品名と突合し、
    実際に組み合わせて選択されたときに警告を出せるペアを
    drug_pair_interaction に自動生成する。

    薬効分類名表記（例:「ジギタリス製剤」）は drug_alias.ALIAS_MAP で
    代表的な一般名に展開してから照合する。

    【2026-09-12修正】以前は「相互作用記載1件 × 全薬剤」の二重ループで、
    薬剤ごとに毎回 interaction_text_mentions() を呼んでいたため、
    薬剤数×相互作用記載数（数万×1万＝数億回）の文字列検索が発生し重かった。
    全薬剤の候補文字列（一般名・商品名・エイリアス展開結果）を事前に1つの
    正規表現へコンパイルしておき（_build_alias_lookup）、相互作用記載1件につき
    その正規表現を1回走らせるだけで該当する全薬剤idを取得する方式に変更した。
    突合結果（drug_pair_interactionの内容）は変更前と同一になることを、
    既存データでの再実行・件数比較で確認済み。

    【2026-09-11修正】drug_pair_interaction.source_text には、突合に使った
    drug_name_or_class（相手薬剤名・分類名の表記そのもの）ではなく、
    clinical_symptom_action（臨床症状・措置方法＝「なぜ危険か」の説明文）を
    格納する。以前はdrug_name_or_classを格納していたため、複数薬チェック画面に
    「利尿剤カリウム排泄型利尿剤...等」のような分類名の羅列だけが表示され、
    肝心の危険性の説明文が表示されない不具合があった。
    """
    migrate_pair_interaction_schema(conn)

    cur = conn.cursor()
    cur.execute("DELETE FROM drug_pair_interaction")

    drugs = cur.execute(
        "SELECT id, brand_name, generic_name FROM drug_master"
    ).fetchall()

    interactions = cur.execute(
        """SELECT drug_master_id, interaction_type, drug_name_or_class, clinical_symptom_action
           FROM drug_interaction"""
    ).fetchall()

    pattern, name_to_drug_ids, prefix_drug_ids = _build_alias_lookup(drugs)

    matched = 0
    if pattern is None:
        return matched

    seen_pairs = set()

    for owner_id, itype, mention_text, clinical_text in interactions:
        text = (mention_text or "").strip()
        if not text:
            continue

        other_ids = set()
        for m in pattern.finditer(text):
            matched_name = m.group(1)
            other_ids |= name_to_drug_ids.get(matched_name, set())
            # 同じ開始位置にある、より短い接頭辞候補（例：合剤名の中の単剤名）を補完する。
            other_ids |= prefix_drug_ids.get(matched_name, set())
        other_ids.discard(owner_id)

        for other_id in other_ids:
            pair_key = tuple(sorted((owner_id, other_id))) + (itype,)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            min_id, max_id = sorted((owner_id, other_id))
            cur.execute(
                """INSERT INTO drug_pair_interaction
                   (min_id, max_id, interaction_type, source_text)
                   VALUES (?, ?, ?, ?)""",
                (min_id, max_id, itype, clinical_text or mention_text),
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
