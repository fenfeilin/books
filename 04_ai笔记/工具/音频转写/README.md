# 音频转写工具

这个目录用于把本地音频转成文本，适合整理播客、课程、访谈、绘本音频和个人素材。工具链尽量离线运行：先统一转换为 `16kHz / mono / WAV`，再用 `whisper.cpp` 输出转写文本。

## 目录结构

- `bin/whisper-main`：whisper.cpp 转写程序。
- `bin/mp3_to_wav_minimp3`：轻量 MP3 转 WAV 工具，适合批量英文 MP3。
- `bin/ffmpeg`：通用音频转换工具，用于处理 `m4a/mp4/aac/wav` 等格式。
- `models/ggml-base.en.bin`：英文 Whisper base.en 模型。
- `models/ggml-base.bin`：多语言 Whisper base 模型，适合中文、自动识别和混合语言。
- `scripts/transcribe_audio.sh`：转写单个音频，支持 `mp3/m4a/mp4/aac/wav`。
- `scripts/batch_transcribe_audio_dir.sh`：批量转写一个目录里的常见音频文件。
- `scripts/transcribe_mp3.sh`：旧入口，默认按英文 MP3 流程调用新版脚本。
- `scripts/batch_transcribe_mp3_dir.sh`：旧入口，默认批量处理英文 MP3。
- `src/`：MP3 转 WAV 工具源码和依赖头文件，方便以后重编译。

## 单个音频转写

在 Vault 根目录或任意目录运行均可：

```bash
./00_管理系统/工具/音频转写/scripts/transcribe_audio.sh "/path/to/audio.m4a" "/path/to/output_dir" zh
```

参数说明：

- 第 1 个参数：输入音频路径，支持 `mp3/m4a/mp4/aac/wav`。
- 第 2 个参数：输出目录，可省略；默认写入当前目录的 `transcripts`。
- 第 3 个参数：语言，可省略；常用值为 `zh`、`en`、`auto`，默认 `auto`。

输出目录结构：

- `wav/`：中间 WAV 文件。
- `txt/`：转写结果，默认生成 `.txt`、`.srt`、`.json`。
- `logs/`：转换和转写日志，排错时查看。

## 批量转写目录

```bash
./00_管理系统/工具/音频转写/scripts/batch_transcribe_audio_dir.sh "/path/to/audio_folder" "/path/to/output_dir" auto
```

如果不写第二个参数，默认输出到音频目录下的 `_transcripts`。如果不写第三个参数，默认自动识别语言。

## 英文 MP3 兼容入口

旧脚本仍可使用，默认语言为英文，并优先使用 `ggml-base.en.bin`：

```bash
./00_管理系统/工具/音频转写/scripts/transcribe_mp3.sh "/path/to/audio.mp3" "/path/to/output_dir"
./00_管理系统/工具/音频转写/scripts/batch_transcribe_mp3_dir.sh "/path/to/mp3_folder" "/path/to/output_dir"
```

## 使用建议

- 播客、访谈和课程：优先使用 `zh` 或 `auto`，转写后再人工校正人名、专有名词和数字。
- 英文绘本或英文材料：使用旧 MP3 入口，或在新版脚本第三个参数传 `en`。
- 有配乐、角色音、笑声或多人抢话的音频，Whisper 结果适合作整理底稿，不建议直接当逐字稿发布。
- 只需要文本时，可在确认无误后删除输出目录里的 `wav/`，保留 `txt/` 和必要日志。

## 脱敏规范

- README 和脚本示例只保留占位路径，不写入个人目录、具体项目名、课程名、节目链接或输出结果。
- 转写结果建议放在具体项目目录，不放进本工具目录。
- 日志中可能包含输入文件名和本地路径；对外分享前请先检查 `logs/`。
- 如果需要公开这个工具目录，建议只保留 `README.md`、`scripts/`、`src/`，不要附带模型、音频、转写结果或日志。

## 常见问题

### 为什么先转 WAV？

`whisper.cpp` 对 `16kHz / mono / WAV` 最稳定。不同来源的 `m4a/mp3/aac` 编码差异很大，先统一格式能减少转写失败。

### MP3 和 M4A 为什么用不同转换工具？

MP3 可以用轻量的 `mp3_to_wav_minimp3` 快速转换；M4A/AAC/MP4 更适合用 `ffmpeg` 解码和重采样。

### 为什么加 `-ng`？

`-ng` 表示不用 GPU，避免 whisper.cpp 去找 Metal 资源文件。这样工具目录迁移后更稳定。

### 想更准怎么办？

可以换更大的多语言模型，例如 `small` 或 `medium`。模型越大通常越准，但转写速度更慢、文件体积也更大。
