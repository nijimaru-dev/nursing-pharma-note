# -*- coding: utf-8 -*-
"""
export_db_to_json.py
karteno_drugs.db（pmda_tenpu_parser.pyが作るSQLite）を、
静的サイト（薬理辞典WEB）が読み込むJSONファイル群に書き出す。

全薬剤分を1ファイルにまとめると、全薬剤展開時（約1万2000件）に
クライアント側の初期読み込みが重くなりすぎるため、以下のように分離する：

- index.json                        : 検索用の軽量インデックス（id・薬品名・一般名のみ）
- drugs/{id}.json                   : 薬品ごとの詳細情報（クリック時に遅延読み込み）
- interactions/{id}.json            : その薬品が関わる相互作用ペアの「索引」のみ
                                       （相手薬のid・注意種別だけ。本文は含まない）
- interactions/pairs/{min}_{max}.json : ペア単位の本文（注意種別・記載テキスト）。
                                       min/maxは薬品idを小さい順に並べたもの。

複数薬チェック画面は、選択した薬のIDの分だけ索引ファイルを取得し、選択中の
組み合わせに絞り込んでから、実際に表示が必要なペアのpairsファイルだけを
取得する（無関係なペアの本文はダウンロードしない）。

【変更履歴・その1】当初はinteractions.jsonを1ファイルにまとめていたが、実データ全件
（約1万件の薬剤・45万件の突合ペア）で書き出したところ195MBの単一ファイルになり、
GitHubの1ファイル100MB上限に抵触して運用不可能と判明したため、薬品ごとに分割する
方式に変更した。

【変更履歴・その2、2026-09-12】薬品ごとの分割（interactions/{id}.json）は、
1つのペアの本文（source_text等）を関係する両方の薬品のファイルに複製して
持たせていたため、全件展開時に287MB（本文が正味の2倍近く）になっていた。
ペアの本文はmin_id/max_idで決まる1ファイルにのみ持たせ（interactions/pairs/）、
薬品ごとのファイルは「どのペアを見に行けばよいか」を示す軽量な索引だけに
変更し、本文の二重持ちを解消した（HANDOFF.md 7章の懸案事項に対応）。

分割単位（頭文字別・薬効分類別等）は未実装。全薬剤展開時にindex.jsonのサイズが
問題になる場合は、ここを分割する対応が必要（Claude Code側での検証待ち）。

観察項目（KarteNo連携用、HANDOFF.md 5.1参照）：
v1は`serious_adverse_events`のテキストをそのまま「観察項目」候補として流用する
（自動・粗いが早く出せる方針）。精度が問題になった薬剤から、専用列を持たせる
方式（案2）へ個別移行する想定。

【2026-09修正・その1】以前は併用注意欄の`clinical_symptom_action`も観察項目に
混ぜていたが、これは薬品詳細ページの「飲み合わせ注意」セクション
（drug_pair_interaction由来）と内容が重複してしまうため廃止した。

【2026-09修正・その2】観察項目の情報源を`serious_adverse_events`（重大な副作用）
から`other_adverse_events`（11.2 その他の副作用＝重大に至らない一般的な副作用。
pmda_tenpu_parser.pyのparse_other_adverse_events参照）に変更した。
`serious_adverse_events`は薬品詳細ページ最上部の「重要」バナー専用とし、
「看護で見る」（観察項目）とは情報源を分離することで、同じ文言が2箇所に
重複表示されないようにしている。

使い方：
    python export_db_to_json.py --db ./karteno_drugs.db --out ./site/data
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path


def derive_observation_points(other_adverse_events):
    """
    v1の簡易実装：その他の副作用（重大に至らない一般的な副作用）テキストを
    行単位に分割し、観察項目の候補リストとして返す。
    重大な副作用（serious_adverse_events）は「重要」バナー専用のため含めない。
    飲み合わせ（併用注意）由来のテキストも「飲み合わせ注意」セクションと
    重複するため含めない。
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

    add_lines(other_adverse_events)

    return points


def build_pair_interactions(conn):
    """
    drug_pair_interaction（min_id/max_id形式）から、書き出し用の2種類の構造を作る。

    - index_by_drug : 薬品idごとの「索引」（相手薬のid・注意種別だけ。本文は含まない）。
                       interactions/{id}.json として書き出す。
    - pairs_content : (min_id, max_id) -> 本文（注意種別・記載テキスト）のリスト。
                       同じペアにcontraindicated/cautionが両方記載されているケースに
                       対応するためリストにしている。interactions/pairs/{min}_{max}.json
                       として、ペアにつき1ファイルだけ書き出す（本文の二重持ちをしない）。
    """
    pairs = conn.execute(
        "SELECT min_id, max_id, interaction_type, source_text FROM drug_pair_interaction"
    ).fetchall()

    index_by_drug = {}
    pairs_content = {}
    for p in pairs:
        min_id, max_id = p["min_id"], p["max_id"]
        index_by_drug.setdefault(min_id, []).append({
            "other_id": max_id,
            "interaction_type": p["interaction_type"],
        })
        index_by_drug.setdefault(max_id, []).append({
            "other_id": min_id,
            "interaction_type": p["interaction_type"],
        })
        pairs_content.setdefault((min_id, max_id), []).append({
            "interaction_type": p["interaction_type"],
            "source_text": p["source_text"],
        })
    return index_by_drug, pairs_content, len(pairs)


def export(db_path: Path, out_dir: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    drugs_dir = out_dir / "drugs"
    drugs_dir.mkdir(parents=True, exist_ok=True)
    interactions_dir = out_dir / "interactions"
    interactions_dir.mkdir(parents=True, exist_ok=True)
    pairs_dir = interactions_dir / "pairs"
    pairs_dir.mkdir(parents=True, exist_ok=True)

    drugs = conn.execute("SELECT * FROM drug_master").fetchall()
    index_by_drug, pairs_content, pair_count = build_pair_interactions(conn)

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
            "other_adverse_events": d["other_adverse_events"],
            "observation_points": derive_observation_points(d["other_adverse_events"]),
            "revision_date": d["revision_date"],
            "is_in_formulary": bool(d["is_in_formulary"]),
            "interactions": [dict(row) for row in interactions],
            # 施設ごとの注意点（第2層）は今後ここに追加する想定。
            # 現状のスキーマにはまだ列が無いため、常に空文字を出力する。
            "facility_notes": "",
        }
        with open(drugs_dir / f"{d['id']}.json", "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)

        drug_pair_index = index_by_drug.get(d["id"])
        if drug_pair_index:
            with open(interactions_dir / f"{d['id']}.json", "w", encoding="utf-8") as f:
                json.dump(drug_pair_index, f, ensure_ascii=False, indent=2)
        # 相互作用ペアが無い薬品はファイル自体を作らない
        # （クライアント側は404を「相互作用の記載なし」として扱う）

    for (min_id, max_id), content in pairs_content.items():
        with open(pairs_dir / f"{min_id}_{max_id}.json", "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)

    with open(out_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    conn.close()
    print(
        f"書き出し完了: 薬品 {len(index)} 件、相互作用ペア {pair_count} 件"
        f"（ペア本文ファイル {len(pairs_content)} 件） -> {out_dir}"
    )


def main():
    ap = argparse.ArgumentParser(description="SQLite -> 静的サイト用JSON書き出し")
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    export(args.db, args.out)


if __name__ == "__main__":
    main()
