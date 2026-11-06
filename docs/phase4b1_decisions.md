# Phase 4B1 実装判断（実装前）

2026-11-06（Asia/Tokyo）。開始HEAD 8a96055655ca7307123af0cfcdba1c015aa3a086、clean。既存199テスト、ruff check/format PASS。Phase 4B1の明示指示に基づき、Phase 4Aの「文書のみ」の範囲から、offline mockのIPC/adapter/v2比較へ進みます。モデル・runtime・tokenizer取得や実通信は許可範囲に含めません。

- 旧ModelReply/StructuredModel/Policy/EpisodeEngineと比較v1は維持します。新しいmock用接続層・比較v2を追加し、v1のPolicy名/seedを上書きしません。
- Policyとbrokerは明示allowlist環境の専用subprocessで動かし、JSONファイルのIPCだけを使います。socket遮断を維持し、URL・コマンド・任意importを要求できるRPCは作りません。終了時は両プロセスの停止と一時ファイル削除を確認します。
- Ollama形式のadapterは注入されたmock transportだけを使います。http実装・cloud接続口は追加しません。既存BudgetedModelAdapterからIPC proxyを通し、brokerでも独立に予約・usage照合を行います。
- mockの1 UTF8 byte=1 tokenという人工仕様だけを正確に数えます。実モデルのtokenizer/templateとの対応はUNKNOWNで、未対応registryは生成前に停止します。byte数を実LLM tokenの推定確定値にしません。
- schemaは小さい明示subsetとして検証・構築し、非対応/過大/循環参照等は生成前に拒否します。schemaと根拠validatorは別々に検査します。
- brokerは生成前の予約journalを残し、成功/失敗/usage不明を区別します。同一request IDの再送は再生成せず、内容が違う場合は拒否します。timeout等で結果不明の予約は返金せず、同じjournalからの自動再起動は行いません。
- 実モデルの性能比較ではなく、mockの配線・異常・再現性だけを評価します。Phase 4B2用の開発/保留条件は未実行の別計画として記録します。
