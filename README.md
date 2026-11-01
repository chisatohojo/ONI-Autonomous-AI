# ONI_Autonomous_AI

Oxygen Not Included（ONI）の自律プレイAIを研究する独立プロジェクトです。ゲームルール・設備仕様・操作仕様を事前知識とし、将来の判断・計画・改善はAIが担う設計です。Klei・Valveの公式プロジェクトではありません。

**Phase 1（0.1.0）：根拠付き知識DBと、合成データだけを使う模擬行動・評価環境。実ゲームへの接続・操作機能はありません。**

## セットアップ（Windows / PowerShell）

Python 3.12.12、pytest 8.4.2、ruff 0.14.3を使用します。実行時の外部依存はありません。直接依存を `pyproject.toml`、推移依存と配布物ハッシュを `uv.lock` で固定しています。ビルド用setuptoolsは80.9.0です。

この環境では `py -3.12` の登録先実体が欠けていたため、既存Python 3.10からプロジェクト内にPythonを用意しました。再構築も同じコマンドで行えます。

```powershell
python scripts/bootstrap.py
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

`bootstrap.py` はWindows x64向けです。固定したuv 0.9.7のPyPI wheelをSHA256照合後に展開し、uvが配布元・チェックサムを管理するCPython 3.12.12を `.tools/python/` に配置して `uv sync --frozen --extra dev` を実行します。PATH・Pythonランチャー・Steam設定を変更しません。初回のみインターネットが必要です。ダウンロードしたOniModsのコードは実行しません。

既にPython 3.12.12とuv 0.9.7がある別環境では `uv sync --frozen --extra dev` でも構築できます。別OSは未検証です。依存更新時は明示的にバージョンとlockを変更し、検証してください。

## オフラインで試す

```powershell
New-Item -ItemType Directory -Force data/local
# 初回だけ実行。DBが既にある場合はinit-dbを省略します。
.\.venv\Scripts\python.exe -m oni_ai init-db data/local/knowledge.sqlite3
.\.venv\Scripts\python.exe -m oni_ai search data/local/knowledge.sqlite3 "Manual Generator"
.\.venv\Scripts\python.exe -m oni_ai mock-demo
```

`init-db` は既存ファイルを上書きしません。再実行時は別名を指定してください。`search` はSQLiteの `mode=ro` と `query_only` で開きます。DBファイルとローカルツールはGit対象外で、スキーマとseedを管理します。

サンプルは `Tile`、`PlanterBox`、`ManualGenerator` のIDと資料中の名称だけです。電力・資材・入出力など未確認のゲーム仕様は `UNKNOWN`、ゲームバージョンとDLC範囲も `UNKNOWN` です。名称は資料上の表記であり、公式日本語訳ではありません。

この3件はPhase 0互換の初期seedとして維持しています。Phase 1の追加catalogは明示的に取り込みます。過去の公式更新記録のビルドに限定した2設備バリアント・5ルールで、現在版の設備性能を推定して埋めるものではありません。

## Phase 1の知識DB

新規init-dbはSchema 2を作成します。既存のSchema 1はそのまま読み取れます。移行する場合は別ファイルへコピーし、元DBを上書きしません。

```powershell
# Phase 0の既存DBがある場合。出力ファイルは未作成の名前を指定します。
.\.venv\Scripts\python.exe -m oni_ai migrate-db data/local/knowledge.sqlite3 data/local/phase1.sqlite3
.\.venv\Scripts\python.exe -m oni_ai import-catalog data/local/phase1.sqlite3
.\.venv\Scripts\python.exe -m oni_ai audit-db data/local/phase1.sqlite3
.\.venv\Scripts\python.exe -m oni_ai rules data/local/phase1.sqlite3 --domain water --game-version 348553
```

元DBがない場合はinit-dbでdata/local/phase1.sqlite3を作成し、import-catalogから進めます。取込み後は4設備ID・5バリアント・5ルール。設備属性50件のうち45件はUNKNOWNです。追加したのは出典が確認できた名称・版別ルールであり、設備の電力・入出力・資材量の追加確定は0件です。

## 合成環境で観測・模擬行動・評価

```powershell
.\.venv\Scripts\python.exe -m oni_ai fixtures
.\.venv\Scripts\python.exe -m oni_ai simulate normal --decisions examples/observe_one_tick.json --log data/local/observe-one-tick.jsonl
.\.venv\Scripts\python.exe -m oni_ai replay data/local/observe-one-tick.jsonl
.\.venv\Scripts\python.exe -m oni_ai operations
```

fixtureはnormal、oxygen_shortage、food_shortage、power_shortage、work_stalled、water_shortage、research_locked、unknown_oxygenの8件です。実ゲーム由来データはありません。量・レート・閾値は任意の合成値で、ONIの仕様ではありません。

明示的なDecisionだけを適用し、行動や攻略順序を自動選択しません。判断根拠・前後状態・失敗要因・指標をローカルJSONLに保存し、replayで遷移の自己整合性を検証します。既存ログは上書きしません。詳細は[評価基盤設計](docs/offline_evaluation.md)を参照してください。

`mock-demo` の出力には `MOCK_SYNTHETIC_NOT_GAME_DATA` と明記します。AI本体はProtocolで設計した段階で、モデルAPIや自動プレイヤーは実装していません。

## 成果物

- [OniMcp調査報告書](docs/oni_mcp_research.md)：固定コミット、API、プロトコル、依存、制限、ライセンス
- [知識DB設計書](docs/knowledge_db_design.md)：UNKNOWN、出典、検証状態、バージョン、検索
- [接続アダプタ・AI設計と次Phase計画](docs/next_phase_plan.md)
- [Steam / Kleiの適用条件](docs/terms_review.md)
- [Phase 0検証記録](docs/phase0_validation.md)
- [参照ファイルの証跡](docs/source_evidence.json)
- [Phase 1変更判断](docs/phase1_decisions.md)、[知識の採否・出典](docs/phase1_sources.md)
- [オフライン実験・評価設計](docs/offline_evaluation.md)、[Phase 1検証記録](docs/phase1_validation.md)
- [観測・行動JSON Schema](src/oni_ai/data/experiment_schemas.json)

調査したOniMcpコミット：`14c08591cbd0bf66cd0f53b37bfb498bdef4abf6`（0.2.6）。READMEのMCP互換性説明とコードに不一致があり、固定コードでは `2025-11-25` のみサポートしています。1.0未満で変更可能性が高く、将来は実行時manifestが最終仕様です。

## 作業範囲

ゲーム本体、MODフォルダ、既存セーブ、Steam設定には触れません。実ゲーム接続、無人操作、公開サーバー、.NET/Rust導入は行いません。GitHub originは既存のものを使用し、Phase 1のpushは別途承認を待ちます。秘密情報は保存せず、将来必要な設定は環境変数等へ分離します。

Phase 2では合成環境上の自律判断ループを構築することを推奨します。Steam規約には自動化禁止条項があるため、MOD利用可能という事実だけから実ゲーム自律プレイの許可を推定しません。実ゲーム接続に進む前に適用条件・必要な許諾と利用者の承認を確認します。
