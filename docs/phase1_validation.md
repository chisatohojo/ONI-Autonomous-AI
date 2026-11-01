# Phase 1 検証記録

履歴更新：Phase 1のコミットd003276はユーザー承認後、既存origin/mainへ通常のfast-forward push済みです。以下はPhase 1作業時の検証記録です。

実施日：2026-11-01（Asia/Tokyo）。作業前HEAD：e1268df75d5e574f51d90c1afbe4dc54bb872d8b。既存originはhttps://github.com/chisatohojo/ONI-Autonomous-AI.git。既存の作業ディレクトリをそのまま使用し、clone/initは実施していません。

## ベースラインと最終チェック

| チェック | 結果 |
| --- | --- |
| 作業前のPhase 0テスト | **31 passed** |
| 作業前ruff check / format --check | PASS |
| Phase 1の全pytest | **96 passed**（既存31件 + 追加65件） |
| 最終ruff check . | PASS |
| 最終ruff format --check . | PASS（21 Python files） |
| uv lock / sync --frozen --extra dev | PASS。依存追加なし、プロジェクト版のみ0.1.0へ更新 |
| wheelビルド・別venvへの--no-deps導入 | PASS |
| wheelのisolated Pythonからinit/import/audit/simulate/replay | PASS |
| 実際のPhase 0 DBからコピー移行 | PASS。元ファイルSHA256不変 |
| 全8fixtureの1 tick記録とreplay | PASS |

環境はPython 3.12.12、pytest 8.4.2、ruff 0.14.3、uv 0.9.7、setuptools 80.9.0です。実行時の外部依存は0です。

## 互換性・整合性

Schema 1の読み取り、独自行・UNKNOWN注記を保持するSchema 2へのコピー、既存出力拒否、読取専用、版/DLCの完全一致、catalog再取込みのno-op、途中衝突の全rollbackを検証しました。新規DBの元seed3件は維持しています。

実際のdata/local/knowledge.sqlite3はSchema 1のまま保持し、data/local/phase1.sqlite3にコピー移行・catalog取込みを実施しました。元DBのSHA256は前後ともcf6de2574f95cf73b5a2c17018280a49109d41378bfd77d5794fcc3c8e404fa0でした。

取込み結果：設備ID4、バリアント5、ルール5、rule_binding2、設備属性50（名称5件がSOURCE_REVIEWED、45件UNKNOWN）。audit-dbはvalid=true、errors=[]、UNKNOWN45件をwarningとして報告しました。

新規追加はBatteryの設備ID1件、PlanterBox/Batteryのビルド限定バリアント2件、酸素・食料・電力・水・研究の公式記録に基づくルール各1件です。設備の入出力レート・電力・資材・研究前提・DLC条件を新たに確定した数は0です。全追加データの適用版と再配布判断は[出典レビュー](phase1_sources.md)で確認できます。

## 合成実験

normal、oxygen_shortage、food_shortage、power_shortage、work_stalled、water_shortage、research_locked、unknown_oxygenの8fixtureを確認しました。各fixtureの1 tick診断はローカルJSONLに保存しreplayできています。

テストでは明示的な行動による状態変化、停滞・研究条件・入力不足・未知状態の区別、context/tick/重複ID拒否、dry-run無変更、競合する入力の保守的処理、数値オーバーフロー時のrollback、拒否行動の記録、複数警告の順序に依存しない再現性を確認しました。

ログの不完全状態・結果の食い違い・fixture digestの不一致・不正JSON、数値のbool/NaN/Infinity/overflow、資材/研究/温度配列の不整合も拒否します。MCPの旧版/新版拒否と固定2025-11-25経路、resourceのURI/MIME/errorの判定はオフラインの合成メッセージだけで検証しています。

## 境界と未確認事項

pytestでは既存のsocket遮断を継続しています。研究用の公開資料取得と開発依存の取得を除き、環境・評価コードは通信しません。ONI本体・MOD・セーブ・Steam設定の読み書き、実ゲーム接続、自動操作、.NET/Rust導入、モデルAPI利用、公開サーバー起動は行っていません。

合成データは実ゲーム由来ではなく、モデル値から設備仕様を補完していません。知識は過去の公式ビルドに限定したSOURCE_REVIEWEDです。現在版への適用、過去ビルドのID実機照合、GAME_VERIFIED化、実行時manifest、OniMcpの文書差異解決、実機互換性、許諾は未確認です。

対象ファイルと秘密情報候補を点検し、DB・ログ・環境・調査した外部本文・wheelをGit対象外にしました。ローカルコミットd003276で作業ツリーをcleanとし、ユーザーの個別承認後にpushを完了しました。
