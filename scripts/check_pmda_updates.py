# -*- coding: utf-8 -*-
"""
check_pmda_updates.py

【現状：意図的に未使用（実装しない方針に確定）】
このスクリプトは、PMDA「医療用医薬品 添付文書等情報検索」の更新年月日検索を使って
差分（直近改訂分）のみを自動検知・自動ダウンロードするための下書きとして書かれたが、
実装しないことに決定した。理由は「未実装」ではなく「不要」である。

- PMDAは公式ダウンロードAPIを提供しておらず、検索ページのフォームパラメータ・
  レスポンス構造に依存したスクレイピングが必要になる。PMDA側の画面変更で
  簡単に壊れるうえ、実機での挙動検証・継続的なメンテナンスコストに見合わないと判断した
  （HANDOFF.md 2章参照）。
- 代わりに `.github/workflows/update-drug-db.yml` は半自動化方式を採用している：
  1. 毎月1日、cronがPMDAには一切アクセスせず「今月の一括ダウンロードをお願いします」
     というGitHub Issueを作成するだけ
  2. 人がPMDAから新記載要領XMLを一括ダウンロードし、`scripts/tenpu_xml/`に配置する
  3. workflow_dispatchを手動実行し、`pmda_tenpu_parser.py`が全件を再パースする

このため「直近改訂分のみを検知する」差分取得の仕組み自体が不要になった。
このファイルはワークフローから呼び出されておらず、経緯を残すためだけに置いている。
削除して差し支えない状況になれば削除してよい。
"""

import sys


def main() -> int:
    print(
        "check_pmda_updates.py は使用されていません。"
        "PMDAの自動差分検知は実装しない方針です（本ファイルのdocstring、"
        "HANDOFF.md 2章、CLAUDE.md「データ更新パイプライン」参照）。",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
