# 看護薬理ノート（nursing-pharma-note）

看護師・介護職員・看護学生のための、無料の薬剤情報リファレンス。薬品名で検索して
効能・用法・注意点を確認し、複数の薬を選んで飲み合わせ（相互作用）もチェックできます。

診断・治療・処方の代替ではありません。詳細は [`DISCLAIMER.md`](./DISCLAIMER.md) を参照してください。

## 構成

```
scripts/                     データパイプライン（Python）
  pmda_tenpu_parser.py        PMDA添付文書XML -> SQLite（唯一の原本）
  drug_alias.py                薬効分類名⇄一般名の対応表・相互作用の自動突合ロジック
  export_db_to_json.py         SQLite -> site/data/ のJSON書き出し
  check_pmda_updates.py        PMDA更新検知（★未実装のプレースホルダー）
  seed_sample_data.py          開発用サンプルDBの投入（本番データの原本にはしない）

site/                         静的サイト本体（Netlifyの公開ディレクトリ）
  index.html / drug.html / check.html / about.html / 404.html
  css/style.css                デザインシステム
  js/                           データ取得・検索UI
  data/                         SQLiteからの生成物（手で直接編集しない）

.github/workflows/update-drug-db.yml   月次の自動更新・デプロイワークフロー
netlify.toml                            Netlifyビルド設定（publish = site）
```

## データの唯一の原本

`karteno_drugs.db`（`scripts/pmda_tenpu_parser.py` が生成するSQLite）が全データの原本です。
`site/data/` 配下のJSONは `scripts/export_db_to_json.py` による生成物なので、
データを直したいときはDBまたはスクリプトを直して再生成してください。

## ローカルでの開発

実際のPMDA添付文書XML・院内処方リストがまだ無い開発段階では、サンプルデータで
フロントエンドを確認できます。

```bash
cd scripts
python seed_sample_data.py --db ./karteno_drugs.sample.db
python export_db_to_json.py --db ./karteno_drugs.sample.db --out ../site/data
```

サイトは `site/` を任意の静的サーバーで配信すれば確認できます（例）。

```bash
cd site
python -m http.server 8000
```

実データを取り込む場合は、PMDA「医療用医薬品 添付文書等情報検索」からダウンロードした
添付文書XML（新記載要領）を1ディレクトリにまとめ、以下を実行します。

```bash
cd scripts
python pmda_tenpu_parser.py --input-dir ./tenpu_xml --db ../karteno_drugs.db --formulary ./formulary.txt
python export_db_to_json.py --db ../karteno_drugs.db --out ../site/data
```

## 現状のスコープと未解決事項

詳細は [`HANDOFF.md`](./HANDOFF.md) を参照してください。特に以下は未解決です。

- **PMDA更新チェック（`scripts/check_pmda_updates.py`）は未実装のプレースホルダー**です。
  PMDAは公式ダウンロードAPIを提供していないため、検索ページの実際のリクエスト形式を
  実機で確認してから実装する必要があります。未実装の間、月次ワークフローは
  「更新なし」として安全に成功終了します。
- ドメイン未決定、Netlifyサイト未作成（デプロイには `NETLIFY_AUTH_TOKEN` /
  `NETLIFY_SITE_ID` をリポジトリSecretsに設定する必要があります）。
- 全薬剤展開時（PMDA添付文書は約1万2000件規模）の `index.json` サイズ・分割方針は未検証です。
- 「平易表示」は、専用の言い換えテキストをデータとして持っていないため、v1では
  既存フィールドを要約・構造化して表示する形で近似しています（別テキストへの
  言い換えではありません）。精度が問題になれば、平易文専用フィールドの追加を検討してください。
- 観察項目（KarteNo連携用）は、`serious_adverse_events` と併用注意欄のテキストを
  そのまま流用するv1実装です（HANDOFF.md 5.1参照）。

## GitHub通知設定（要手動対応）

月次ジョブが失敗した際に気づけるよう、GitHubアカウントの
Settings > Notifications で Actions の失敗通知を有効にしておいてください
（この設定はAPI経由では行えないため、手動での確認をお願いします）。
