# -*- coding: utf-8 -*-
"""
seed_sample_data.py
開発用のサンプルデータ投入スクリプト。

実際のPMDA添付文書XML・院内処方リストがまだ用意できていない開発初期段階で、
フロントエンド（site/）を実データに近い形で作り込めるように、
pmda_tenpu_parser.py と同じスキーマ・同じ自動突合ロジック
（auto_match_pair_interactions）を使ってサンプルDBを組み立てる。

ここに書く薬剤情報・相互作用情報は、一般に公知の薬理学的知識に基づく
デモ用の簡略化した記載であり、実際の添付文書の記載そのものではない。
公開前には必ず pmda_tenpu_parser.py で実際のPMDA添付文書XMLから
再構築すること（本番データの原本にはしない）。

使い方：
    python seed_sample_data.py --db ./karteno_drugs.sample.db
    python export_db_to_json.py --db ./karteno_drugs.sample.db --out ../site/data
"""

import argparse
import sqlite3
from pathlib import Path

from pmda_tenpu_parser import SCHEMA, auto_match_pair_interactions

SAMPLE_DRUGS = [
    {
        "brand_name": "ジゴシン",
        "yj_code": "2113001F1044",
        "generic_name": "ジゴキシン",
        "therapeutic_classification": "強心配糖体製剤",
        "indications": "うっ血性心不全、心房細動・粗動による頻脈の調節",
        "dose_admin": "通常成人にはジゴキシンとして維持量0.25mgを1日1回経口投与する。",
        "contraindications": "ジギタリス中毒の患者、房室ブロックのある患者",
        "application_precautions": "腎機能低下患者では血中濃度が上昇しやすいため減量を検討する。",
        "serious_adverse_events": "ジギタリス中毒（悪心・嘔吐、食欲不振、視覚異常、不整脈）\n房室ブロック、洞停止",
        "is_in_formulary": 1,
        "interactions": [
            ("caution", "ループ利尿薬", "低カリウム血症によりジギタリス中毒が発現しやすくなる。血清カリウム値を確認すること。", "利尿薬による低カリウム血症が心筋のジギタリス感受性を高める。"),
            ("caution", "マクロライド系抗菌薬", "本剤の血中濃度が上昇し、ジギタリス中毒があらわれることがある。", "腸内細菌によるジゴキシン代謝の阻害。"),
        ],
    },
    {
        "brand_name": "ラシックス",
        "yj_code": "2139001A1032",
        "generic_name": "フロセミド",
        "therapeutic_classification": "ループ利尿薬",
        "indications": "浮腫（心性、腎性、肝性）、高血圧症",
        "dose_admin": "通常成人1日1回40mgを経口投与する。症状により適宜増減する。",
        "contraindications": "無尿の患者、肝性昏睡の患者",
        "application_precautions": "脱水・電解質異常（低カリウム血症等）に注意する。",
        "serious_adverse_events": "低カリウム血症、低ナトリウム血症\n脱水症状\n難聴",
        "is_in_formulary": 1,
        "interactions": [
            ("caution", "ジギタリス製剤", "低カリウム血症によりジギタリス中毒を起こしやすくなる。", "利尿による血清カリウム低下。"),
        ],
    },
    {
        "brand_name": "ワーファリン",
        "yj_code": "3332001F1039",
        "generic_name": "ワルファリンカリウム",
        "therapeutic_classification": "経口抗凝固薬",
        "indications": "血栓塞栓症の治療及び予防",
        "dose_admin": "PT-INR等の血液凝固能検査値を参考に個々の患者ごとに用量を決定する。",
        "contraindications": "出血している患者、重篤な肝障害のある患者、妊婦",
        "application_precautions": "納豆・クロレラ食品・青汁の摂取により作用が減弱することがある。",
        "serious_adverse_events": "出血（脳出血、消化管出血等）\n肝機能障害",
        "is_in_formulary": 1,
        "interactions": [
            ("caution", "非ステロイド性消炎鎮痛剤", "出血傾向が増強されることがある。出血徴候（皮下出血、下血等）の有無を観察すること。", "血小板機能抑制及び蛋白結合部位競合による遊離型ワルファリンの増加。"),
            ("caution", "抗血小板剤", "出血の危険性が増大するおそれがある。", "止血機構への相加的な作用。"),
        ],
    },
    {
        "brand_name": "バイアスピリン",
        "yj_code": "3399001F1039",
        "generic_name": "アスピリン",
        "therapeutic_classification": "抗血小板剤",
        "indications": "狭心症、心筋梗塞、虚血性脳血管障害における血栓・塞栓形成の抑制",
        "dose_admin": "通常成人1日1回100mgを経口投与する。",
        "contraindications": "アスピリン喘息の既往のある患者、出血傾向のある患者",
        "application_precautions": "消化性潰瘍の既往がある患者では悪化に注意する。",
        "serious_adverse_events": "出血（消化管出血、脳出血等）\nショック、アナフィラキシー",
        "is_in_formulary": 1,
        "interactions": [
            ("caution", "経口抗凝固薬", "出血の危険性が増大するおそれがある。出血徴候の有無を観察すること。", "血小板凝集抑制作用の相加。"),
        ],
    },
    {
        "brand_name": "ロキソニン",
        "yj_code": "1149002F1029",
        "generic_name": "ロキソプロフェンナトリウム水和物",
        "therapeutic_classification": "非ステロイド性消炎鎮痛剤",
        "indications": "関節リウマチ、腰痛症、術後・外傷後の消炎・鎮痛、発熱・疼痛時の解熱・鎮痛",
        "dose_admin": "通常成人1回60mgを1日3回経口投与する。",
        "contraindications": "消化性潰瘍のある患者、重篤な血液異常のある患者",
        "application_precautions": "高齢者では消化管出血等の副作用が発現しやすいため注意する。",
        "serious_adverse_events": "消化性潰瘍、消化管出血\n腎障害\nショック、アナフィラキシー",
        "is_in_formulary": 1,
        "interactions": [
            ("caution", "経口抗凝固薬", "出血傾向が増強されることがある。", "血小板機能抑制及び蛋白結合部位競合。"),
        ],
    },
    {
        "brand_name": "クラリス",
        "yj_code": "6149001F1026",
        "generic_name": "クラリスロマイシン",
        "therapeutic_classification": "マクロライド系抗生物質製剤",
        "indications": "肺炎、咽頭・喉頭炎、中耳炎等の細菌感染症",
        "dose_admin": "通常成人1回200mgを1日2回経口投与する。",
        "contraindications": "本剤の成分に対し過敏症の既往歴のある患者",
        "application_precautions": "QT延長のリスクがある患者では心電図変化に注意する。",
        "serious_adverse_events": "QT延長、心室頻拍\n肝機能障害、黄疸\n偽膜性大腸炎",
        "is_in_formulary": 1,
        "interactions": [
            ("caution", "強心配糖体", "ジギタリス中毒があらわれることがあるので、血中濃度モニタリングを行うなど注意すること。", "腸内細菌叢の変化によるジゴキシン代謝阻害。"),
        ],
    },
    {
        "brand_name": "オメプラール",
        "yj_code": "2329015F1024",
        "generic_name": "オメプラゾール",
        "therapeutic_classification": "プロトンポンプインヒビター",
        "indications": "胃潰瘍、十二指腸潰瘍、逆流性食道炎",
        "dose_admin": "通常成人1日1回20mgを経口投与する。",
        "contraindications": "本剤の成分に対し過敏症の既往歴のある患者",
        "application_precautions": "長期投与時は胃酸分泌抑制に伴う影響（骨折リスク等）に留意する。",
        "serious_adverse_events": "汎血球減少、無顆粒球症\n中毒性表皮壊死融解症",
        "is_in_formulary": 1,
        "interactions": [],
    },
    {
        "brand_name": "プルゼニド",
        "yj_code": "2354002F1027",
        "generic_name": "センノシド",
        "therapeutic_classification": "下剤・便秘用薬",
        "indications": "便秘症",
        "dose_admin": "通常成人1日1回12～24mgを就寝前に経口投与する。",
        "contraindications": "急性腹症が疑われる患者、痙攣性便秘の患者",
        "application_precautions": "連用により耐性を生じることがある。漫然と長期投与しない。",
        "serious_adverse_events": "記載なし",
        "is_in_formulary": 0,
        "interactions": [],
    },
]


def seed(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    cur = conn.cursor()

    cur.execute("DELETE FROM drug_interaction")
    cur.execute("DELETE FROM drug_pair_interaction")
    cur.execute("DELETE FROM drug_master")

    for drug in SAMPLE_DRUGS:
        cur.execute(
            """INSERT INTO drug_master
               (brand_name, yj_code, generic_name, therapeutic_classification, indications,
                dose_admin, contraindications, application_precautions, serious_adverse_events,
                source_file, is_in_formulary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                drug["brand_name"], drug["yj_code"], drug["generic_name"],
                drug["therapeutic_classification"], drug["indications"], drug["dose_admin"],
                drug["contraindications"], drug["application_precautions"],
                drug["serious_adverse_events"], "sample_data", drug["is_in_formulary"],
            ),
        )
        drug_master_id = cur.lastrowid
        for itype, name_or_class, clinical, mechanism in drug["interactions"]:
            cur.execute(
                """INSERT INTO drug_interaction
                   (drug_master_id, interaction_type, drug_name_or_class,
                    clinical_symptom_action, mechanism_risk_factor)
                   VALUES (?, ?, ?, ?, ?)""",
                (drug_master_id, itype, name_or_class, clinical, mechanism),
            )

    matched = auto_match_pair_interactions(conn)
    conn.commit()
    conn.close()
    print(f"サンプルデータ投入完了: 薬品 {len(SAMPLE_DRUGS)} 件 -> {db_path}")
    print(f"自動突合した相互作用ペア: {matched} 件")


def main():
    ap = argparse.ArgumentParser(description="開発用サンプルDBの投入")
    ap.add_argument("--db", required=True, type=Path)
    args = ap.parse_args()
    seed(args.db)


if __name__ == "__main__":
    main()
