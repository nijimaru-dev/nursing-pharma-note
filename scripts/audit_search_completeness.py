# -*- coding: utf-8 -*-
"""
audit_search_completeness.py
検索データ完全性の全件監査（読み取り専用）。

【厳守事項】
- このスクリプトは監査専用。karteno_drugs.db・site/data/・既存スクリプトの
  いずれも一切書き換えない（読み込みのみ）。
- 生データ（data-raw/配下）も一切変更しない。
- 「17,728件」等の既知の数字を母数として仮定せず、各段階を実測する。

【発見済みの根本原因（メインテート個別検証で確認）】
pmda_tenpu_parser.py の parse_tenpu_file() は、
    for approval in root.iter("ApprovalEtc"):
        name = _text_all(approval.find(".//ApprovalBrandName"))
        yj   = _text_all(approval.find(".//YJCode"))
という実装になっている。しかし実データでは <ApprovalEtc> 1個の中に
<DetailBrandName id="BRD_Drug1">, <DetailBrandName id="BRD_Drug2">, ...
という「規格違いの製品」を表す子要素が複数並んでおり、真に反復すべきは
ApprovalEtc（1ファイルにほぼ常に1個）ではなく DetailBrandName（1ファイルに
規格の数だけ存在）である。.find()（単数形）が ApprovalEtc 配下の最初の
ApprovalBrandName/YJCodeしか拾わないため、2番目以降の規格が
構造化の時点で（drug_masterに一度も入らないまま）欠落する。

このスクリプトでは、上記の「誤ったApprovalEtc単位の抽出」（現行ロジックの再現）と
「正しいDetailBrandName単位の抽出」（監査専用の修正版ロジック、本番コードには反映しない）の
両方を実施し、差分を機械的に検出する。

使い方：
    python audit_search_completeness.py
"""

import csv
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from pmda_tenpu_parser import parse_tenpu_file, _text_all  # noqa: E402

RAW_DIR = REPO_ROOT / "data-raw" / "pmda_all_sgml_xml_20260911" / "SGML_XML"
DB_PATH = REPO_ROOT / "karteno_drugs.db"
INDEX_JSON = REPO_ROOT / "site" / "data" / "index.json"
OUT_DIR = REPO_ROOT / "audit"
OUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# 監査専用：DetailBrandName単位の正しい抽出（本番コードは変更しない）
# ---------------------------------------------------------------------------
def extract_brands_correct(root):
    """
    ApprovalEtc配下のDetailBrandNameを1件ずつ正しく反復する監査専用ロジック。
    現行pmda_tenpu_parser.pyのバグ（ApprovalEtc単位で.find()する）を修正した
    「あるべき抽出結果」を返す。
    """
    brands = []
    for approval in root.iter("ApprovalEtc"):
        details = approval.findall("DetailBrandName")
        if details:
            for d in details:
                name = _text_all(d.find(".//ApprovalBrandName")).strip()
                yj = _text_all(d.find(".//YJCode")).strip()
                if name or yj:
                    brands.append({"brand_name": name, "yj_code": yj})
        else:
            name = _text_all(approval.find(".//ApprovalBrandName")).strip()
            yj = _text_all(approval.find(".//YJCode")).strip()
            if name or yj:
                brands.append({"brand_name": name, "yj_code": yj})
    if not brands:
        name = _text_all(root.find(".//ApprovalBrandName")).strip()
        yj = _text_all(root.find(".//YJCode")).strip()
        brands.append({"brand_name": name, "yj_code": yj})
    return brands


def extract_brands_current(root):
    """現行pmda_tenpu_parser.pyのバグを再現した抽出（ApprovalEtc単位で.find()）。"""
    brands = []
    for approval in root.iter("ApprovalEtc"):
        name = _text_all(approval.find(".//ApprovalBrandName")).strip()
        yj = _text_all(approval.find(".//YJCode")).strip()
        if name or yj:
            brands.append({"brand_name": name, "yj_code": yj})
    if not brands:
        name = _text_all(root.find(".//ApprovalBrandName")).strip()
        yj = _text_all(root.find(".//YJCode")).strip()
        brands.append({"brand_name": name, "yj_code": yj})
    return brands


def strip_namespaces(root):
    for elem in root.iter():
        if isinstance(elem.tag, str) and elem.tag.startswith("{"):
            elem.tag = elem.tag.split("}", 1)[1]
    return root


# ---------------------------------------------------------------------------
# 規格・剤形の正規化（比較専用。元データは変更しない。raw/normalized両方残す）
# ---------------------------------------------------------------------------
ZEN2HAN = str.maketrans("０１２３４５６７８９．", "0123456789.")

STRENGTH_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mg|g|mL|ml|mcg|μg|%|w/v%|単位|kg|L|Ｌ)", re.IGNORECASE
)

FORM_KEYWORDS = [
    ("OD錠", "OD錠"), ("口腔内崩壊錠", "OD錠"),
    ("ドライシロップ", "ドライシロップ"),
    ("錠", "錠"), ("カプセル", "カプセル"), ("顆粒", "顆粒"), ("散", "散剤"),
    ("シロップ", "シロップ"),
    ("注射用", "注射剤"), ("注射液", "注射剤"), ("点滴静注", "注射剤"), ("注", "注射剤"),
    ("軟膏", "軟膏"), ("クリーム", "クリーム"), ("ローション", "ローション"),
    ("坐剤", "坐剤"), ("坐薬", "坐剤"),
    ("テープ", "貼付剤"), ("パップ", "貼付剤"), ("貼付剤", "貼付剤"),
    ("点眼液", "点眼剤"), ("点鼻液", "点鼻剤"),
    ("吸入液", "吸入剤"), ("吸入用", "吸入剤"),
    ("トローチ", "トローチ"), ("液", "液剤"),
]


def normalize_strength_text(brand_name):
    return unicodedata.normalize("NFKC", brand_name or "").translate(ZEN2HAN)


def extract_strengths(brand_name):
    """brand_nameから規格表記(raw)を全て抽出し、正規化した値も返す。"""
    norm = normalize_strength_text(brand_name)
    raws = []
    normed = []
    for m in STRENGTH_RE.finditer(norm):
        normed.append(f"{float(m.group(1))}{m.group(2).lower()}" if "." in m.group(1) or True else m.group(0))
    # raw側はNFKC正規化前のbrand_nameに対して同じ位置関係で探すのは複雑なので、
    # raw表記は「正規化後にマッチした部分文字列に対応する、正規化前のbrand_name全体」を
    # 監査結果に残す方針にする（詳細はCSVのbrand_name列そのものがraw）。
    return normed


def extract_form(brand_name):
    for kw, label in FORM_KEYWORDS:
        if kw in (brand_name or ""):
            return label
    return "(不明)"


def family_key(generic_name, brand_name):
    """
    同一販売名＋同一成分でグルーピングするためのキー。
    brand_nameから規格の数値部分だけを取り除き、剤形・メーカー表記
    （「サワイ」等）はそのまま残す（別剤形・別メーカーを誤って
    同一グループにしないため）。
    """
    norm = normalize_strength_text(brand_name)
    stripped = STRENGTH_RE.sub("", norm)
    stripped = re.sub(r"\s+", "", stripped)
    return (generic_name or "").strip(), stripped


def sha256_of(path: Path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    log = []

    def p(msg):
        print(msg)
        log.append(msg)

    p("=" * 70)
    p("検索データ完全性監査（読み取り専用）")
    p("=" * 70)

    if not RAW_DIR.exists():
        p(f"[致命的] 生データディレクトリが見つかりません: {RAW_DIR}")
        sys.exit(1)

    # --- Stage 1: PMDA原データ件数 -----------------------------------------
    top_folders = [d for d in RAW_DIR.iterdir() if d.is_dir()]
    all_xml_files = list(RAW_DIR.rglob("*.xml"))
    p(f"\n[Stage1] PMDA原データ件数")
    p(f"  直下フォルダ数: {len(top_folders)}")
    p(f"  XMLファイル総数(再帰): {len(all_xml_files)}")

    # ハッシュで実体の重複（同一添付文書が複数規格フォルダに複製されているケース）を検出
    hash_to_files = defaultdict(list)
    for fp in all_xml_files:
        try:
            h = sha256_of(fp)
        except OSError as e:
            p(f"  [警告] 読み込み失敗: {fp} ({e})")
            continue
        hash_to_files[h].append(fp)

    unique_docs = len(hash_to_files)
    dup_doc_count = sum(1 for files in hash_to_files.values() if len(files) > 1)
    p(f"  ユニークな添付文書(内容ハッシュ基準): {unique_docs}")
    p(f"  複数フォルダに複製されている文書数: {dup_doc_count}")
    p(f"  （重複率: {dup_doc_count/unique_docs*100:.1f}% ※1文書が複数規格フォルダに複製される構造のため）")

    # --- Stage 2: 抽出対象件数（parser の rglob と同一条件） ----------------
    extraction_targets = all_xml_files  # pmda_tenpu_parser.py と同じ rglob("*.xml")
    p(f"\n[Stage2] 抽出対象件数（rglob(\"*.xml\")一致）")
    p(f"  対象ファイル数: {len(extraction_targets)}")
    p(f"  Stage1との差分: {len(extraction_targets) - len(all_xml_files)} (0のはず＝抽出漏れ無し)")

    # --- ユニーク文書ごとに現行ロジック／正しいロジックの両方でパース -------
    p(f"\n[パース中] ユニーク文書 {unique_docs} 件を現行ロジック・修正版ロジックの両方でパース...")
    doc_results = {}  # hash -> dict
    parse_error_count = 0
    for i, (h, files) in enumerate(hash_to_files.items()):
        rep = files[0]
        try:
            tree = ET.parse(rep)
            root = strip_namespaces(tree.getroot())
        except ET.ParseError as e:
            parse_error_count += 1
            doc_results[h] = {"error": str(e), "files": files}
            continue

        generic_name = _text_all(root.find(".//GenericName"))
        current_brands = extract_brands_current(root)
        correct_brands = extract_brands_correct(root)
        doc_results[h] = {
            "files": files,
            "generic_name": generic_name,
            "current_brands": current_brands,
            "correct_brands": correct_brands,
        }
        if (i + 1) % 2000 == 0:
            p(f"  ...{i+1}/{unique_docs} 件処理済み")

    p(f"  パース完了。パースエラー: {parse_error_count} 件")

    # --- Stage 3: 構造化された薬剤件数（現行ロジック / 修正版ロジックの両方） ---
    current_records = []  # (generic_name, brand_name, yj_code, source_hash)
    correct_records = []
    for h, r in doc_results.items():
        if "error" in r:
            continue
        for b in r["current_brands"]:
            current_records.append((r["generic_name"], b["brand_name"], b["yj_code"], h))
        for b in r["correct_brands"]:
            correct_records.append((r["generic_name"], b["brand_name"], b["yj_code"], h))

    p(f"\n[Stage3] 構造化された薬剤件数（重複UPSERT前、ユニーク文書ベース）")
    p(f"  現行ロジックでの抽出件数: {len(current_records)}")
    p(f"  修正版ロジックでの抽出件数: {len(correct_records)}")
    p(f"  差分（修正版 - 現行 = 欠落していた件数）: {len(correct_records) - len(current_records)}")

    # UNIQUE(yj_code, brand_name) 相当のUPSERTをシミュレート
    def upsert_sim(records):
        d = {}
        for generic, brand, yj, h in records:
            key = (yj.strip(), brand.strip())
            d[key] = (generic, brand, yj, h)
        return d

    current_upserted = upsert_sim(current_records)
    correct_upserted = upsert_sim(correct_records)
    p(f"\n  UNIQUE(yj_code, brand_name)適用後:")
    p(f"    現行ロジック: {len(current_upserted)} 件（重複{len(current_records)-len(current_upserted)}件を統合）")
    p(f"    修正版ロジック: {len(correct_upserted)} 件（重複{len(correct_records)-len(correct_upserted)}件を統合）")

    # --- Stage 4: 販売名件数 -------------------------------------------------
    current_brand_names = {b for (_, b) in current_upserted.keys()}
    correct_brand_names = {b for (_, b) in correct_upserted.keys()}
    p(f"\n[Stage4] 販売名件数（ユニークbrand_name）")
    p(f"  現行ロジック: {len(current_brand_names)}")
    p(f"  修正版ロジック: {len(correct_brand_names)}")

    # --- Stage 5: 規格件数 ----------------------------------------------------
    # 「販売名1件が複数規格を持つ」は無い（規格は販売名文字列に含まれるため
    # 販売名そのものが規格単位）。ここでは「同一販売名文字列」の中に規格数値が
    # 何個現れるか（通常1個）と、家族単位(family_key)での規格バリエーション数を集計する。
    def strength_variation_count(upserted):
        families = defaultdict(set)
        for (yj, brand), (generic, _, _, _) in upserted.items():
            fam = family_key(generic, brand)
            strengths = tuple(extract_strengths(brand))
            families[fam].add(strengths if strengths else (brand,))
        return families

    current_families = strength_variation_count(current_upserted)
    correct_families = strength_variation_count(correct_upserted)
    p(f"\n[Stage5] 規格件数（同一販売名・同一成分ファミリー単位の規格バリエーション数）")
    p(f"  現行ロジックでのファミリー数: {len(current_families)}")
    p(f"  修正版ロジックでのファミリー数: {len(correct_families)}")
    multi_strength_correct = {k: v for k, v in correct_families.items() if len(v) >= 2}
    p(f"  修正版ロジックで規格が2種類以上あるファミリー数: {len(multi_strength_correct)}")

    # --- Stage 6: 剤形件数 -----------------------------------------------------
    def form_counts(upserted):
        c = defaultdict(int)
        for (yj, brand), _ in upserted.items():
            c[extract_form(brand)] += 1
        return c

    current_forms = form_counts(current_upserted)
    correct_forms = form_counts(correct_upserted)
    p(f"\n[Stage6] 剤形件数（brand_nameからのキーワード抽出、簡易版）")
    p(f"  現行ロジック: {dict(sorted(current_forms.items(), key=lambda x: -x[1]))}")
    p(f"  修正版ロジック: {dict(sorted(correct_forms.items(), key=lambda x: -x[1]))}")

    # --- Stage 7: 検索インデックス件数（実際の現行DB / index.json） -----------
    p(f"\n[Stage7] 検索インデックス件数（現行DB・現行index.json＝現在サイトに出ている実データ）")
    db_records = {}
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, brand_name, yj_code, generic_name FROM drug_master").fetchall()
        conn.close()
        for row in rows:
            db_records[(row["yj_code"] or "", row["brand_name"] or "")] = (
                row["generic_name"], row["brand_name"], row["yj_code"], row["id"]
            )
        p(f"  karteno_drugs.db drug_master件数: {len(rows)}")
        p(f"  ユニーク(yj_code, brand_name)件数: {len(db_records)}")
    else:
        p(f"  [警告] {DB_PATH} が見つかりません。DB比較はスキップします。")

    index_count = None
    if INDEX_JSON.exists():
        with open(INDEX_JSON, encoding="utf-8") as f:
            index_data = json.load(f)
        index_count = len(index_data)
        p(f"  site/data/index.json 件数: {index_count}")
        p(f"  drug_master件数との差: {index_count - len(db_records) if db_records else 'N/A'}")
    else:
        p(f"  [警告] {INDEX_JSON} が見つかりません。")

    # --- 現行DBは「現行ロジックで全件パースした場合」と一致するはずかを検証 ---
    p(f"\n[検証] 現行DBは「現行ロジックで生データ全件を再パースした場合」の想定件数と一致するか")
    p(f"  現行ロジック再パース想定件数: {len(current_upserted)}")
    p(f"  現行DBの実件数: {len(db_records)}")
    if db_records and len(current_upserted) != len(db_records):
        p(f"  → 不一致。現行DBは今回の生データ一式そのものから構築されたのではない可能性がある")
        p(f"    （別バージョンのコード／別バージョンの生データで構築された可能性を含め、要調査）")
    elif db_records:
        p(f"  → 件数は一致。ただし中身（どのレコードか）は別途Master-Index比較で検証する")

    # =========================================================================
    # 本題：規格欠落・孤立レコード・重複候補の抽出
    # =========================================================================
    p(f"\n{'='*70}")
    p("規格欠落・孤立レコードの抽出")
    p("=" * 70)

    correct_keys = set(correct_upserted.keys())
    db_keys = set(db_records.keys())

    # Master(あるべき姿=修正版ロジック) → Index(現行DB) 方向：欠落
    missing_keys = correct_keys - db_keys
    p(f"\n[Master→Index] 修正版ロジックでは存在するはずなのに、現行DBに無いレコード: {len(missing_keys)} 件")

    # Index(現行DB) → Master(あるべき姿) 方向：孤立
    orphan_keys = db_keys - correct_keys
    p(f"[Index→Master] 現行DBにあるが、修正版ロジックの再パース結果に無いレコード（孤立候補）: {len(orphan_keys)} 件")

    # メインテート個別検証（監査ロジックが実際に検出できるかの確認）
    maintate_check = [k for k in missing_keys if "メインテート" in correct_upserted[k][1]]
    p(f"\n[個別検証] メインテートの欠落レコード検出数: {len(maintate_check)} 件")
    for k in maintate_check:
        p(f"    - {correct_upserted[k][1]} (YJ:{k[0]})")
    if len(maintate_check) >= 2:
        p("  → 監査ロジックは既知の不具合（メインテート2.5mg/5mg欠落）を正しく検出できている")
    else:
        p("  → [注意] メインテートの既知の欠落を検出できていない。監査ロジックを見直す必要がある")

    # 欠落を「同一ファミリーで一部規格だけ欠落」の形に整理
    family_missing = defaultdict(lambda: {"present": set(), "missing": set(), "generic": ""})
    for k in correct_keys:
        generic, brand, _, _ = correct_upserted[k]
        fam = family_key(generic, brand)
        if k in db_keys:
            family_missing[fam]["present"].add(brand)
        else:
            family_missing[fam]["missing"].add(brand)
        family_missing[fam]["generic"] = generic

    partial_families = {
        fam: v for fam, v in family_missing.items()
        if v["missing"] and v["present"]  # 一部だけ欠落しているファミリー
    }
    fully_missing_families = {
        fam: v for fam, v in family_missing.items()
        if v["missing"] and not v["present"]  # 全規格が欠落しているファミリー（別種の問題）
    }
    p(f"\n[集計] 「一部の規格だけ検索インデックスに存在しない」薬剤ファミリー数: {len(partial_families)}")
    p(f"[集計] 「ファミリー全体が検索インデックスに存在しない」薬剤ファミリー数: {len(fully_missing_families)}")
    p(f"  （後者はDetailBrandNameバグとは別原因＝パースエラー・未収載等の可能性。個別確認が必要）")

    # 重複候補：同一(generic_name, brand_name)で yj_code が複数存在するもの
    p(f"\n[重複候補] 現行DBで、同一(brand_name, generic_name)がyj_code違いで複数存在するもの")
    brand_generic_to_yj = defaultdict(set)
    for (yj, brand), (generic, _, _, _id) in db_records.items():
        brand_generic_to_yj[(brand, generic)].add(yj)
    dup_candidates = {k: v for k, v in brand_generic_to_yj.items() if len(v) > 1}
    p(f"  該当件数: {len(dup_candidates)}")

    # -------------------------------------------------------------------------
    # CSV出力
    # -------------------------------------------------------------------------
    missing_csv = OUT_DIR / "missing-index-strengths.csv"
    with open(missing_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["generic_name", "brand_name_raw", "yj_code", "family_key", "strength_extracted",
                    "form_extracted", "present_siblings_in_family", "source_xml_hash"])
        for k in sorted(missing_keys, key=lambda x: correct_upserted[x][1]):
            generic, brand, yj, h = correct_upserted[k]
            fam = family_key(generic, brand)
            siblings = sorted(family_missing[fam]["present"])
            w.writerow([generic, brand, yj, "|".join(fam), "/".join(extract_strengths(brand)) or "",
                        extract_form(brand), "; ".join(siblings), h[:12]])
    p(f"\n[出力] {missing_csv} ({len(missing_keys)}件)")

    orphan_csv = OUT_DIR / "orphan-index-records.csv"
    with open(orphan_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["db_id", "generic_name", "brand_name", "yj_code"])
        for k in sorted(orphan_keys, key=lambda x: db_records[x][1] or ""):
            generic, brand, yj, db_id = db_records[k]
            w.writerow([db_id, generic, brand, yj])
    p(f"[出力] {orphan_csv} ({len(orphan_keys)}件)")

    dup_csv = OUT_DIR / "duplicate-candidates.csv"
    with open(dup_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["brand_name", "generic_name", "yj_codes"])
        for (brand, generic), yjs in sorted(dup_candidates.items()):
            w.writerow([brand, generic, "; ".join(sorted(yjs))])
    p(f"[出力] {dup_csv} ({len(dup_candidates)}件)")

    # -------------------------------------------------------------------------
    # Markdownレポート出力
    # -------------------------------------------------------------------------
    md_path = OUT_DIR / "search-completeness-audit.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 検索データ完全性監査レポート\n\n")
        f.write("読み取り専用の監査。修正は未実施。データ・コードは一切変更していない。\n\n")
        f.write("## 根本原因（メインテートの個別検証で確認済み）\n\n")
        f.write(
            "`pmda_tenpu_parser.py` の `parse_tenpu_file()` は `ApprovalEtc` 要素単位で "
            "`.find()`（単数形）により `ApprovalBrandName`/`YJCode` を1個だけ取得している。"
            "しかし実データでは1つの `ApprovalEtc` の中に、規格違いの製品ごとの "
            "`DetailBrandName` 要素（例：`id=\"BRD_Drug1\"`, `\"BRD_Drug2\"`, `\"BRD_Drug3\"`）が"
            "複数並んでおり、2番目以降が構造化の時点で欠落する。\n\n"
            "メインテートの場合、`メインテート錠０．６２５ｍｇ`／`メインテート錠２．５ｍｇ`／"
            "`メインテート錠５ｍｇ` の3フォルダは同一の添付文書XML（SHA256一致・byte単位で同一）を"
            "共有しており、この1ファイルの中に3規格分の `DetailBrandName` が入っている。"
            "現行ロジックはこのうち最初の1件（0.625mg）しか抽出できていない。\n\n"
        )
        f.write("## 各段階の件数\n\n")
        f.write("| 段階 | 件数 | 備考 |\n|---|---|---|\n")
        f.write(f"| ①PMDA原データ（フォルダ数） | {len(top_folders)} | data-raw/直下 |\n")
        f.write(f"| ①PMDA原データ（XMLファイル数） | {len(all_xml_files)} | 再帰探索 |\n")
        f.write(f"| ①’ユニーク添付文書数（内容ハッシュ基準） | {unique_docs} | 複数規格フォルダに複製される文書あり |\n")
        f.write(f"| ②抽出対象（rglob一致） | {len(extraction_targets)} | ①と同数のはず |\n")
        f.write(f"| ③構造化（現行ロジック、UPSERT前） | {len(current_records)} | |\n")
        f.write(f"| ③構造化（修正版ロジック、UPSERT前） | {len(correct_records)} | |\n")
        f.write(f"| ③’構造化（現行ロジック、UNIQUE適用後） | {len(current_upserted)} | 現行DB件数と比較対象 |\n")
        f.write(f"| ③’構造化（修正版ロジック、UNIQUE適用後） | {len(correct_upserted)} | あるべき姿 |\n")
        f.write(f"| ④販売名件数（現行） | {len(current_brand_names)} | |\n")
        f.write(f"| ④販売名件数（修正版） | {len(correct_brand_names)} | |\n")
        f.write(f"| ⑤規格ファミリー数（現行） | {len(current_families)} | |\n")
        f.write(f"| ⑤規格ファミリー数（修正版） | {len(correct_families)} | |\n")
        f.write(f"| ⑤’2規格以上を持つファミリー数（修正版） | {len(multi_strength_correct)} | |\n")
        f.write(f"| ⑦検索インデックス（drug_master実件数） | {len(db_records)} | 現在のサイトの実データ |\n")
        f.write(f"| ⑦検索インデックス（index.json実件数） | {index_count if index_count is not None else 'N/A'} | |\n")
        f.write("\n")
        f.write("## 欠落・孤立の集計\n\n")
        f.write(f"- Master(あるべき姿)→Index(現行DB)で欠落しているレコード: **{len(missing_keys)} 件**\n")
        f.write(f"- Index(現行DB)→Master(あるべき姿)で孤立しているレコード: **{len(orphan_keys)} 件**\n")
        f.write(f"- 「一部の規格だけ欠落」している薬剤ファミリー数: **{len(partial_families)} 件**\n")
        f.write(f"- 「ファミリー全体が欠落」している薬剤ファミリー数: **{len(fully_missing_families)} 件**（別原因の可能性、要個別確認）\n")
        f.write(f"- 重複候補（同一brand_name+generic_nameでyj_code違い）: **{len(dup_candidates)} 件**\n\n")
        f.write("## メインテート個別検証\n\n")
        f.write(f"検出された欠落レコード数: {len(maintate_check)} 件\n\n")
        for k in maintate_check:
            f.write(f"- {correct_upserted[k][1]} (YJ: {k[0]})\n")
        f.write("\n")
        f.write("## 出力ファイル\n\n")
        f.write(f"- `audit/missing-index-strengths.csv`（{len(missing_keys)}件）\n")
        f.write(f"- `audit/orphan-index-records.csv`（{len(orphan_keys)}件）\n")
        f.write(f"- `audit/duplicate-candidates.csv`（{len(dup_candidates)}件）\n\n")
        f.write("## 一部欠落ファミリーの代表例（先頭20件）\n\n")
        f.write("| 一般名 | ファミリー | 現行DBに存在する規格 | 欠落している規格 |\n|---|---|---|---|\n")
        for fam, v in list(partial_families.items())[:20]:
            f.write(f"| {v['generic']} | {fam[1]} | {', '.join(sorted(v['present']))} | {', '.join(sorted(v['missing']))} |\n")
        f.write("\n")
        f.write("## 修正方針の候補（未実装・次フェーズ）\n\n")
        f.write(
            "`parse_tenpu_file()` の販売名抽出ループを、`ApprovalEtc` 単位ではなく "
            "`ApprovalEtc` 配下の `DetailBrandName` 単位で反復するように変更する必要がある "
            "（`approval.findall(\"DetailBrandName\")` が空の場合は現行の `ApprovalEtc` 直下探索に "
            "フォールバックする形にすれば、旧構造のファイルへの後方互換も保てる）。"
            "このスクリプト内の `extract_brands_correct()` が実装例。\n"
        )
    p(f"\n[出力] {md_path}")

    p(f"\n{'='*70}")
    p("監査完了。修正は未実施。")
    p("=" * 70)

    # ログをテキストとしても保存
    with open(OUT_DIR / "audit-run-log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    main()
