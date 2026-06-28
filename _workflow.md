# 知识库自动更新工作流

> 本文件是完整的工作流说明书。任何 AI Agent 读到此文件，即可独立完成"发现新视频 → 全流程处理 → 入库"的全部操作。

---

## 前置条件

- 本仓库路径：当前目录（包含此文件的 git 仓库根目录）
- 配置文件：`_config.json`（数据源、分类规则）
- 视频清单：`_video_list.json`（已处理视频的基准列表）
- 系统依赖：Python 3.10+、ffmpeg、Chrome（已登录抖音）
- Python 依赖：requests、browser_cookie3、openai-whisper

### 依赖 Skill

本工作流依赖以下 2 个 CatPaw Agent Skill，均托管在 GitHub（`Fan-zexu`），安装到 `~/.catpaw/skills/` 目录即可被 Agent 自动识别。

| Skill 名称 | 用途 | 对应步骤 | GitHub 仓库 |
|------------|------|----------|-------------|
| `dy-subtitle-extractor-skill` | 抖音视频字幕提取（平台 AI 字幕 + Whisper 兜底） | Step 2 | [Fan-zexu/dy-subtitle-extractor-skill](https://github.com/Fan-zexu/dy-subtitle-extractor-skill) |
| `psychology-content-polish` | 心理学/成长类文字稿润色为结构化学习笔记 | Step 3 | [Fan-zexu/psychology-content-polish-skill](https://github.com/Fan-zexu/psychology-content-polish-skill) |

**安装方式**：

```bash
cd ~/.catpaw/skills
git clone git@github.com:Fan-zexu/dy-subtitle-extractor-skill.git
git clone git@github.com:Fan-zexu/psychology-content-polish-skill.git
```

**检查是否已安装**：确认 `~/.catpaw/skills/<skill-name>/SKILL.md` 文件存在即可。Agent 启动时会自动扫描该目录下所有包含 `SKILL.md` 的子目录作为可用技能。

---

## 工作流总览

```
Step 1: 发现新视频
Step 2: 提取字幕
Step 3: 润色文字稿
Step 4: 归档分类
Step 5: 同步到 GitHub
```

---

## Step 1: 发现新视频

**目标**：对比博主当前视频列表与 `_video_list.json`，找出尚未处理的新视频。

**操作步骤**：

1. 读取 `_config.json` 中的 `source.homepage` 获取博主主页链接
2. 使用 `dy-subtitle-extractor-skill` 的 `--list-only` 模式抓取博主当前所有视频列表：
   ```bash
   python3.12 <skill-dir>/scripts/douyin_subtitle_batch.py "<homepage_url>" -o <临时目录> --list-only
   ```
3. 读取 `_video_list.json` 中已有的 `aweme_id`
4. 对比策略：用 `aweme_id` 精确匹配，找出不在本地列表中的新视频
5. 过滤规则：
   - 跳过时长 < 15 秒的视频（通常是颁奖/感言等非内容型）
   - 其余视频全部处理（治愈果的内容均为心理学/成长相关，无需主题过滤）
6. 输出新增视频列表，包含：标题、aweme_id、时长
7. 如果没有新视频，流程结束

---

## Step 2: 提取字幕

**目标**：为每个新视频获取字幕文件（.md）。

**使用技能**：`dy-subtitle-extractor-skill`

**操作步骤**：

1. 对每个新视频，先尝试**策略 A**（平台 AI 字幕）：
   - 通过视频详情接口检查 `subtitleInfos` / `caption_infos` / `auto_captions`
   - 如有字幕，直接下载并转为 .srt + .md + .txt
2. 策略 A 失败时，执行**策略 B**（Whisper 本地转录）：
   - 下载视频 → ffmpeg 提取音频
   - 统一使用 `large` 模型（治愈果视频均 ≤ 12 分钟，large 模型保证心理学术语精度）
   - 执行转录，生成 .srt + .md + .txt

**命令参考**（单视频）：

```bash
python3.12 <dy-subtitle-extractor-skill>/scripts/douyin_subtitle_batch.py \
  "https://www.douyin.com/video/{aweme_id}" \
  -o <临时输出目录> \
  --max-count 1 \
  --whisper-model large
```

**输出文件**：

- `{视频标题}.md` — Markdown 带时间戳文字稿（主要使用）
- `{视频标题}.srt` — SRT 格式字幕文件
- `{视频标题}.txt` — 纯文本

---

## Step 3: 润色文字稿

**目标**：将口语化字幕整理为结构清晰、便于学习回顾的笔记。

**使用技能**：`psychology-content-polish`

**操作步骤**：

1. 读取 Step 2 产出的 `.md` 文件
2. 按照 `psychology-content-polish` skill 的完整流程处理：
   - **去噪清洗**：删除时间戳、视频元数据、底部纯文字稿区块、标题中的 #标签
   - **保留原话**：作者的用词、比喻、语气词、犀利表达、案例故事 —— 不改写不美化
   - **碎句合并**：将 Whisper 切碎的短句按语义完整性合并为自然段落
   - **结构化分章节**：按作者的"分享N点"逻辑分点分章节
   - **术语纠错**：仅修正明显的语音识别错字（心理学术语、人名尤其注意）
   - **金句提炼**：每篇 3-10 句，要有力量感和普适性
   - **引用参考**：整理提到的人物（标注身份）、书籍、理论/概念

3. 输出格式：

```markdown
# [简洁标题]

> [一句话概括核心主题或最有力的观点]

[开篇引入段落]

---

## 一、[第一个分点]

[合并后的自然段落...]

---

## 二、[第二个分点]

[...]

---

### 💎 本篇金句

- "金句1"
- "金句2"

### 📚 引用参考

- **人物名**（身份）
- **《书名》**
- **理论/概念名**
```

**质量检查**：
- 是否残留时间戳或元数据
- 术语是否正确
- 段落是否自然流畅
- 金句和引用是否完整

---

## Step 4: 归档分类

**目标**：将处理完的文件移入正确的分类目录。

**操作步骤**：

1. 读取 `_config.json` 中的 `classification.categories`
2. 根据视频标题和内容中的关键词，匹配最合适的分类
3. 匹配规则：
   - 统计每个分类的关键词在标题+内容中的命中次数
   - 选择命中最多的分类
   - 命中相同时，按 categories 数组顺序优先
   - 完全无法匹配时，归入 `📁 其他`
4. 在对应分类目录下创建子目录（以视频标题简称命名）
5. 将润色后的 `.md` 文件移入目标目录

**目录结构**：

```
治愈果/
├── 💕 亲密关系与恋爱/
│   ├── 不允许伴侣生气算霸凌吗/
│   │   └── 不允许伴侣生气算霸凌吗.md
│   └── ...
├── 🌱 情绪管理与心理健康/
│   ├── PTSD和EMDR严重创伤如何疗愈/
│   │   └── PTSD和EMDR严重创伤如何疗愈.md
│   └── ...
└── ...
```

**分类不确定时**：如果视频涉及多个主题，按"主要讲述内容"归类。

---

## Step 5: 同步到 GitHub

**目标**：将所有改动提交并推送到远程仓库。

**操作步骤**：

1. 更新 `_video_list.json`：
   - 将新抓取到的视频信息合并到已有列表
   - 保持按 `create_time` 倒序排列
2. 执行 git 操作：
   ```bash
   git add -A
   git commit -m "feat: 批量新增 {N} 个视频笔记"
   git push origin main
   ```

---

## 异常处理

| 场景 | 处理方式 |
|------|----------|
| 平台字幕和 Whisper 都失败 | 记录到 `_失败视频列表.md`，跳过后续步骤 |
| 视频已下架/私密 | 记录失败原因，跳过 |
| 无法确定分类 | 放入 `📁 其他` |
| git push 失败 | 保留本地 commit，输出错误信息供人工处理 |

---

## 快速启动指南

**最简使用方式**（给任何 Agent 的 prompt）：

```
请读取当前仓库根目录下的 _workflow.md、_config.json 和 _video_list.json，
按照工作流执行"发现新视频→字幕提取→润色→归档→同步"的完整流程。
```

**仅检查新视频**（不处理）：

```
读取 _config.json 和 _video_list.json，抓取博主最新视频列表，
对比后告诉我有哪些新视频，不需要执行后续处理。
```

**处理指定视频**：

```
按照 _workflow.md 的流程，处理以下视频：
https://www.douyin.com/video/7512019548389723446
```
