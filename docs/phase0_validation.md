# Phase 0 検証記録

実施日：2026-11-01（Asia/Tokyo）。対象：このリポジトリの独自Python実装。OniMods/.NETの上流テスト、ONI実機テストは対象外・未実施です。

## 環境

- OS：Windows x64 / PowerShell
- Python：3.12.12（プロジェクト内のmanaged CPython、.venv）
- pytest：8.4.2、ruff：0.14.3、ビルド用setuptools：80.9.0
- uv：0.9.7。bootstrap wheelの固定SHA256を照合してから使用
- 実行時の外部Python依存：0。開発依存とその推移依存はuv.lockで固定
- pyランチャーの3.12登録先は実体が欠損。既存登録は変更せず、.tools/pythonに別途構築

## 実施結果

| チェック | 結果 |
| --- | --- |
| python scripts/bootstrap.py | PASS。ハッシュ再照合・Python確認・frozen sync |
| 別の空venvへのuv sync --frozen --extra dev | PASS。.tools/rebuild-venvに同じ固定依存を構築 |
| .venv/Scripts/python.exe -m pytest | **31 passed** |
| 再構築したvenvでのpytest | **31 passed** |
| ruff check . | PASS |
| ruff format --check . | PASS |
| uv build --wheel | PASS。schema.sqlとseed.jsonを同梱 |
| wheelを別venvへ--no-depsで導入 | PASS |
| wheelからinit-db / search / mock-demo | PASS。ソースeditable installに頼らず起動 |
| SQLite integrity_check / foreign_key_check | PASS（pytestで検証） |

## テストの範囲

31件は、根拠・版・UNKNOWNの維持、検索のSQL注入/ワイルドカード対策、入力制限、版/DLCの厳密フィルタ、DB読み取り専用、上書き防止、未知スキーマ拒否、数値/単位/根拠のDB制約、整合性、mock URIのallowlist、fixtureのコピー、欠落fixture拒否、AI計画ポートのmock、CLIのエラー表示とライブ接続コマンド不在を検証します。数値0を入れるテストは合成テスト値であり、seedには含めません。

pytestではautouse fixtureでsocket生成・名前解決・接続を失敗させます。テストは実ネットワーク、ゲーム、ゲームファイル、モデルAPIに依存しません。これはOS全体の通信遮断ではなくテストプロセス内の防止策です。環境構築時の通常の依存ダウンロードは別です。

## 作業境界

作業開始時、フォルダは空で親もGitリポジトリではありませんでした。このフォルダだけをmainブランチの新規Gitリポジトリにしました。remoteは設定しません。

ONI本体、MODフォルダ、既存セーブ、Steam設定は読み書き・接続対象にしていません。外部コードはGitHub接続ツールでテキストとして調査しただけで、OniModsのビルドスクリプトやDLLは実行していません。.NET/Rustの導入、サーバー起動、GitHub公開・push、Issue/メール送信はしていません。

コミット対象は独自コード、スキーマ/seed、設定、lock、調査文書です。.tools、.venv、DB、wheel、調査した外部コード本文は.gitignoreの対象です。最終ステージ内容の秘密情報候補と差分を確認してからローカルコミットを作成し、コミット後のgit statusを確認します。最終コミットIDは会話の完了報告とgit logで確認できます。

## 残る制限

実機での互換性・性能、数値設備仕様、AIのプレイ能力は検証していません。サンプルは3設備のID/名称のみ、27属性はUNKNOWNです。規約上の実ゲーム自律操作の許諾は未取得で、SteamのAutomation禁止に例外があるとは判断していません。次の推奨範囲は[オフラインPhase 1](next_phase_plan.md)です。
