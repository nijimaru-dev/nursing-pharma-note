# -*- coding: utf-8 -*-
"""
export_db_to_json.py
karteno_drugs.db（pmda_tenpu_parser.pyが作るSQLite）を、
静的サイト（薬理辞典WEB）が読み込むJSONファイル群に書き出す。

全薬剤分を1ファイルにまとめると、全薬剤展開時（約1万2000件）に
クライアント側の初期読み込みが重くなりすぎるため、以下のように分離する：

- index.json              : 検索用の軽量インデックス（id・薬品名・一般名のみ）
- drugs/{id}.json         : 薬品ごとの詳細情報（クリック時に遅延読み込み）
- interactions/{id}.json  : その薬品が関わる相互作用ペアのみ（相手薬のid・ブランド名・
                             注意種別・記載テキスト）。複数薬チェック画面は選択した
                             薬のIDの分だけ都度フェッチする。

【変更履歴】当初はinteractions.jsonを1ファイルにまとめていたが、実データ全件
（約1万件の薬剤・45万件の突合ペア）で書き出したところ195MBの単一ファイルになり、
GitHubの1ファイル100MB上限に抵触して運用不可能と判明したため、薬品ごとに分割する
方式に変更した。

分割単位（頭文字別・薬効分類別等）は未実装。全薬剤展開時にindex.jsonのサイズが
問題になる場合は、ここを分割する対応が必要（Claude Code側での検証待ち）。

観察項目（KarteNo連携用、HANDOFF.md 5.1参照）：
v1は`serious_adverse_events`と、併用注意欄の`clinical_symptom_action`の
テキストをそのまま「観察項目」候補として流用する（自動・粗いが早く出せる方針）。
精度が問題になった薬剤から、専用列を持たせる方式（案2）へ個別移行する想定。

使い方：
    python export_db_to_json.py --db ./karteno_drugs.db --out ./site/data
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path


def derive_observation_points(serious_adverse_events, caution_interactions):
    """
    v1の簡易実装：重大な副作用テキストと併用注意の臨床症状・措置方法テキストを
    行・句点単位に分割し、観察項目の候補リストとして返す。
    看護知識による個別の精査は行っていないため、あくまで叩き台。
    """
    points = []
    seen = set()

    def add_lines(text):
        if not text:
            return
        for line in re.split(r"[\n。]", text):
            line = line.strip()
            if line and line not in seen:
                seen.add(line)
                points.append(line)

    add_lines(serious_adverse_events)
    for text in caution_interactions:
        add_lines(text)

    return points


def build_interactions_by_drug(conn):
    """
    drug_pair_interactionを、薬品idごとの「相手薬との相互作用リスト」に変換する。
    ペアは両方向（A視点・B視点）で該当薬のリストに含める。
    """
    pairs = conn.execute(
        """SELECT dp.drug_a_id, dp.drug_b_id, dp.interaction_type, dp.source_text,
                  a.brand_name AS a_brand, b.brand_name AS b_brand
           FROM drug_pair_interaction dp
           JOIN drug_master a ON a.id = dp.drug_a_id
           JOIN drug_master b ON b.id = dp.drug_b_id"""
    ).fetchall()

    by_drug = {}
    for p in pairs:
        by_drug.setdefault(p["drug_a_id"], []).append({
            "other_id": p["drug_b_id"],
            "other_brand": p["b_brand"],
            "interaction_type": p["interaction_type"],
            "source_text": p["source_text"],
        })
        by_drug.setdefault(p["drug_b_id"], []).append({
            "other_id": p["drug_a_id"],
            "other_brand": p["a_brand"],
            "interaction_type": p["interaction_type"],
            "source_text": p["source_text"],
        })
    return by_drug, len(pairs)


def export(db_path: Path, out_dir: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    drugs_dir = out_dir / "drugs"
    drugs_dir.mkdir(parents=True, exist_ok=True)
    interactions_dir = out_dir / "interactions"
    interactions_dir.mkdir(parents=True, exist_ok=True)

    drugs = conn.execute("SELECT * FROM drug_master").fetchall()
    interactions_by_drug, pair_count = build_interactions_by_drug(conn)

    index = []
    for d in drugs:
        index.append({
            "id": d["id"],
            "brand_name": d["brand_name"],
            "generic_name": d["generic_name"],
            "therapeutic_classification": d["therapeutic_classification"],
            "is_in_formulary": bool(d["is_in_formulary"]),
        })

        interactions = conn.execute(
            "SELECT interaction_type, drug_name_or_class, clinical_symptom_action, "
            "mechanism_risk_factor FROM drug_interaction WHERE drug_master_id = ?",
            (d["id"],),
        ).fetchall()

        caution_texts = [
            row["clinical_symptom_action"]
            for row in interactions
            if row["interaction_type"] == "caution"
        ]

        detail = {
            "id": d["id"],
            "brand_name": d["brand_name"],
            "generic_name": d["generic_name"],
            "therapeutic_classification": d["therapeutic_classification"],
            "indications": d["indications"],
            "dose_admin": d["dose_admin"],
            "contraindications": d["contraindications"],
            "application_precautions": d["application_precautions"],
            "serious_adverse_events": d["serious_adverse_events"],
            "observation_points": derive_observation_points(d["serious_adverse_events"], caution_texts),
            "is_in_formulary": bool(d["is_in_formulary"]),
            "interactions": [dict(row) for row in interactions],
            # 施設ごとの注意点（第2層）は今後ここに追加する想定。
            # 現状のスキーマにはまだ列が無いため、常に空文字を出力する。
            "facility_notes": "",
        }
        with open(drugs_dir / f"{d['id']}.json", "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)

        drug_pairs = interactions_by_drug.get(d["id"])
        if drug_pairs:
            with open(interactions_dir / f"{d['id']}.json", "w", encoding="utf-8") as f:
                json.dump(drug_pairs, f, ensure_ascii=False, indent=2)
        # 相互作用ペアが無い薬品はファイル自体を作らない
        # （クライアント側は404を「相互作用の記載なし」として扱う）

    with open(out_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    conn.close()
    print(f"書き出し完了: 薬品 {len(index)} 件、相互作用ペア {pair_count} 件 -> {out_dir}")


def main():
    ap = argparse.ArgumentParser(description="SQLite -> 静的サイト用JSON書き出し")
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    export(args.db, args.out)


if __name__ == "__main__":
    main()
