# Phase 4A：開発PCの読み取り専用調査

確認日：2026-11-02（Asia/Tokyo）。開始コミット d0e3d5b3b5dfd028dbd31f2670613db10caa0236。数値は照会時のスナップショットで、利用可能量の保証ではありません。シリアル番号、GPU UUID、PC名、アカウント、ユーザー固有パス、ボリューム名は取得対象から除外し、公開文書に保存していません。

## OS・CPU・メモリ・ストレージ

| 項目 | 確認値 | 根拠 |
| --- | --- | --- |
| OS | Microsoft Windows 11 Home、10.0.26200、build 26200、**x64** | Win32_OperatingSystem＋RuntimeInformation.OSArchitecture=X64、process表記AMD64 |
| CPU | Intel Core i9-12900K、16 cores / 24 logical processors | Win32_Processor |
| 物理RAM | 17,179,869,184 bytes = 16 GiB | Win32_PhysicalMemory.Capacityの合計 |
| OSで使用可能なRAM | 15.646 GiB | TotalVisibleMemorySize=16,406,480 KiB |
| 使用中 / 空きRAM | 12.031 / 3.616 GiB | FreePhysicalMemory=3,791,376 KiB。使用中は上記との差分 |
| システム用ドライブ空き | 35.378 GiB | Win32_LogicalDisk、固定ディスクのみ |
| データ用ドライブA空き | 778.540 GiB | 同上、実ラベル/マウント先は公開しない |
| データ用ドライブB空き | 632.200 GiB | 同上 |

容量は1 GiB=2^30 bytes。使用中RAMと空きRAMはOS可視範囲内の値であり、使用中＋空きが搭載物理16GiBと一致するとは限りません。メモリ解放のためにアプリ停止やOS設定変更は行っていません。モデル置場は将来、利用者が選ぶ十分な空きのあるデータ用領域を候補とし、今は作成・設定していません。

## GPU：専用VRAMの確認

検出GPUは**NVIDIA GeForce RTX 4060、1基**です。CPU内蔵GPUの有効/無効状態はUNKNOWNで、CPU名から利用可能GPUを追加推定していません。

| 確認経路 | 結果 | 扱い |
| --- | --- | --- |
| nvidia-smi query | total **8,188 MiB**、used 2,440 MiB、free **5,517 MiB（5.388 GiB）** | 専用VRAMの主な根拠 |
| レジストリのHardwareInformation.qwMemorySize | **8,585,740,288 bytes = 8,188 MiB** | 64bit容量値としてNVMLと一致 |
| Win32_VideoController.AdapterRAM | 4,293,918,720 bytes（約4GiB） | 上記と不一致。最終容量として採用しない |
| GPU driver | NVIDIA **610.88**、CIM表記32.0.16.1088 | nvidia-smi/CIMで照合 |
| Compute capability | **8.9** | nvidia-smi query |
| CUDA UMD version | **13.3** | nvidia-smi --versionのdriver側表示 |

totalをマーケティング上の8GB級と区別し、実際に取得したMiB値を保持しています。total/used/freeは別項目として記録し、差分を勝手に利用可能量へ加算していません。CIMの約4GiB値を根拠に4GB GPUと誤判定しない方針です。

## バックエンド・既存ランタイム

| 項目 | 検出したもの | 今回確認できた範囲 / UNKNOWN |
| --- | --- | --- |
| CUDA driver | nvcuda.dll、32.0.16.1088、NVML照会成功 | ドライバ検出済み。LLM/CUDA kernel実行は未測定 |
| CUDA Toolkit | nvccはPATH上になく、標準CUDAフォルダもなし | この範囲で未検出。全ディスクの未導入を断定しない |
| Vulkan | vulkaninfo --summaryでRTX 4060を列挙。Instance/API 1.4.341、driver610.88 | GPU列挙まで確認。LLM実行はUNKNOWN |
| DirectML / D3D12 | DirectML.dll 1.15.6、d3d12.dll 10.0.26100.9549 | DLLの存在/版のみ。device作成とONNX推論はUNKNOWN |
| Python（プロジェクト） | **3.12.12** | 既存venvを使用 |
| Python（通常PATHの実体） | 3.10.6 | PowerShellで取得した実体を直接--version。環境ごとにPATHが異なることを区別 |
| Python launcher / python3 | launcherのファイル版3.12.1、python3コマンドあり | launcher版はインタプリタ版ではない。python3実行先/実版はUNKNOWN |
| PyTorch / Transformers / ONNX Runtime / DirectML EP / llama-cpp-python / vLLM | プロジェクトvenvではすべて未導入 | import実行せず配布metadataを調査。他venvはUNKNOWN |
| Ollama / llama-cli / llama-server / lms / vllm | PATHで未検出 | Ollama/LM Studioの標準ユーザー配置先も未検出。独自配置はUNKNOWN |
| WSL / Docker / 別のLLMサービス / モデルcache | 未調査 | UNKNOWN。サービス接続、モデル列挙、個人ディレクトリ全走査はしない |

Ollamaの[公式GPU対応表](https://docs.ollama.com/gpu)ではRTX 4060/CC8.9が掲載され、ドライバ条件も示されています。現GPU/driverはその公称条件を満たしますが、実際のモデル実行成功は未確認です。DirectMLは[Microsoft公式説明](https://learn.microsoft.com/en-us/windows/ai/directml/dml)でDirectX12対応ハードウェアが対象とされています。DLLがあるだけで特定LLMの対応を確定しません。いずれも確認日2026-11-02。

## 再調査用コマンド（読み取りだけ）

```powershell
Get-CimInstance Win32_OperatingSystem -Property Caption,Version,BuildNumber,OSArchitecture,TotalVisibleMemorySize,FreePhysicalMemory |
  Select-Object Caption,Version,BuildNumber,OSArchitecture,TotalVisibleMemorySize,FreePhysicalMemory
Get-CimInstance Win32_Processor -Property Name,NumberOfCores,NumberOfLogicalProcessors |
  Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
Get-CimInstance Win32_PhysicalMemory -Property Capacity | Measure-Object Capacity -Sum
Get-CimInstance Win32_VideoController -Property Name,AdapterRAM,DriverVersion |
  Select-Object Name,AdapterRAM,DriverVersion
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,driver_version,compute_cap --format=csv,noheader
nvidia-smi --version
vulkaninfo --summary | Select-String 'Vulkan Instance Version|deviceName|deviceType|driverName|driverInfo|apiVersion|driverVersion'
```

追加調査では、標準のVideoレジストリ配下の0000キーからDriverDescとHardwareInformation.qwMemorySizeだけを選択し、DLLのFileVersionInfo、Get-Commandの存在判定、固定ディスクのSize/FreeSpace、importlib.metadataを使用しました。レジストリ全出力やシリアル等を含む全プロパティ出力は保存していません。

判断：8GB級GPUは小型量子化モデルの候補になります。ただし現在の空きRAM約3.6GiBとVRAM約5.4GiBを考慮すると、大規模モデルや長大context、複数モデル常駐は推奨できません。適合性は[ローカル候補](phase4a_local_models.md)の条件付き評価とし、推論速度・ピークメモリはUNKNOWNです。
