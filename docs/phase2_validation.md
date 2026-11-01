# Phase 2 検証記録

実施日：2026-11-01（Asia/Tokyo）。開始HEAD：d003276be4e9b68977b4fb2d5b789ddd39063ffc。既存originを継続使用し、新規clone/initや履歴の書換えは行っていません。Phase 1のpushは承認後完了済みです。

## チェック結果

| チェック | 結果 |
| --- | --- |
| 作業前のpytest | **96 passed** |
| 作業前ruff check / format --check | PASS |
| Phase 2全pytest | **147 passed**（既存96 + 追加51） |
| ruff check . | PASS |
| ruff format --check . | PASS（29 Python files） |
| uv lock / sync --frozen --extra dev | PASS、依存追加0、版0.2.0 |
| CLIで開発6 seed・評価6 seed | 計12エピソード、全件replay PASS |
| wheelビルド、別venvへの--no-deps導入 | PASS |
| wheelのisolated Pythonからepisode / result / replay | PASS（12試行連続） |
| wheelから別の評価2 seed | PASS、全件replay |

Python 3.12.12、pytest 8.4.2、ruff 0.14.3、uv 0.9.7、setuptools 80.9.0を使用。実行時の外部依存は0です。外部LLM APIや有料サービスは利用していません。

## 再開後の最終確認（2026-11-02、Asia/Tokyo）

- HEADはPhase 1のd003276で、Phase 2のローカルコミットは未作成でした。既存の未コミット変更を保持して点検し、再実装や履歴の書換えは行っていません。
- 全pytestを再実行し147 passed、ruff check / format --checkもPASS（29 Python files）でした。
- 開発6 seed・評価6 seedを新規出力先へ再実行し、全12件でepisode-resultとepisode-replayもPASSしました。下表と同じ試行数・終了理由を確認しました。
- 単独episodeの実行・結果表示・再現と、前回導入したwheelの別venvからのisolated Pythonによる同じ一連の操作もPASSしました。参照DBの実行前後のSHA256は一致しています。
- 再検証の生成物はdata/local/phase2-resume-20261102-010d226dへ保存し、Git対象外です。今回のソースコード修正はなく、再開後の記録と引継ぎ文書のみ補足しました。

## 実際に実行したCLI検証

Policy seed=0、max_steps=30、各splitの環境seed=0,1,2,17,42,101。--db data/local/phase1.sqlite3を指定して読み取り専用snapshotを同梱しました。根拠付きの初期テストPolicyは合成modelを検索しています。

| split | seed | 試行数 | 適用 | 拒否 | 終了理由 | 再現 |
| --- | --- | --- | --- | --- | --- | --- |
| development | 0 | 16 | 16 | 0 | NO_PROGRESS | PASS |
| development | 1 | 16 | 16 | 0 | NO_PROGRESS | PASS |
| development | 2 | 16 | 16 | 0 | NO_PROGRESS | PASS |
| development | 17 | 12 | 12 | 0 | NO_PROGRESS | PASS |
| development | 42 | 12 | 11 | 1 | NO_PROGRESS | PASS |
| development | 101 | 16 | 16 | 0 | NO_PROGRESS | PASS |
| evaluation | 0 | 12 | 7 | 5 | NO_PROGRESS | PASS |
| evaluation | 1 | 12 | 9 | 3 | GOAL_REACHED | PASS |
| evaluation | 2 | 12 | 10 | 2 | NO_PROGRESS | PASS |
| evaluation | 17 | 12 | 9 | 3 | NO_PROGRESS | PASS |
| evaluation | 42 | 12 | 9 | 3 | NO_PROGRESS | PASS |
| evaluation | 101 | 12 | 9 | 3 | NO_PROGRESS | PASS |

ログとreport.jsonはdata/local/phase2-development、data/local/phase2-evaluationに保存し、Git対象外です。GOAL_REACHEDは指定した合成work量の到達だけを示し、生存や攻略成功を表しません。この表は配線・検証・再現の実行証拠であって、Policyの汎化性能やONIの攻略性能の比較ではありません。

## 追加テストの内容

- 複数ステップ、交換Policy、取得根拠、失敗履歴を利用した提案修正、履歴窓と不変データ。
- fixture名・description・split/seed・元process名をPolicyへ渡さないこと、一意contextと観測schema 2。
- stale digest/tick/context、未知/未取得の根拠、根拠不足、未知操作、重複ID、UNKNOWN未申告の拒否。
- 対象processの資源不足、未知資源、研究条件、障害を実行前に検査し、状態不変で拒否すること。
- 最大試行、進展停止、IDを替えた同一行動の反復、目標達成、初期目標/未知目標、Policy例外、実行例外での停止。
- 大きなログの予算停止・未記録stepのrollbackと完結したログのreplay。
- DB snapshotの版/status/UNKNOWN維持、合成モデルに不適合な実ゲーム根拠の拒否、DBを使わない再現。
- proposal・検索結果・状態・指標・終了判定の不一致と、不完全ログの検出。
- 開発/評価の初期食料範囲の非重複、評価側のUNKNOWN・追加process、複数seedの再現とCLIの一連の動作。

全テストで既存のsocket遮断を維持しています。Phase 1の明示行動・読取mock・SQLite schema 1/2・元の96テストは維持しています。新しい自律episodeのログ/Policy schemaは別形式です。

## 制限と引継ぎ

初期Policyは乱数探索のテスト用で、固定攻略手順・状況別の正解表・LLM接続はありません。生存は合成需要充足の代理指標です。実ゲームの地形・移動・温度・電網・複製人間AI・実レシピはモデル化していません。

自由記述の理由を自然言語ですべて検証する機能、任意Policyの強制タイムアウト、ログ署名、実ゲームの数値仕様やOniMcp実行時manifest・文書差異・許諾は未解決です。将来のLLMアダプタは[Phase 2設計](autonomous_episodes.md)の境界を維持し、提供元・費用・データ送信範囲・キー管理・期限を決めてから別途追加します。

最終差分は24ファイルです。コミット対象の全61テキストファイルで秘密情報パターンと禁止生成物の混入を点検し、検出0件、ローカルMarkdownリンク51件も存在を確認しました。DB、評価report、JSONL、環境、wheelがGit対象外になることを確認しています。既存のPhase 1コア実装と元の96テストは変更していません。

ローカルコミットとして記録し、今回のpushは承認を待ちます。最終コミットIDと作業ツリー状態は完了報告で示します。
