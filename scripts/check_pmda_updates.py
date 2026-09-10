# -*- coding: utf-8 -*-
"""
check_pmda_updates.py
PMDA「医療用医薬品 添付文書等情報検索」の更新年月日検索を使い、
直近で改訂された添付文書のみを検知して差分ダウンロードするためのスクリプト。

【現状：未実装のプレースホルダー】
PMDAは公式ダウンロードAPIを提供しておらず、検索ページのフォームパラメータ・
レスポンス構造に依存したスクレイピングが必要になる。実際のリクエスト形式は
実機で検証していないため、ここでは実装していない（HANDOFF.md 2章・7章参照）。

実装する際に確認すべきこと：
- 検索ページのURL・フォームの実際のパラメータ名（更新年月日での絞り込み条件）
- 検索結果一覧のHTML構造（ページネーション含む）
- 個別のXML（新記載要領）ダウンロードリンクの取得方法
- 短期間に大量リクエストを送らないためのレート制御・User-Agent設定

未実装の間は、このスクリプトは常に「更新なし」として正常終了する
（exit code 0）。これにより、GitHub Actions のワークフロー自体は
本実装が入るまで安全にスキップ・成功扱いになる。
実装後は、新規・改訂ファイルを --input-dir に保存し、
GITHUB_OUTPUT に has_updates=true/false を書き出すこと。

使い方（実装後の想定）：
    python check_pmda_updates.py --input-dir ./tenpu_xml
"""

import argparse
import os
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="PMDA添付文書の更新チェック（未実装プレースホルダー）")
    ap.add_argument("--input-dir", type=Path, default=Path("./tenpu_xml"))
    args = ap.parse_args()

    print(
        "[未実装] PMDA更新チェックはまだ実装されていません。"
        "HANDOFF.md 2章・7章および本ファイルのdocstringを参照し、"
        "実機でPMDA検索ページの挙動を確認してから実装してください。",
        file=sys.stderr,
    )

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write("has_updates=false\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
