# -*- coding: utf-8 -*-
"""
rematch_pairs.py
既存のkarteno_drugs.db（drug_master・drug_interactionは正しい状態）に対して、
auto_match_pair_interactions() だけを再実行するためのユーティリティ。

pmda_tenpu_parser.pyのauto_match_pair_interactions()に2026-09-11に入れた修正
（drug_pair_interaction.source_textをdrug_name_or_classではなく
clinical_symptom_actionにする修正）を、17,728件のXML再パース（約40分）なしで
DBへ反映するために使う。

使い方：
    python rematch_pairs.py --db ../karteno_drugs.db
"""

import argparse
import sqlite3
from pathlib import Path

from pmda_tenpu_parser import auto_match_pair_interactions


def main():
    ap = argparse.ArgumentParser(description="drug_pair_interactionの再突合のみ実行")
    ap.add_argument("--db", required=True, type=Path)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    matched = auto_match_pair_interactions(conn)
    conn.commit()
    conn.close()
    print(f"再突合完了: {matched} 件 -> {args.db}")


if __name__ == "__main__":
    main()
