# Phase 4A：ローカルLLM候補

確認日：2026-11-02（Asia/Tokyo）。モデルカード、公開設定、配布metadataとランタイム公式資料を閲覧しました。重み・tokenizer・ランタイムを取得せず、推論性能は一切実測していません。公称benchmarkをONIでの判断性能へ読み替えません。

## 候補比較

| 候補 | 言語・計画/指示追従の資料 | 公称context / 構造化出力 | ライセンス表記 | このPCでの位置付け |
| --- | --- | --- | --- | --- |
| **Qwen3.5-4B** | 多言語・agent/reasoningを公称。日英の個別品質はUNKNOWN、要比較 | 262,144。JSON Schema制約は採用runtimeとの組合せで検証 | Apache-2.0 | **主候補**。Q4_K_Mのmodel表示3.3GB、tag全体4.0GB。text-only・短contextから条件付き試験 |
| **Qwen3.5-2B** | 同系列の小型候補。複数制約や失敗後の修正能力はUNKNOWN | 262,144（カード）。runtime/量子化で品質・対応が変わる | Apache-2.0 | **省メモリ代替**。確認したtag全体は3.1GBであり、「2Bだから必ず1GB」ではない |
| **Gemma 4 E2B IT** | 多言語・reasoning/function callingを公称。日英のこの課題での品質はUNKNOWN | 小型版128K。JSON Schemaはruntimeで制約 | Apache-2.0（カード/公式リンク） | 第2系列の比較候補。ただし2.3B effectiveに対しembeddings込み5.1B。現在tag全体7.5GBで余裕が小さい |
| **Phi-4-mini-instruct** | 日英を含む24言語、3.8B、reasoning/tool use。関数名の幻覚の限界もカードに記載 | 128K。schema制約はruntimeで別検証 | MIT | 小型の別系列候補。Ollamaのphi4-mini表示2.5GB。量子化の確定版は選定時に確認 |
| Qwen3.8-27B等の大きい公開モデル | 最新系列も入手可能だが、このPCの初回候補にはしない | 長contextがあっても現在のRAM/VRAMとは別問題 | 対象artifactの条件は選定前再確認 | 27B×4bitだけで理論13.5GB。8GB GPUへの全量常駐を前提にしない。offload速度もUNKNOWN |

出典：Qwenの[4Bカード](https://huggingface.co/Qwen/Qwen3.5-4B)・[2Bカード](https://huggingface.co/Qwen/Qwen3.5-2B)、Googleの[Gemma 4 E2Bカード](https://huggingface.co/google/gemma-4-E2B-it)、Microsoftの[Phiカード](https://huggingface.co/microsoft/Phi-4-mini-instruct)、Qwenの[公式公開モデル一覧](https://huggingface.co/Qwen/models)。新しさだけで選ばず、公開配布・ライセンス・短contextの適合性を優先しています。

ライセンス表記は確認できた資料の状態です。Qwenの[LICENSE](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/LICENSE)とGemmaカードが指す[公式Apacheライセンス](https://ai.google.dev/gemma/apache_2)も参照しました。Gemmaの当該repoの同名LICENSEパスは404でした。実際に導入する量子化配布物のLICENSE/NOTICE・変換元・利用条件はPhase 4Bの取得前に確認します。第三者の重みやモデルカード本文を転載していません。trust_remote_codeのサンプルを無条件に実行する方針ではありません。

## 実行環境の比較

| 環境 | 利点・接続方式 | このPCと運用上の注意 |
| --- | --- | --- |
| **Ollama（第一候補）** | Windows向け運用、ローカルHTTP、formatにJSON Schema。Qwen3.5/Gemma4の配布tagを確認 | CUDA対応表にRTX4060。必要な版・タグdigestを固定。自動取得やcloud tagを禁止する設計が必要 |
| **llama.cpp** | CUDA/Vulkan等を選択でき、GGUF・schema/grammar制約を細かく固定する比較候補 | artifactとbackend版の組合せ確認が必要。ビルド環境/Toolkitは現在未導入なので、Phase 4Bでは検証済み配布物の選定を先に行う |
| **LM Studio** | GUIで確認でき、OpenAI互換APIとJSON Schemaがある | 今回未検出。GUI/サービスとruntimeの版・利用条件を別管理。自動ロード/更新も実験条件に含める |
| Transformers / vLLM / SGLang | tokenizerや高度なservingの選択肢 | 新規依存・対応版・メモリ・Windows運用の負担が増える。Phase 4B最小構成には採用しない |
| DirectML / ONNX Runtime | 別のWindows推論経路候補 | DLLのみ検出。モデル変換、対応operator、構造化decodeはUNKNOWN。CUDA経路があるため初回の優先度は低い |

根拠：[Ollama GPU](https://docs.ollama.com/gpu)、[structured outputs](https://docs.ollama.com/capabilities/structured-outputs)、[llama.cpp build](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)、[LM Studio structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output)。Ollamaのcloud版は、確認したstructured-output資料では未対応とされており、ローカル版と同一視しません。

## サイズとメモリの適合性

公開tagは可変です。今回閲覧したmetadataは[Qwen4B](https://ollama.com/library/qwen3.5:4b)のtag短縮digest 7f3251fa6878、全体4.0GB、model d8b0f5e9760c 3.3GB/Q4_K_M、別にBF16 projectorを含みます。[Qwen2B](https://ollama.com/library/qwen3.5:2b)のtag表示は3.1GB、model 2.7GB/Q8_0です。2Bのdefaultが4bitとは仮定しません。[GemmaE2B](https://ollama.com/library/gemma4:e2b)は45d11505b91d、全体7.5GB、model b37049369adf 4.6GB/Q4_K_Mにprojector/draft等を伴います。[Phi](https://ollama.com/library/phi4-mini)は2.5GB表示です。これらは配布ファイルの表示値であり、VRAMピークや全ファイルのGPU常駐量ではありません。短縮digestは将来の完全hash検証の代わりにはなりません。

Qwen4Bを主候補にする根拠は、現在の空きVRAM5.388GiBに対し、表示modelファイル3.3GBは約3.1GiBで、限定contextなら検証する余地があることです。RAM空きは3.616GiBしかなく、ロード中のホスト側buffer、mmapページ、CPU offload、driver領域も必要なため**動作保証ではありません**。まずtext-only、並列1、常駐1モデル、context4,096、入力最大2,048・出力/思考合計最大1,024 tokensを試験案とし、速度より最初にピークメモリとJSON成功率を測ります。合計contextにはchat templateやsystem指示の余裕も必要です。2Bへの縮小も、実際の配布内容とメモリ測定に基づいて判断します。

計算例（実測ではない）：[Qwenの公開config](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/config.json)は32層、full attention8層、KV heads4、head_dim256を示します。full attention部分のFP16 K/Vだけなら、`2 × 8 × 4 × 256 × context × 2 bytes`で4K≈128MiB、8K≈256MiBです。linear attentionの状態、MTP、activations、backend workspace、projector、allocator、OS表示用GPUメモリを含まない**部分量の概算**です。全32層を通常KVとして計算した値や、4bit重みの比率だけで動作可否を確定しません。

モデルの公称最大contextを設定して起動する方針ではありません。CPU-onlyもRAM・帯域・実装依存で、tokens/s・初回遅延・日本語のtoken数・思考出力長・量子化による精度差はすべてUNKNOWNです。既存アプリの停止やRAM増設は今回は行わず、必要なら利用者が別途判断します。

選定結論：ローカルの**Qwen3.5-4B/Q4_K_M＋Ollamaを条件付き第一候補**とし、メモリ/JSON検査不合格時は2B、別系列はPhi-4-miniまたはtext-onlyのGemma構成を再選定します。固定攻略手順の有無ではなく、日英の同一観測・UNKNOWN・資源前提・失敗履歴に対する判断を比較します。
