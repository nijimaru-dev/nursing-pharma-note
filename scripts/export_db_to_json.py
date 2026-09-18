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
- interactions/pairs/{id}.json      : その薬品が関わる全ペアの本文（相手薬id・
                                       注意種別・記載テキスト）をまとめた1ファイル。

複数薬チェック画面は、選択した薬のIDの分だけ索引ファイルを取得し、選択中の
組み合わせに絞り込んでから、実際に表示が必要な相手側の薬品idのpairsファイル
だけを取得する（無関係な薬品の本文はダウンロードしない）。

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

【変更履歴・その3、2026-09-13】pmda_tenpu_parser.pyのDetailBrandName欠落バグ
修正により、drug_pair_interactionの件数が45万→150万件に急増した。「1ペア=1
ファイル」（interactions/pairs/{min}_{max}.json）のままだと、pairsディレクトリ
だけで約150万個の個別ファイルになり、git（1コミットでの追跡・push）にも
NTFS等のファイルシステムにも非現実的な規模になったため運用不能と判断した。
「1薬品=その薬品が関わる全ペアをまとめた1ファイル」（interactions/pairs/{id}.json）
に変更し、ファイル数を薬品数（相互作用を持つ薬品の数）程度に戻した。1つの
ペアの本文は関係する両方の薬品のファイルに重複して持つことになる
（2026-09-12時点で一度解消した「本文の二重持ち」が復活するが、内容量の重複より
ファイル数の実用性を優先した）。薬品ごとの軽量索引（interactions/{id}.json）は
変更していない。

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
import time
from pathlib import Path


_PERCENT_SUFFIX_RE = re.compile(r"[（(]\s*[\d.]+\s*%\s*[）)]$")


def _symptom_dedup_key(token):
    """重複判定用のキー。「めまい」と「めまい（16.0%）」を同一とみなすため、
    末尾の（NN.N%）表記だけを取り除く（それ以外の表記ゆれは意味解析しない）。"""
    return _PERCENT_SUFFIX_RE.sub("", token).strip()


def derive_observation_points(other_adverse_events):
    """
    その他の副作用（重大に至らない一般的な副作用）テキストから、
    「器官別分類（循環器・精神神経系等）ごとに1行」の観察項目リストを作る。

    【不具合修正・2026-09-13】pmda_tenpu_parser.pyのparse_other_adverse_events()
    は、適応症・試験ごとに分かれた複数の<OtherAdverse>表を単純に連結するため、
    実データでは同一カテゴリ（例：循環器）が複数の完全に別々の行として
    重複出現していた（drug.htmlで「循環器：xxx」ブロックが2〜3回表示される
    不具合）。ここでカテゴリをキーに全記載をマージし、「、」区切りの語句単位で
    重複を除去してから1カテゴリ1行に整形する。

    重複判定は語句の完全一致（％表記の有無だけを無視）でのみ行う。
    「AST、ALT、ビリルビンの上昇」のように末尾の動詞句が複数語へ分配で
    係る構文までは意味解析しないため、このケースに限り重複が完全には
    解消しないことがある（既知の制約。誤って「ビリルビン」のような
    語だけを機械的に「ビリルビンの上昇」と決めつけて医学的に不正確な
    文言を自動生成するリスクを避けるため、あえて分配の推測はしない）。

    重大な副作用（serious_adverse_events）は「重要」バナー専用のため含めない。
    飲み合わせ（併用注意）由来のテキストも「飲み合わせ注意」セクションと
    重複するため含めない。
    看護知識による個別の精査は行っていないため、あくまで叩き台。
    """
    if not other_adverse_events:
        return []

    category_order = []
    # category -> {dedup_key: 表示用の実際の語句（％表記があればそちらを優先）}
    category_tokens = {}

    for line in other_adverse_events.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "：" in line:
            category, rest = line.split("：", 1)
        else:
            category, rest = "", line

        if category not in category_tokens:
            category_tokens[category] = {}
            category_order.append(category)
        bucket = category_tokens[category]

        for token in rest.split("、"):
            token = token.strip()
            if not token:
                continue
            key = _symptom_dedup_key(token)
            existing = bucket.get(key)
            has_percent = bool(_PERCENT_SUFFIX_RE.search(token))
            if existing is None or (has_percent and not _PERCENT_SUFFIX_RE.search(existing)):
                bucket[key] = token

    points = []
    for category in category_order:
        tokens = list(category_tokens[category].values())
        if not tokens:
            continue
        merged = "、".join(tokens)
        points.append(f"{category}：{merged}" if category else merged)

    return points


def build_pair_data(conn):
    """
    drug_pair_interaction（min_id/max_id形式）を1回走査し、薬品idごとの
    (1) 軽量索引（相手薬id・注意種別のみ。interactions/{id}.json用）と
    (2) 全ペア本文（相手薬id・注意種別・記載テキスト。interactions/pairs/{id}.json用）
    の両方を組み立てる。

    【2026-09-13】DetailBrandName欠落バグ修正で全体のペア数が約3.4倍
    （45万→150万件）に増えたが、薬品数自体は約1.6倍（1.05万→1.66万件）
    にしか増えていない。ペア本文を薬品単位（最大でも薬品数程度のファイル数）に
    まとめれば、ファイル数の増加を実用的な範囲に抑えられる
    （詳細はモジュールdocstringの変更履歴・その3を参照）。
    """
    index_by_drug = {}
    content_by_drug = {}
    pair_count = 0
    cur = conn.execute(
        "SELECT min_id, max_id, interaction_type, source_text FROM drug_pair_interaction"
    )
    for min_id, max_id, interaction_type, source_text in cur:
        index_by_drug.setdefault(min_id, []).append({
            "other_id": max_id,
            "interaction_type": interaction_type,
        })
        index_by_drug.setdefault(max_id, []).append({
            "other_id": min_id,
            "interaction_type": interaction_type,
        })
        content_by_drug.setdefault(min_id, []).append({
            "other_id": max_id,
            "interaction_type": interaction_type,
            "source_text": source_text,
        })
        content_by_drug.setdefault(max_id, []).append({
            "other_id": min_id,
            "interaction_type": interaction_type,
            "source_text": source_text,
        })
        pair_count += 1
    return index_by_drug, content_by_drug, pair_count


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
    index_by_drug, content_by_drug, pair_count = build_pair_data(conn)

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
            # 規格×適応症の参考表（一部薬剤のみ。pmda_tenpu_parser.pyの
            # parse_indications参照）。無い薬剤はNULLなのでNoneのまま出力する。
            "indications_table": json.loads(d["indications_table"]) if d["indications_table"] else None,
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

        drug_pair_content = content_by_drug.get(d["id"])
        if drug_pair_content:
            with open(pairs_dir / f"{d['id']}.json", "w", encoding="utf-8") as f:
                json.dump(drug_pair_content, f, ensure_ascii=False, indent=2)

    pairs_file_count = sum(1 for _ in content_by_drug)

    with open(out_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    # 【キャッシュバスティング用】このファイルの値が変わるたびに、data.jsが
    # JSON取得URLへ付与するクエリパラメータ（?v=...）も変わり、ブラウザ・CDNに
    # 残った古いキャッシュを自動的に無視して再取得させる。このスクリプトを
    # 再実行するたびに自動更新されるだけで、手動でのバージョン管理は不要。
    with open(out_dir / "version.json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": str(int(time.time()))}, f)

    conn.close()
    print(
        f"書き出し完了: 薬品 {len(index)} 件、相互作用ペア {pair_count} 件"
        f"（ペア本文ファイル {pairs_file_count} 件） -> {out_dir}"
    )


def main():
    ap = argparse.ArgumentParser(description="SQLite -> 静的サイト用JSON書き出し")
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    export(args.db, args.out)


if __name__ == "__main__":
    main()
