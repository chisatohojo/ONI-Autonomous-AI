# Phase 2の実装判断（実装前記録）

日付：2026-11-01（Asia/Tokyo）。開始HEAD：d003276be4e9b68977b4fb2d5b789ddd39063ffc。既存コード、next_phase_plan、offline_evaluationを確認。ベースライン：96 passed、ruff check / format --check PASS。

- Phase 1のSyntheticEnvironment、Decision、run_experiment/replayは互換性を保持する。自律ループは別のepisode層に追加し、DBスキーマも変更しない。
- fixture名・description・元process名はPolicyに渡さない。episodeごとの不透明IDとprocess IDへ置換し、観測digestも使って古い状態を拒否する。元fixtureとsplit/seedは再現用ログだけに保持する。
- 交換可能なPolicyは知識検索要求と構造化提案を返す。初期実装はseed付きの一般的な探索テスト用であり、資源名や危機別の正解行動表、攻略順を持たない。
- 合成モデルのルール・processの入出力・操作仕様を検索可能な独立した根拠として提供する。実ゲームDBは読み取り専用snapshotから検索できるが、合成行動を正当化する根拠にはしない。UNKNOWN/CONFLICTED/版不適合を根拠として確定利用しない。
- 観測、知識結果、判断、検証、dry-run、実行、評価、記憶を別段階で扱う。対象processの資源不足等は実行前に拒否する。待機中に起こる需要不足は環境結果として評価し、待機を支出行動とは同一視しない。
- 学習・開発と評価には別seed名前空間・別パラメータ範囲を使う。評価には未知値・未見process・条件の組合せを含め、splitとseedをPolicyへ正解ラベルとして渡さない。
- エピソードログは知識snapshotとモデルを含む自己完結形式にする。replayはPolicy/APIを再実行せず、検索・検証・遷移・停止・評価を再計算する。外部のPolicy例外等は記録された故障イベントとして再現し、例外原因そのものを再現したと主張しない。
- 生存は実際の死亡モデルではなく、合成の生命維持需要を満たしたかの代理指標である。UNKNOWNは不明のまま。資源・進捗・無効行動率と独立に記録し、実ゲーム攻略能力は評価しない。
- 実ゲーム、外部LLM、有料サービス、公開サーバーは利用しない。pushは今回の変更について改めて承認を求める。過去のPhase 1 push待ち表記は完了済みの履歴へ訂正する。
