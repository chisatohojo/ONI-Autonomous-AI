# ONI_Autonomous_AI

Oxygen Not Included（ONI）の自律プレイAIを研究する独立プロジェクトです。ゲームルール・設備仕様・操作仕様を事前知識とし、将来の判断・計画・改善はAIが担う設計です。Klei・Valveの公式プロジェクトではありません。

**Phase 3（0.3.0）：複数Policyを同条件で比較し、構造化主張・プロセス期限・開発/評価分離を検証する合成研究環境。実ゲーム・外部LLMには接続しません。**

**Phase 4B1（0.4.0b1）：socket遮断を維持する推論IPC、mock専用ローカルモデルadapter、予約予算・usage照合、比較plan/report v2を追加しました。実モデル・runtimeの導入、LLM通信、課金は行っていません。**

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

上記simulateはPhase 1互換の明示的なDecision実行です。判断根拠・前後状態・失敗要因・指標をローカルJSONLに保存し、replayで遷移の自己整合性を検証します。自律実験には下記episodeを使用します。既存ログは上書きしません。詳細は[評価基盤設計](docs/offline_evaluation.md)を参照してください。

すべての実験データにMOCK_SYNTHETIC_NOT_GAME_DATAと明記します。初期Policyは汎用の乱数探索テスト用であり、攻略用のAIや学習済みPolicyではありません。

## Phase 2の自律実験

```powershell
.\.venv\Scripts\python.exe -m oni_ai episode --split development --seed 2 --policy-seed 0 --max-steps 20 --log data/local/episode-dev.jsonl
.\.venv\Scripts\python.exe -m oni_ai episode-result data/local/episode-dev.jsonl
.\.venv\Scripts\python.exe -m oni_ai episode-replay data/local/episode-dev.jsonl
.\.venv\Scripts\python.exe -m oni_ai benchmark --split evaluation --seeds 0 1 2 17 --max-steps 20 --output-dir data/local/evaluation-run
```

logと出力ディレクトリは未作成の名前を指定します。--db data/local/phase1.sqlite3を追加すると、読み取り専用のゲーム知識snapshotも検索対象にできます。初期Policyは合成モデルを検索し、実ゲームの知識を合成行動の根拠として流用しません。

Policyにはfixture名・元process名・評価seedを渡しません。提案の観測digest、根拠の存在と適用範囲、UNKNOWN、資源等の前提を検証し、最大試行・進展停止・反復・例外で停止します。生存の代理指標、資源、進捗、無効試行率を別々に記録します。固定攻略順や正解行動表はありません。

開発用と評価用は別の初期値範囲・seed名前空間です。評価には未知値や未見processを含めます。replayはPolicy/API/元DBなしで検索・検証・遷移・停止・評価を再計算します。詳細は[Phase 2設計](docs/autonomous_episodes.md)と[検証記録](docs/phase2_validation.md)を参照してください。

## Phase 3のPolicy比較

```powershell
.\.venv\Scripts\python.exe -m oni_ai comparison-prepare data/local/my-study --db data/local/phase1.sqlite3
.\.venv\Scripts\python.exe -m oni_ai compare data/local/my-study/plan.json --group development
.\.venv\Scripts\python.exe -m oni_ai comparison-freeze data/local/my-study/plan.json
.\.venv\Scripts\python.exe -m oni_ai compare data/local/my-study/plan.json --group regression
.\.venv\Scripts\python.exe -m oni_ai compare data/local/my-study/plan.json --group heldout
.\.venv\Scripts\python.exe -m oni_ai comparison-verify data/local/my-study/heldout/report.json
.\.venv\Scripts\python.exe -m oni_ai research-replay data/local/my-study/heldout/203-0-lookahead.jsonl
```

my-studyには未作成の出力先を指定します。--dbは省略可能です。比較基準は既存のSeededTestPolicy、新Policyは深さ2・上位8候補の汎用モデル探索です。固定攻略順や資源別の正解表はありません。同じ初期状態・観測範囲・Policy seed・操作上限・時間予算で比較し、開発reportとソースを固定してから評価を解禁します。

Policyは専用プロセスで動き、期限超過時は終了と一時ファイル削除を確認します。構造化主張は取得値・statusと照合します。自然言語の完全な意味検証やOS sandboxではありません。Phase 1/2のCLI・ログ・DBは維持し、Phase 3のresearchログを別形式にしています。

開発36件・既公開seedの回帰36件・新seedの保留48件、計120件を実行し全件再現できました。保留の目標達成は探索0/24、新Policy3/24ですが、需要充足の代理指標は悪化しており、総合改善や実ONIの攻略性能を主張しません。JSON/CSV/Markdownの詳細はローカルのdata/local/phase3-study-20261102にあり、Git対象外です。設計・限界・結果は下記文書を参照してください。

## Phase 4Aの調査結果

開発PCはCore i9-12900K、RAM16GiB、RTX4060の専用VRAM8,188MiBです。調査時の空きRAMは約3.6GiB、空きVRAMは約5.4GiBで、推論速度や実モデルのピークメモリはUNKNOWNです。

最初はQwen3.5-4B/Q4_K_M＋Ollamaを短context・並列1で条件付き評価するA（ローカルのみ）を推奨します。メモリ不適合なら2B等へ再選定し、自動でcloudへ送信しません。別途承認された場合のcloud品質参照はGPT-6.1 Sol、低費用対照はGPT-6 Lunaです。この課題での順位は未測定です。

費用例は8,000入力＋1,500課金出力tokens/判断で1,000判断ならSol $31、Luna $1.55。思考tokenを含む仮定で、retry・税等は別です。これは見積もりで、利用承認ではありません。Phase 4Bでは既存workerのsocket遮断を維持するbroker、正確なtoken計数、新しいplan/report版と保留条件を先に用意します。

## Phase 4B1のmock推論接続

```powershell
.\.venv\Scripts\python.exe -m oni_ai model-compare-prepare data/local/my-model-study --db data/local/phase1.sqlite3 --max-steps 5
.\.venv\Scripts\python.exe -m oni_ai model-compare data/local/my-model-study/plan.json --group mock-development
.\.venv\Scripts\python.exe -m oni_ai model-compare-freeze data/local/my-model-study/plan.json
.\.venv\Scripts\python.exe -m oni_ai model-compare data/local/my-model-study/plan.json --group mock-validation
.\.venv\Scripts\python.exe -m oni_ai model-compare-verify data/local/my-model-study/mock-validation/report.json
.\.venv\Scripts\python.exe -m oni_ai model-episode-replay data/local/my-model-study/mock-validation/5003-0-model-mock.jsonl data/local/my-model-study/mock-validation/5003-0-model-mock.audit.json
```

出力先は未作成の名前を使い、--dbは必要なら省略します。3 Policy×2環境seed×2 Policy seedを各groupで実行します。model-mockは探索Policyを返すtest doubleで、LLMの判断性能を測るものではありません。mock-validationも配線検証用で、Phase 4B2の新しい保留評価ではありません。

専用Policy/brokerプロセスは両方socket遮断・環境変数allowlistで起動します。IPCは検索・提案とcount/generateだけで、任意URL・コマンドを渡す口はありません。モデル・tokenizer・templateを固定した正確な計数がなければ生成前に停止します。現在の正確な計数は人工mockのUTF8 byte仕様だけで、実モデルは未対応です。入力＋最大出力を毎回予約し、失敗・usage不明を返金しません。期限超過・異常終了時はプロセス停止と一時領域削除を確認します。

旧researchログに推論監査sidecarを関連付け、JSON/CSV/Markdownと予約台帳を検証します。旧CLI・比較v1の形式は維持しています。自然言語の意味やOS全体の隔離を保証する仕組みではありません。詳細は[推論設計](docs/phase4b1_inference.md)、[検証記録](docs/phase4b1_validation.md)、[B2引継ぎ](docs/phase4b2_handoff.md)を参照してください。

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
- [Phase 2変更判断](docs/phase2_decisions.md)、[自律エピソード設計・LLM接続案](docs/autonomous_episodes.md)
- [Policy用JSON Schema](src/oni_ai/data/policy_schemas.json)、[Phase 2検証記録](docs/phase2_validation.md)
- [Phase 3変更判断](docs/phase3_decisions.md)、[Policy比較・検証設計](docs/policy_comparison.md)
- [Phase 3検証記録](docs/phase3_validation.md)、[比較結果の抜粋JSON](docs/phase3_results.json)
- [Phase 4のLLM接続計画・ローカル/クラウド比較](docs/phase4_model_plan.md)
- [Phase 4A PC環境報告](docs/phase4a_pc_environment.md)、[ローカルLLM候補](docs/phase4a_local_models.md)
- [クラウド候補・費用表](docs/phase4a_cloud_models.md)、[費用の前提・結果JSON](docs/phase4a_cost_estimates.json)
- [推奨構成・Phase 4B具体計画](docs/phase4b_implementation_plan.md)、[Phase 4A検証記録](docs/phase4a_validation.md)
- [Phase 4B1変更判断](docs/phase4b1_decisions.md)、[推論IPC・比較v2設計](docs/phase4b1_inference.md)
- [Phase 4B1検証記録](docs/phase4b1_validation.md)、[Phase 4B2導入・評価手順](docs/phase4b2_handoff.md)

調査したOniMcpコミット：`14c08591cbd0bf66cd0f53b37bfb498bdef4abf6`（0.2.6）。READMEのMCP互換性説明とコードに不一致があり、固定コードでは `2025-11-25` のみサポートしています。1.0未満で変更可能性が高く、将来は実行時manifestが最終仕様です。

## 作業範囲

ゲーム本体、MODフォルダ、既存セーブ、Steam設定には触れません。実ゲーム接続・操作、外部LLM API、有料サービス、公開サーバー、.NET/Rust導入は行いません。GitHub originは既存のものを使用します。Phase 1のd003276、Phase 2の27fb339、Phase 3のd0e3d5b、Phase 4Aの8a96055は承認後push完了済みです。Phase 4B1のpushは別途承認を待ちます。秘密情報は保存せず、将来必要な設定は環境変数等へ分離します。

合成実験の結果を実ゲームの攻略性能とは扱いません。実ゲームへの接続・自律操作に進む前に適用条件・必要な許諾と利用者の承認を確認します。
