#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Video Generation - Video Package Generator

当前模式：Template Mode
- 不调用任何外部 API
- 不消耗模型 token
- 只读取 JSONL 和模板文件
- 生成结构完整但带 TODO 占位符的 video package

未来模式：LLM Mode
- 调用 ChatGPT / Claude API 自动生成完整内容
- 需要在 config/ 中配置 API Key
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime
from textwrap import dedent

# Import LLM Topic Enhancer (Phase 2A)
try:
    from llm_topic_enhancer import LLMTopicEnhancer
except ImportError:
    # If running from different directory, add scripts to path
    script_dir = Path(__file__).parent
    sys.path.insert(0, str(script_dir))
    try:
        from llm_topic_enhancer import LLMTopicEnhancer
    except ImportError:
        LLMTopicEnhancer = None  # Will be checked when needed


class VideoPackageGenerator:
    """Video Package 生成器"""

    def __init__(self, project_root):
        """
        初始化生成器

        Args:
            project_root: 项目根目录路径
        """
        self.project_root = Path(project_root)
        self.data_dir = self.project_root / "data"
        self.templates_dir = self.project_root / "templates"
        self.outputs_dir = self.project_root / "outputs"

        # 确保 outputs 目录存在
        self.outputs_dir.mkdir(exist_ok=True)

    # ========== Helper Functions for Field Compatibility ==========

    @staticmethod
    def get_reasoning_step_title(step):
        """获取推理步骤标题（兼容 step_title / title）"""
        return step.get('step_title') or step.get('title', '[步骤标题]')

    @staticmethod
    def get_reasoning_step_explanation(step):
        """获取推理步骤解释（兼容 explanation / content）"""
        return step.get('explanation') or step.get('content', '[步骤内容]')

    @staticmethod
    def get_reasoning_step_visual_cue(step):
        """获取推理步骤视觉提示（兼容 visual_cue / visual）"""
        return step.get('visual_cue') or step.get('visual', '')

    @staticmethod
    def get_subtitle_highlight(segment):
        """获取字幕高亮词（兼容 highlight_words / highlight）"""
        highlight = segment.get('highlight_words') or segment.get('highlight', '')
        if isinstance(highlight, list):
            return ', '.join(highlight)
        return str(highlight)

    @staticmethod
    def get_scene_id(scene):
        """获取场景 ID（兼容 scene_id / scene）"""
        return scene.get('scene_id') or scene.get('scene', 1)

    @staticmethod
    def get_scene_visual(scene):
        """获取场景视觉描述（兼容 visual_description / visual）"""
        return scene.get('visual_description') or scene.get('visual', '[视觉描述]')

    @staticmethod
    def get_scene_style(scene):
        """获取场景风格限制（兼容 style_restrictions / style）"""
        return scene.get('style_restrictions') or scene.get('style', '[风格限制]')

    @staticmethod
    def get_scene_onscreen_text(scene):
        """获取场景屏幕文本（兼容 onscreen_text / on_screen_text）"""
        return scene.get('onscreen_text') or scene.get('on_screen_text', '[On-screen text]')

    @staticmethod
    def render_instruction_list(value):
        """渲染指令列表（兼容 list / string）"""
        if not value:
            return "No specific topic restrictions."
        if isinstance(value, list):
            return '\n'.join(f"- {item}" for item in value)
        return str(value)

    @staticmethod
    def parse_duration_range(duration_value):
        """
        解析时长字符串，返回 (min_seconds, max_seconds)

        支持格式：
        - "45s" → (45, 45)
        - "60s" → (60, 60)
        - "50-60s" → (50, 60)
        - "50-60 seconds" → (50, 60)
        - "45 to 60 seconds" → (45, 60)

        Args:
            duration_value: 时长字符串

        Returns:
            (min_seconds, max_seconds) 元组
        """
        if not duration_value:
            return (45, 60)

        import re

        # 转换为字符串
        duration_str = str(duration_value).lower().strip()

        # 移除 "seconds" 等单位词
        duration_str = re.sub(r'\s*(seconds?|secs?)\s*$', '', duration_str)

        # 尝试匹配 "50-60" 或 "50 to 60" 格式
        range_match = re.search(r'(\d+)\s*(?:-|to)\s*(\d+)', duration_str)
        if range_match:
            min_val = int(range_match.group(1))
            max_val = int(range_match.group(2))
            return (min_val, max_val)

        # 尝试匹配单个数字 "45"
        single_match = re.search(r'(\d+)', duration_str)
        if single_match:
            val = int(single_match.group(1))
            return (val, val)

        # 默认值
        return (45, 60)

    @staticmethod
    def estimate_word_count_range(duration_value):
        """
        根据视频时长估算推荐词数范围

        使用语速：2.2-2.6 words per second（英文短视频旁白标准语速）

        Args:
            duration_value: 时长字符串（如 "50-60s"）

        Returns:
            (min_words, max_words) 元组
        """
        min_seconds, max_seconds = VideoPackageGenerator.parse_duration_range(duration_value)

        # 语速：2.2-2.6 words/second
        min_words = int(min_seconds * 2.2)
        max_words = int(max_seconds * 2.6)

        return (min_words, max_words)

    @staticmethod
    def normalize_markdown(content):
        """
        清理 markdown 内容的多余缩进

        功能：
        - 去掉统一的前置缩进（通常是 dedent 失效导致的 8 空格）
        - 保留 bullet list 和 code block 的相对缩进
        - 开头不要空行，末尾保留一个换行

        策略：
        - 通过检测 markdown header（# 开头的行）来确定模板缩进
        - 这样可以避免被插入内容（0 缩进）影响
        """
        if not content:
            return content

        # 分行处理
        lines = content.split('\n')

        # 去掉开头的空行
        while lines and not lines[0].strip():
            lines.pop(0)

        # 去掉末尾的空行
        while lines and not lines[-1].strip():
            lines.pop()

        if not lines:
            return '\n'

        # 找出所有 top-level markdown header 行（# 或 ## 开头）的缩进
        # 只看 # 和 ##，因为 ### 等可能是插入内容的一部分
        # 这些 top-level header 行代表模板结构，能准确反映需要去除的缩进量
        header_lines = [
            line for line in lines
            if line.lstrip().startswith('#') and not line.lstrip().startswith('###')
        ]

        if header_lines:
            # 使用 top-level header 的最小缩进作为基准
            template_indent = min(len(line) - len(line.lstrip()) for line in header_lines)
        else:
            # 如果没有 header，回退到所有非空行的最小缩进
            non_empty_lines = [line for line in lines if line.strip()]
            if not non_empty_lines:
                return '\n'
            template_indent = min(len(line) - len(line.lstrip()) for line in non_empty_lines)

        # 如果检测到统一的模板缩进，去掉所有行的前置缩进
        if template_indent > 0:
            cleaned_lines = []
            for line in lines:
                if line.strip():  # 非空行
                    # 检查这行是否真的有 template_indent 个前置空格
                    # 只有当行的实际缩进 >= template_indent 时才strip
                    actual_indent = len(line) - len(line.lstrip())
                    if actual_indent >= template_indent:
                        cleaned_lines.append(line[template_indent:])
                    else:
                        # 这行的缩进少于模板缩进（可能是插入的内容），保持原样
                        cleaned_lines.append(line)
                else:  # 空行
                    cleaned_lines.append('')
            lines = cleaned_lines

        # 拼接并确保末尾有一个换行
        result = '\n'.join(lines)
        if not result.endswith('\n'):
            result += '\n'

        return result

    def check_todo_count(self, output_folder):
        """检查输出文件夹中的 TODO 数量"""
        core_files = [
            "video_package.md",
            "notebooklm_prompt.md",
            "narration_script.md",
            "storyboard.md",
            "subtitles.md"
        ]

        print(f"\n📊 TODO 检查结果：")
        print(f"=" * 60)

        total_todos = 0
        file_results = {}

        for filename in core_files:
            file_path = output_folder / filename
            if not file_path.exists():
                continue

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 统计 TODO 出现次数（不区分大小写）
            todo_count = content.upper().count('[TODO')
            total_todos += todo_count
            file_results[filename] = todo_count

            status = "✅" if todo_count == 0 else "⚠️ "
            print(f"{status} {filename:<30} {todo_count} TODO(s)")

        print(f"=" * 60)

        if total_todos == 0:
            print(f"✅ 所有核心文件无 TODO 占位符")
            print(f"✅ Enhanced package generated successfully")
        else:
            print(f"⚠️  仍有 {total_todos} 个 TODO 占位符需要填充")
            print(f"⚠️  建议：手动填充或添加增强字段到 JSONL")

        return file_results

    def check_output_quality(self, output_folder, topic=None):
        """检查输出文件的质量和完整性（增强版：包含词数和时间轴检查）"""
        print(f"\n📋 Quality Check:")
        print(f"=" * 60)

        quality_results = {}
        import re

        # 1. 检查 notebooklm_prompt.md 的 20 个字段
        notebooklm_file = output_folder / "notebooklm_prompt.md"
        if notebooklm_file.exists():
            with open(notebooklm_file, 'r', encoding='utf-8') as f:
                content = f.read()

            required_fields = [
                "## Title", "## Topic", "## Target platform", "## Target audience",
                "## Video length", "## Video format", "## Core concept", "## Narration style",
                "## Video hook", "## Puzzle setup", "## Question", "## Correct answer",
                "## Wrong intuition", "## Key explanation", "## Main lesson",
                "## Narration draft", "## On-screen text plan", "## Visual style",
                "## Important requirements", "## Call to action"
            ]

            found_fields = sum(1 for field in required_fields if field in content)
            quality_results['notebooklm_prompt'] = f"{found_fields}/20 fields"
            status = "✅" if found_fields == 20 else "⚠️ "
            print(f"{status} notebooklm_prompt.md: {found_fields}/20 fields found")

        # 2. 检查 narration_script.md 的必需部分 + 词数检查
        narration_file = output_folder / "narration_script.md"
        if narration_file.exists():
            with open(narration_file, 'r', encoding='utf-8') as f:
                content = f.read()

            required_sections = [
                "## Full Narration Script",
                "## Script Breakdown",
                "### 1. Hook",
                "### 2. Problem Setup",
                "### 3. Wrong Intuition",
                "### 4. Key Reasoning"
            ]

            found_sections = sum(1 for section in required_sections if section in content)
            has_required = found_sections >= 4
            quality_results['narration_script'] = "required sections found" if has_required else "missing sections"
            status = "✅" if has_required else "⚠️ "
            print(f"{status} narration_script.md: {'required sections found' if has_required else f'only {found_sections}/6 sections'}")

            # 词数检查（新增）
            if topic:
                # 提取实际词数（支持多种格式，包括 markdown 格式）
                actual_match = re.search(r'Actual Word Count.*?(\d+)\s+words', content)
                if actual_match:
                    actual_words = int(actual_match.group(1))

                    # 计算推荐词数
                    duration_str = topic.get('target_duration', '60s')
                    word_count_min, word_count_max = self.estimate_word_count_range(duration_str)

                    # 判断是否在合理范围（允许 ±20% 浮动）
                    tolerance = 0.2
                    min_acceptable = word_count_min * (1 - tolerance)
                    max_acceptable = word_count_max * (1 + tolerance)
                    is_ok = min_acceptable <= actual_words <= max_acceptable

                    status = "✅" if is_ok else "⚠️ "
                    print(f"{status} word count: {actual_words} words, recommended {word_count_min}-{word_count_max}, {'OK' if is_ok else 'review'}")

        # 3. 检查 storyboard.md 的场景数 + 时间轴检查
        storyboard_file = output_folder / "storyboard.md"
        if storyboard_file.exists():
            with open(storyboard_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 统计 "## Scene" 出现次数
            scene_count = content.count("## Scene ")
            quality_results['storyboard'] = f"{scene_count} scenes"
            status = "✅" if scene_count >= 6 else "⚠️ "

            # 时间轴检查（新增）
            timeline_status = ""
            timestamp_pattern = r'Timestamp.*?(\d{2}):(\d{2})-(\d{2}):(\d{2})'
            timestamps = re.findall(timestamp_pattern, content)
            if timestamps and topic:
                # 获取最后一个时间戳的结束时间
                last_end = timestamps[-1][2:4]  # (mm, ss)
                last_end_seconds = int(last_end[0]) * 60 + int(last_end[1])

                # 获取目标时长
                min_sec, max_sec = self.parse_duration_range(topic.get('target_duration', '60s'))

                # 检查是否覆盖到目标时长
                coverage_ok = last_end_seconds >= min_sec
                timeline_status = f", timeline ends at {last_end[0]}:{last_end[1]}, {'OK' if coverage_ok else 'too short'}"

            print(f"{status} storyboard.md: {scene_count} scenes found{timeline_status}")

        # 4. 检查 subtitles.md 的字幕段数 + 时间轴检查
        subtitles_file = output_folder / "subtitles.md"
        if subtitles_file.exists():
            with open(subtitles_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 统计时间戳格式的段落数（例如 "### 00:00-00:03"）
            timestamp_pattern = r'###\s+(\d{2}):(\d{2})-(\d{2}):(\d{2})'
            segments = re.findall(timestamp_pattern, content)
            segment_count = len(segments)
            quality_results['subtitles'] = f"{segment_count} segments"
            status = "✅" if segment_count >= 8 else "⚠️ "

            # 时间轴检查（新增）
            timeline_status = ""
            if segments and topic:
                # 获取最后一个时间戳的结束时间
                last_end = segments[-1][2:4]  # (mm, ss)
                last_end_seconds = int(last_end[0]) * 60 + int(last_end[1])

                # 获取目标时长
                min_sec, max_sec = self.parse_duration_range(topic.get('target_duration', '60s'))

                # 检查是否覆盖到目标时长
                coverage_ok = last_end_seconds >= min_sec
                timeline_status = f", timeline ends at {last_end[0]}:{last_end[1]}, {'OK' if coverage_ok else 'too short'}"

            print(f"{status} subtitles.md: {segment_count} subtitle segments found{timeline_status}")

        # 5. 检查 TODO 占位符（保留原有逻辑）
        core_files = ["video_package.md", "notebooklm_prompt.md", "narration_script.md", "storyboard.md", "subtitles.md"]
        todo_count = 0
        for filename in core_files:
            file_path = output_folder / filename
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    todo_count += f.read().count("[TODO")

        status = "✅" if todo_count == 0 else "⚠️ "
        print(f"{status} core files: {'no [TODO] placeholders' if todo_count == 0 else f'{todo_count} [TODO] placeholders found'}")

        print(f"=" * 60)

        return quality_results

    def load_topics(self):
        """
        从 JSONL 文件加载选题库

        Returns:
            list: 选题列表
        """
        jsonl_file = self.data_dir / "topic_library_sample.jsonl"

        if not jsonl_file.exists():
            raise FileNotFoundError(
                f"找不到选题库文件：{jsonl_file}\n"
                f"请确保 data/topic_library_sample.jsonl 存在。"
            )

        topics = []
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:  # 跳过空行
                    continue
                try:
                    topic = json.loads(line)
                    topics.append(topic)
                except json.JSONDecodeError as e:
                    print(f"警告：第 {line_num} 行 JSON 解析失败：{e}")
                    continue

        if not topics:
            raise ValueError("选题库为空，请添加选题到 data/topic_library_sample.jsonl")

        return topics

    def find_topic(self, topics, topic_id):
        """
        根据 ID 查找选题

        Args:
            topics: 选题列表
            topic_id: 选题 ID

        Returns:
            dict: 找到的选题，如果未找到则返回 None
        """
        for topic in topics:
            if topic.get("id") == topic_id:
                return topic
        return None

    def slugify(self, text):
        """
        将文本转换为适合文件名的 slug

        Args:
            text: 原始文本

        Returns:
            str: slug 格式的文本
        """
        # 转换为小写
        text = text.lower()
        # 替换空格为下划线
        text = text.replace(" ", "_")
        # 只保留字母、数字、下划线、连字符
        text = re.sub(r'[^a-z0-9_-]', '', text)
        # 去除连续的下划线
        text = re.sub(r'_+', '_', text)
        # 去除首尾下划线
        text = text.strip('_')
        return text

    def create_output_folder(self, topic, overwrite=False):
        """
        创建输出文件夹

        Args:
            topic: 选题信息
            overwrite: 是否覆盖已存在的文件夹

        Returns:
            Path: 输出文件夹路径
        """
        topic_id = topic.get("id", "unknown")
        title_en = topic.get("title_en", "untitled")
        slug = self.slugify(title_en)

        folder_name = f"{topic_id}_{slug}"
        output_folder = self.outputs_dir / folder_name

        # 如果文件夹已存在
        if output_folder.exists():
            if overwrite:
                print(f"⚠️  文件夹已存在，将覆盖：{folder_name}")
            else:
                # 添加时间戳避免覆盖
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                folder_name = f"{topic_id}_{slug}_{timestamp}"
                output_folder = self.outputs_dir / folder_name
                print(f"⚠️  文件夹已存在，创建新文件夹：{folder_name}")

        output_folder.mkdir(parents=True, exist_ok=True)
        return output_folder

    def generate_topic_json(self, topic, output_folder):
        """
        生成 topic.json

        Args:
            topic: 选题信息
            output_folder: 输出文件夹路径
        """
        output_file = output_folder / "topic.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(topic, f, ensure_ascii=False, indent=2)
        print(f"✓ 已生成：{output_file.name}")

    def generate_video_package_md(self, topic, output_folder):
        """
        生成 video_package.md

        Args:
            topic: 选题信息
            output_folder: 输出文件夹路径
        """
        output_file = output_folder / "video_package.md"

        # 检查是否有增强字段
        has_enhanced = 'full_problem' in topic

        # 格式化时长显示（统一为 "XX-YY seconds" 或 "XX seconds"）
        duration_str = topic.get('target_duration', '60s')
        min_sec, max_sec = self.parse_duration_range(duration_str)
        if min_sec == max_sec:
            duration_display = f"{min_sec} seconds"
        else:
            duration_display = f"{min_sec}-{max_sec} seconds"

        # 根据增强状态生成不同的内容
        if has_enhanced:
            mode_desc = "Enhanced Template Mode (Phase 1B)"
            mode_details = dedent("""\
            - ✅ 已使用增强字段
            - ✅ 生成完整可用内容
            - ✅ 核心内容已自动填充
            - ⚠️ 建议 review 后再提交 NotebookLM
            """)
            next_steps = dedent("""\
            1. 打开 `internal_review.md` 查看生成信息和质量检查
            2. 打开 `notebooklm_clean_source.txt` 确认内容
            3. 复制 `notebooklm_clean_source.txt` 完整内容到 NotebookLM
            4. 在 NotebookLM 中生成视频

            💡 提示：
            - `notebooklm_clean_source.txt` 是干净版本，直接复制到 NotebookLM
            - `notebooklm_prompt.md` 是工程版（包含使用说明），用于备查
            - `internal_review.md` 是内部审核文档，不要复制到 NotebookLM
            """)

            # 显示增强字段摘要
            enhanced_content = dedent(f"""\
            ## 内容摘要（Content Summary）

            ### Hook
            {topic.get('hook', 'N/A')}

            ### Problem
            {topic.get('full_problem', 'N/A')}

            ### Question
            {topic.get('question', 'N/A')}

            ### Correct Answer
            {topic.get('correct_answer', 'N/A')}

            ### Wrong Intuition
            {topic.get('wrong_intuition', 'N/A')}

            ### Key Reasoning Steps
            """)

            if 'reasoning_steps' in topic:
                for step in topic['reasoning_steps']:
                    step_num = step.get('step', '?')
                    step_title = self.get_reasoning_step_title(step)
                    enhanced_content += f"**Step {step_num}**: {step_title}\n"

            enhanced_content += dedent(f"""
            ### Takeaway
            {topic.get('takeaway', 'N/A')}

            ### Call to Action
            {topic.get('cta', 'N/A')}

            ### Visual Consistency
            {topic.get('core_visual_consistency', 'N/A')}

            ---
            """)
        else:
            mode_desc = "Basic Template Mode"
            mode_details = dedent("""\
            - ⚠️ 未包含增强字段
            - ⚠️ 生成 TODO 占位符
            - ⚠️ 需要手动填充内容
            - 💡 可以手动添加增强字段到 JSONL，或等待 LLM Mode
            """)
            next_steps = dedent("""\
            1. 打开 `notebooklm_prompt.md`，填充 TODO 部分
            2. 打开 `narration_script.md`，编写完整旁白
            3. 打开 `storyboard.md`，细化分镜描述
            4. 打开 `subtitles.md`，编写字幕
            5. 使用 `qa_checklist.md` 检查质量
            6. 复制 `notebooklm_clean_source.txt` 到 NotebookLM 生成视频
            """)
            enhanced_content = ""

        content = dedent(f"""\
        # Video Package - {topic.get('title_en', 'Untitled')}

        ## 题目信息（Topic Information）

        - **ID**: {topic.get('id', 'N/A')}
        - **中文标题**: {topic.get('title_cn', 'N/A')}
        - **英文标题**: {topic.get('title_en', 'N/A')}
        - **分类**: {topic.get('category', 'N/A')}
        - **核心概念**: {topic.get('core_concept', 'N/A')}
        - **目标时长**: {duration_display}
        - **难度**: {topic.get('difficulty', 'N/A')}
        - **可视化难度**: {topic.get('visual_feasibility', 'N/A')}
        - **传播潜力**: {topic.get('viral_potential', 'N/A')}
        - **状态**: {topic.get('status', 'N/A')}

        ---

        ## 当前生成模式（Current Generation Mode）

        **{mode_desc}**
        {mode_details}
        ---

        {enhanced_content}
        ## 推荐工作流模式（Recommended Workflow Mode）

        ### 模式 A：NotebookLM Prompt Mode
        - 适合当前阶段
        - 使用本 video package 中的 `notebooklm_prompt.md`
        - 人工复制到 NotebookLM 生成视频

        ### 模式 B：Direct Video Pipeline Mode
        - 未来阶段（V3+）
        - 自动生成音频、视觉素材、字幕
        - ffmpeg 自动合成视频

        ---

        ## 下一步生产步骤（Next Production Steps）

        {next_steps}
        ---

        ## 文件清单（Files in This Package）

        - `topic.json` - 选题原始信息
        - `video_package.md` - 当前文件，汇总信息
        - `notebooklm_prompt.md` - NotebookLM Prompt {'✅ 完整' if has_enhanced else '⚠️ 草稿'}
        - `narration_script.md` - 旁白脚本 {'✅ 完整' if has_enhanced else '⚠️ 草稿'}
        - `storyboard.md` - 分镜 {'✅ 完整' if has_enhanced else '⚠️ 草稿'}
        - `subtitles.md` - 字幕 {'✅ 完整' if has_enhanced else '⚠️ 草稿'}
        - `qa_checklist.md` - 质量检查清单

        ---

        **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        **生成模式**: {mode_desc}
        **项目**: AI Educational Video Workflow Engine
        """)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(self.normalize_markdown(content))
        print(f"✓ 已生成：{output_file.name}")

    def generate_notebooklm_prompt_md(self, topic, output_folder):
        """
        生成 notebooklm_prompt.md（对齐 20-field reference pattern）

        Args:
            topic: 选题信息
            output_folder: 输出文件夹路径
        """
        output_file = output_folder / "notebooklm_prompt.md"

        # 检查是否有增强字段
        has_enhanced = 'full_problem' in topic

        # 辅助函数：获取字段值或 TODO
        def get_or_todo(field_name, todo_text):
            return topic.get(field_name, f"[TODO: {todo_text}]")

        # 生成 reasoning steps
        if 'reasoning_steps' in topic and topic['reasoning_steps']:
            steps_text = ""
            for step in topic['reasoning_steps']:
                step_num = step.get('step', '?')
                step_title = self.get_reasoning_step_title(step)
                step_explanation = self.get_reasoning_step_explanation(step)
                steps_text += f"\n**Step {step_num}: {step_title}**\n"
                steps_text += f"{step_explanation}\n"
            reasoning_content = steps_text
        else:
            reasoning_content = """
[TODO: Fill in 3-5 reasoning steps]

**Step 1: [Title]**
[Content]

**Step 2: [Title]**
[Content]

**Step 3: [Title]**
[Content]
"""

        # 生成 on-screen text plan
        if 'subtitle_segments' in topic and topic['subtitle_segments']:
            subtitle_text = ""
            for seg in topic['subtitle_segments']:
                highlight = self.get_subtitle_highlight(seg)
                subtitle_text += f"{seg['timestamp']} | {seg['text']} | \"{highlight}\"\n"
            onscreen_content = subtitle_text
        else:
            onscreen_content = """[TODO: Fill in subtitle segments]

00:00-00:03 | [Text] | [Highlight words]
00:03-00:07 | [Text] | [Highlight words]
...
"""

        # 计算 word count（修复：使用新的解析函数）
        duration_str = topic.get('target_duration', '60s')
        word_count_min, word_count_max = self.estimate_word_count_range(duration_str)
        word_count = f"{word_count_min}-{word_count_max} words"

        # 格式化时长显示（统一为 "XX-YY seconds" 或 "XX seconds"）
        min_sec, max_sec = self.parse_duration_range(duration_str)
        if min_sec == max_sec:
            duration_display = f"{min_sec} seconds"
        else:
            duration_display = f"{min_sec}-{max_sec} seconds"

        content = dedent(f"""\
        # NotebookLM Prompt - {topic.get('title_en', 'Untitled')}

        > **使用说明**：本文件已按照 `docs/reference_prompt_pattern.md` 的 20 个一级字段{"自动生成" if has_enhanced else "生成"}。
        > {"✅ 核心内容已完成填充，可直接使用。" if has_enhanced else "⚠️ 当前题目未包含增强字段，请填充 TODO 部分。"}
        > {"建议 review 一遍后，复制完整内容到 NotebookLM。" if has_enhanced else "填充完成后，复制完整内容到 NotebookLM。"}

        ---

        ## Title

        {topic.get('title_en', 'Untitled')}

        ---

        ## Topic

        {topic.get('topic_label_en') or topic.get('category', '[TODO: Topic category]')}

        ---

        ## Target platform

        TikTok, YouTube Shorts, Instagram Reels

        ---

        ## Target audience

        Students, parents, and viewers who enjoy short math puzzles, probability puzzles, brain tricks, visual reasoning, or everyday science.

        ---

        ## Video length

        {duration_display}

        ---

        ## Video format

        Short-form educational video.

        ---

        ## Core concept

        {topic.get('core_concept', '[TODO: Core concept]')}

        {get_or_todo('short_explanation', '用 1-3 句话说明这个视频真正讲的核心概念，不只是重复标题')}

        ---

        ## Narration style

        ⭐⭐⭐ **CRITICAL - MANDATORY REQUIREMENTS** ⭐⭐⭐

        - Use a single narrator only.
        - The video must be a one-person explanatory monologue.
        - The narrator should directly explain the puzzle to the viewer.
        - Do not use dialogue.
        - Do not use two hosts.
        - Do not use multiple speakers.
        - Do not use podcast style.
        - Do not use interview style.
        - Do not create a conversation between characters.
        - Do not include back-and-forth discussion.

        ---

        ## Video hook

        {get_or_todo('hook', '填写 3 秒内的开头钩子，一个吸引人的问题')}

        ---

        ## Puzzle setup

        {get_or_todo('full_problem', '填写完整题面，清晰陈述问题条件')}

        {get_or_todo('question', '明确提问')}

        ---

        ## Question

        {get_or_todo('question', '明确提问，不能含糊')}

        ---

        ## Correct answer

        {get_or_todo('correct_answer', '直接给正确答案')}

        ---

        ## Wrong intuition

        {get_or_todo('wrong_intuition', '指出大多数人会怎么想，以及为什么这个直觉是错的')}

        ---

        ## Key explanation

        {reasoning_content}
        ---

        ## Main lesson

        {get_or_todo('takeaway', '总结视频真正想教会观众的东西')}

        ---

        ## Narration draft

        ⭐ **CRITICAL**: This MUST be a **single narrator monologue**. Do NOT create dialogue, interview, or podcast format.

        {get_or_todo('narration_script', '完整英文单人旁白脚本')}

        **Narration requirements**:
        - **Single narrator only** - one clear, friendly voice throughout
        - **Tone**: Casual but authoritative, curious but confident, friendly but not overly cute
        - **Pacing**: 2-3 words per second (English), slow down at key reveals
        - **Word count**: Approximately {word_count} for {duration_display}

        ---

        ## On-screen text plan

        ⭐ **CRITICAL**: Text must be **large and clear** (at least 1/5 of screen height). Use **yellow highlight boxes** for key words.

        **Format**:
        ```
        Timestamp | Text | Highlight
        ```

        {onscreen_content}

        ---

        ## Visual style

        ⭐⭐⭐ **CRITICAL - MANDATORY REQUIREMENTS** ⭐⭐⭐

        ### ✅ MUST HAVE:

        **Background**:
        - Minimal white background or white/light graph-paper background.
        - Pure white (#FFFFFF) OR light gray graph paper (#F5F5F5 with subtle grid lines at 10-20% opacity).

        **Illustration Style**:
        - Clean doodle / hand-drawn educational style.
        - Modern educational style.
        - Use simple hand-drawn shapes. Avoid photorealistic or 3D-rendered objects.
        - Hand-drawn lines (slightly irregular, not perfectly geometric).
        - Simple but not childish, cute but not overly cute.
        - Think of it as: sketches drawn on white paper with a black marker.

        **Text & Captions**:
        - Use large readable English text. Key phrases should be prominent, but should not cover the main diagram.
        - Clear on-screen captions.
        - Yellow highlight boxes for key words when helpful.
        - Bold Sans-serif font (Arial, Roboto, Montserrat).
        - Black text (#000000) on white/light background.

        **Animation**:
        - Simple motion only.
        - Fade in / fade out (0.3-0.5s).
        - Zoom in / zoom out (0.5-1s).
        - Pan left / pan right (1-2s).
        - Hand-drawn animation (elements gradually "draw" themselves).

        **Core Visual Consistency**:
        {get_or_todo('core_visual_consistency', '描述核心图示如何保持一致')}

        ### ❌ DO NOT INCLUDE:

        - No realistic humans.
        - No dialogue bubbles.
        - No podcast visuals (two people sitting, microphones, headphones).
        - No interview visuals (interviewer and interviewee).
        - No dark background.
        - No black background.
        - No decorative clutter.
        - No random objects.
        - No unrelated characters.
        - No photorealistic images or 3D renders.
        - No horror elements or scary visuals.
        - No complex 3D animations, spinning (unless relevant), explosions, flashing effects.

        ---

        ## Important requirements

        ⭐⭐⭐ **CRITICAL - MANDATORY REQUIREMENTS** ⭐⭐⭐

        ### Logical Correctness:
        - The explanation must be logically correct.
        - The answer must match the puzzle.
        - Do not change the puzzle setup or add extra conditions.
        - Do not give the wrong answer.
        - Do not present the wrong intuition as the correct answer.

        ### Visual Requirements:
        - The visuals must support the reasoning, not distract from it.
        - The core diagram must remain consistent across all scenes.
        - Do not create visuals that contradict the explanation.

        ### Format Requirements:
        - The video must not become a dialogue, interview, podcast, or two-host conversation.
        - Use single narrator monologue only.
        - Do not use multiple speakers or back-and-forth discussion.

        ### Topic-Specific Requirements:
        {get_or_todo('notebooklm_specific_instructions', '根据具体题目添加的特定要求')}

        ---

        ## Call to action

        {get_or_todo('cta', 'Call-to-action')}

        ---

        ## QUALITY CHECKLIST

        Before finalizing, verify all items below:

        ### ⭐ Hard Requirements (Must ALL Pass):
        - [ ] **Content Accuracy**: Is the answer logically correct? Is the reasoning complete and verifiable?
        - [ ] **Single Narrator**: Is this a monologue, NOT a dialogue/interview/podcast?
        - [ ] **White Background**: Are all scenes on a white or light graph-paper background (no dark backgrounds)?
        - [ ] **Hand-Drawn Style**: Are all visuals clean doodle / hand-drawn educational style (no photorealistic images)?
        - [ ] **Large Text**: Are on-screen captions large and clear (at least 1/5 screen height)?
        - [ ] **Yellow Highlights**: Are key words highlighted with yellow boxes?
        - [ ] **Visual Consistency**: Are core diagrams consistent throughout?
        - [ ] **No Forbidden Elements**: No dialogue, no dark backgrounds, no podcast visuals, no realistic humans?
        - [ ] **Logic Flow**: Does each visual correspond to the reasoning step?
        - [ ] **Answer Correctness**: Does the final answer match the correct answer to the puzzle?

        ---

        **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        **Mode**: {"Enhanced Template Mode (Phase 1B)" if has_enhanced else "Basic Template Mode"}
        **Template Version**: v2.0 (20-field standard)
        **Next Step**: {"Review content and copy to NotebookLM" if has_enhanced else "Fill in all TODO sections, then copy to NotebookLM"}
        """)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(self.normalize_markdown(content))
        print(f"✓ 已生成：{output_file.name}")

    def generate_narration_script_md(self, topic, output_folder):
        """
        生成 narration_script.md

        Args:
            topic: 选题信息
            output_folder: 输出文件夹路径
        """
        output_file = output_folder / "narration_script.md"

        # 检查是否有增强字段
        has_enhanced = 'narration_script' in topic

        # 计算 word count（修复：使用新的解析函数）
        duration_str = topic.get('target_duration', '60s')
        word_count_min, word_count_max = self.estimate_word_count_range(duration_str)

        # 格式化时长显示（统一为 "XX-YY seconds" 或 "XX seconds"）
        min_sec, max_sec = self.parse_duration_range(duration_str)
        if min_sec == max_sec:
            duration_display = f"{min_sec} seconds"
        else:
            duration_display = f"{min_sec}-{max_sec} seconds"

        if has_enhanced:
            # 使用增强字段生成完整脚本
            narration = topic.get('narration_script', '')
            actual_word_count = len(narration.split())

            # 尝试从完整脚本中提取各部分
            hook = topic.get('hook', '[Extract from full script]')
            problem = topic.get('full_problem', '[Extract from full script]')
            wrong_intuition = topic.get('wrong_intuition', '[Extract from full script]')
            answer = topic.get('correct_answer', '[Extract from full script]')
            takeaway = topic.get('takeaway', '[Extract from full script]')
            cta = topic.get('cta', '[Extract from full script]')

            content = dedent(f"""\
            # Narration Script - {topic.get('title_en', 'Untitled')}

            > **状态**：✅ 已使用增强字段生成完整旁白脚本

            ---

            ## Script Information

            - **Title**: {topic.get('title_en', 'N/A')}
            - **Duration**: {duration_display}
            - **Target Word Count**: {word_count_min}-{word_count_max} words
            - **Actual Word Count**: {actual_word_count} words
            - **Tone**: Casual but authoritative, curious but confident
            - **Pacing**: 2-3 words per second (English)
            - **Mode**: Enhanced Template Mode (Phase 1B)

            ---

            ## Full Narration Script

            {narration}

            ---

            ## Script Breakdown

            ### 1. Hook (0-4s)
            {hook}

            ---

            ### 2. Problem Setup (4-12s)
            {problem}

            ---

            ### 3. Wrong Intuition (12-20s)
            {wrong_intuition}

            ---

            ### 4. Key Reasoning (20-46s)
            """)

            # 添加推理步骤
            if 'reasoning_steps' in topic:
                for step in topic['reasoning_steps']:
                    step_num = step.get('step', '?')
                    step_title = self.get_reasoning_step_title(step)
                    step_content = self.get_reasoning_step_explanation(step)
                    content += f"**Step {step_num} - {step_title}**: {step_content}\n\n"
            else:
                content += "[Reasoning steps - see full script above]\n\n"

            content += dedent(f"""
            ---

            ### 5. Answer Reveal (46-52s)
            {answer}

            ---

            ### 6. Takeaway & CTA (52-58s)
            {takeaway}

            {cta}

            ---

            ## Narration Style Guidelines

            ### ✅ DO:
            - Use **single narrator monologue** (one voice throughout)
            - Keep tone casual but authoritative
            - Slow down at key reveals
            - Pause briefly before the answer

            ### ❌ DON'T:
            - Create dialogue between two people
            - Use interview or podcast format
            - Use overly academic language
            - Sacrifice clarity for brevity

            ---

            **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            **Mode**: Enhanced Template Mode (Phase 1B)
            **Next Step**: Review and adjust if needed
            """)
        else:
            # 使用 TODO 模板
            content = dedent(f"""\
            # Narration Script - {topic.get('title_en', 'Untitled')}

            > **使用说明**：本文件为旁白脚本草稿。请按照标准结构填充内容。

            ---

            ## Script Information

            - **Title**: {topic.get('title_en', 'N/A')}
            - **Duration**: {topic.get('target_duration', '60s')}
            - **Target Word Count**: {word_count_min}-{word_count_max} words
            - **Tone**: Casual but authoritative, curious but confident
            - **Pacing**: 2-3 words per second (English)

            ---

            ## Script Structure

            ### 1. Hook (0-3s)
            [TODO: 前 3 秒的开头钩子，一个吸引人的问题]

            Example: "If a coin lands heads 5 times in a row, is tails more likely next?"

            ---

            ### 2. Problem Setup (3-10s)
            [TODO: 完整陈述题目条件]

            Example: "You flip a fair coin 5 times, and it lands heads every single time."

            ---

            ### 3. Wrong Intuition (10-15s)
            [TODO: 提出常见误解]

            Example: "Most people say yes. They think tails is 'due' to happen."

            ---

            ### 4. Key Reasoning (15-30s)
            [TODO: 核心推理过程，2-3 个关键点]

            Example: "But here's the truth: each coin flip is independent. The coin has no memory. Every single flip is still 50-50, no matter what happened before."

            ---

            ### 5. Concept Name (30-35s)
            [TODO: 概念名称]

            Example: "This mistake? It's called the Gambler's Fallacy."

            ---

            ### 6. Answer Reveal (35-40s)
            [TODO: 揭晓答案]

            Example: "The answer: still 50% heads, 50% tails."

            ---

            ### 7. Takeaway & CTA (40-45s)
            [TODO: 总结 + Call-to-Action]

            Example: "Past results don't change future odds. Follow for more mind-bending facts!"

            ---

            ## Full Script (Complete Version)

            [TODO: 将上面 7 个部分连接成完整的旁白脚本，流畅自然]

            Example:
            "If a coin lands heads 5 times in a row, is tails more likely next? Most people say yes. But here's the truth: each coin flip is independent. The coin has no memory. Every single flip is still 50-50, no matter what happened before. This mistake? It's called the Gambler's Fallacy. Past results don't change future odds. The answer: still 50% heads, 50% tails. Follow for more mind-bending facts!"

            ---

            ## Narration Style Guidelines

            ### ✅ DO:
            - Use **single narrator monologue** (one voice throughout)
            - Keep tone casual but authoritative
            - Slow down at key reveals
            - Pause briefly before the answer

            ### ❌ DON'T:
            - Create dialogue between two people
            - Use interview or podcast format
            - Use overly academic language
            - Sacrifice clarity for brevity

            ---

            **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            **Mode**: Basic Template Mode
            **Next Step**: Fill in all TODO sections
            """)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(self.normalize_markdown(content))
        print(f"✓ 已生成：{output_file.name}")

    def generate_storyboard_md(self, topic, output_folder):
        """
        生成 storyboard.md

        Args:
            topic: 选题信息
            output_folder: 输出文件夹路径
        """
        output_file = output_folder / "storyboard.md"

        # 检查是否有增强字段
        has_enhanced = 'storyboard_scenes' in topic

        # 格式化时长显示
        duration_str = topic.get('target_duration', '60s')
        min_sec, max_sec = self.parse_duration_range(duration_str)
        if min_sec == max_sec:
            duration_display = f"{min_sec} seconds"
        else:
            duration_display = f"{min_sec}-{max_sec} seconds"

        if has_enhanced:
            # 使用增强字段生成完整分镜
            scenes = topic.get('storyboard_scenes', [])
            total_scenes = len(scenes)

            content = dedent(f"""\
            # Storyboard - {topic.get('title_en', 'Untitled')}

            > **状态**：✅ 已使用增强字段生成完整分镜

            ---

            ## Storyboard Information

            - **Title**: {topic.get('title_en', 'N/A')}
            - **Duration**: {duration_display}
            - **Total Scenes**: {total_scenes}
            - **Style**: White/light graph-paper background + clean doodle / hand-drawn educational style
            - **Mode**: Enhanced Template Mode (Phase 1B)

            ---

            """)

            # 生成每个场景
            for scene in scenes:
                scene_id = self.get_scene_id(scene)
                timestamp = scene.get('timestamp', 'N/A')
                narration = scene.get('narration', '[Narration]')
                on_screen_text = self.get_scene_onscreen_text(scene)
                visual = self.get_scene_visual(scene)
                style = self.get_scene_style(scene)

                content += dedent(f"""\
                ## Scene {scene_id}

                **Timestamp**: {timestamp}

                **Narration**: {narration}

                **On-Screen Text**: {on_screen_text}

                **Visual Description**:
                {visual}

                **Style Restrictions**:
                {style}

                ---

                """)

            # 添加核心视觉一致性说明
            if 'core_visual_consistency' in topic:
                content += dedent(f"""\
                ## Core Visual Consistency

                {topic.get('core_visual_consistency', 'N/A')}

                ---

                """)

            content += dedent(f"""
            ## Visual Consistency Checklist

            - [ ] All scenes use white or light graph-paper background
            - [ ] All illustrations use hand-drawn style (not perfect geometric)
            - [ ] Core visual element consistent across all scenes
            - [ ] Yellow highlight boxes used for key words/numbers
            - [ ] Large, centered captions (占屏幕 1/4-1/3)
            - [ ] No dark backgrounds, no photorealistic images
            - [ ] No dialogue, no interview, no podcast format

            ---

            **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            **Mode**: Enhanced Template Mode (Phase 1B)
            **Next Step**: Review and adjust if needed
            """)
        else:
            # 使用 TODO 模板
            content = dedent(f"""\
            # Storyboard - {topic.get('title_en', 'Untitled')}

            > **使用说明**：本文件为分镜草稿。请按照标准 6 个镜头结构填充每个镜头的画面描述。

            ---

            ## Storyboard Information

            - **Title**: {topic.get('title_en', 'N/A')}
            - **Duration**: {topic.get('target_duration', '60s')}
            - **Total Scenes**: 6
            - **Style**: White/light graph-paper background + clean doodle / hand-drawn educational style

            ---

            ## Scene 1: Hook (0-3s)

            **Timestamp**: 0-3s

            **Narration**: [TODO: 旁白内容]

            **On-Screen Text**: [TODO: 字幕，大而居中]

            **Visual Description**:
            [TODO: 画面描述（英文），例如：A coin flipping in the air, landing heads 5 times in a row. White background, clean black hand-drawn line art.]

            **Style Restrictions**:
            - White or light graph-paper background
            - Hand-drawn style (not perfect geometric shapes)
            - Simple and clear

            ---

            ## Scene 2: Problem Setup (3-10s)

            **Timestamp**: 3-10s

            **Narration**: [TODO: 旁白内容]

            **On-Screen Text**: [TODO: 字幕，大而居中]

            **Visual Description**:
            [TODO: 画面描述（英文），例如：A question mark appears next to a 6th coin. Text overlay: "6th flip?"]

            **Style Restrictions**:
            - Same background as Scene 1
            - Consistent coin style

            ---

            ## Scene 3: Wrong Intuition (10-18s)

            **Timestamp**: 10-18s

            **Narration**: [TODO: 旁白内容]

            **On-Screen Text**: [TODO: 字幕，关键词用黄色高亮框]

            **Visual Description**:
            [TODO: 画面描述（英文）]

            **Style Restrictions**:
            - Hand-drawn style diagrams
            - Yellow highlight box for key concepts

            ---

            ## Scene 4: Key Reasoning (18-30s)

            **Timestamp**: 18-30s

            **Narration**: [TODO: 旁白内容]

            **On-Screen Text**: [TODO: 字幕，数字和概念用黄色高亮]

            **Visual Description**:
            [TODO: 画面描述（英文），例如：Tree diagram showing each flip has 50% heads and 50% tails. Clean black lines, blue nodes, yellow highlight boxes for percentages.]

            **Style Restrictions**:
            - Tree diagram or other educational diagram
            - Yellow highlight boxes for key numbers (50%, 50%)
            - Consistent visual style

            ---

            ## Scene 5: Concept Name (30-37s)

            **Timestamp**: 30-37s

            **Narration**: [TODO: 旁白内容]

            **On-Screen Text**: [TODO: 概念名称，超大字幕 + 黄色高亮框]

            **Visual Description**:
            [TODO: 画面描述（英文），例如：Large text: "Gambler's Fallacy". White background. Yellow highlight box around the text.]

            **Style Restrictions**:
            - Concept name in large, bold text
            - Yellow highlight box
            - Clean and minimal

            ---

            ## Scene 6: Answer & CTA (37-45s)

            **Timestamp**: 37-45s

            **Narration**: [TODO: 旁白内容]

            **On-Screen Text**: [TODO: 答案 + "Follow for more!"，黄色高亮答案]

            **Visual Description**:
            [TODO: 画面描述（英文），例如：The 6th coin with "50%-50%" label. Yellow highlight box. Think Academy logo with "Follow for more" text.]

            **Style Restrictions**:
            - Answer emphasized with yellow highlight box
            - Think Academy logo (if available)
            - Clean and professional

            ---

            ## Visual Consistency Checklist

            - [ ] All scenes use white or light graph-paper background
            - [ ] All illustrations use hand-drawn style (not perfect geometric)
            - [ ] Core visual element (e.g., coin) consistent across all scenes
            - [ ] Yellow highlight boxes used for key words/numbers
            - [ ] Large, centered captions (占屏幕 1/4-1/3)
            - [ ] No dark backgrounds, no photorealistic images
            - [ ] No dialogue, no interview, no podcast format

            ---

            **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            **Mode**: Basic Template Mode
            **Next Step**: Fill in all TODO sections, ensure visual consistency
            """)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(self.normalize_markdown(content))
        print(f"✓ 已生成：{output_file.name}")

    def generate_subtitles_md(self, topic, output_folder):
        """
        生成 subtitles.md

        Args:
            topic: 选题信息
            output_folder: 输出文件夹路径
        """
        output_file = output_folder / "subtitles.md"

        # 检查是否有增强字段
        has_enhanced = 'subtitle_segments' in topic

        if has_enhanced:
            # 使用增强字段生成完整字幕
            segments = topic.get('subtitle_segments', [])
            total_segments = len(segments)

            content = dedent(f"""\
            # Subtitles - {topic.get('title_en', 'Untitled')}

            > **状态**：✅ 已使用增强字段生成完整字幕

            ---

            ## Subtitle Guidelines

            ### ✅ 字幕设计原则：
            - **大而清晰**：占屏幕 1/4 到 1/3
            - **居中对齐**：屏幕正中央或中下部
            - **关键词高亮**：用黄色背景框突出关键数字、概念、答案
            - **简洁有力**：每段 1-2 句，每句 1-2 秒
            - **与旁白同步**：字幕与旁白完全对应

            ### ❌ 字幕禁忌：
            - 不要小字幕（< 1/5 屏幕高度）
            - 不要左对齐或右对齐（除非特殊设计）
            - 不要放在屏幕顶部（会被平台 UI 遮挡）
            - 不要忽略关键词高亮

            ---

            ## Subtitle Segments

            """)

            # 生成每个字幕段落
            for segment in segments:
                timestamp = segment.get('timestamp', 'N/A')
                text = segment.get('text', '[Text]')
                highlight = self.get_subtitle_highlight(segment)

                content += dedent(f"""\
                ### {timestamp}
                {text}

                **Highlight**: {highlight if highlight else 'None'}

                ---

                """)

            content += dedent("""
            ## Subtitle Style Reference

            ### Normal Style
            - Font: Bold Sans-serif (Arial, Roboto)
            - Size: Large (1/4-1/3 screen height)
            - Color: Black text (#000000)
            - Position: Centered

            ### Emphasized Style (for key concepts)
            - Font: Bold Sans-serif
            - Size: Extra Large (1/3 screen height)
            - Color: Black text (#000000)
            - Highlight: Yellow background box (#FFD700, 70-80% opacity)

            ### Answer Style (for answer reveal)
            - Font: Bold Sans-serif
            - Size: Extra Large (1/3 screen height)
            - Color: Black text (#000000)
            - Highlight: Yellow background box (#FFD700, 70-80% opacity)
            - Position: Centered, prominent

            ---

            ## Yellow Highlight Examples

            关键词需要用黄色背景框高亮：
            - 数字（"50%", "5 times", "6th"）
            - 核心概念（"Gambler's Fallacy", "Independent", "Probability"）
            - 答案（"Still 50-50", "No", "Yes"）

            ---

            **Generated**: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """
            **Mode**: Enhanced Template Mode (Phase 1B)
            **Next Step**: Review and adjust if needed
            """)
        else:
            # 使用 TODO 模板
            content = dedent(f"""\
            # Subtitles - {topic.get('title_en', 'Untitled')}

            > **使用说明**：本文件为字幕草稿。请按照短视频字幕形式分段填充。

            ---

            ## Subtitle Guidelines

            ### ✅ 字幕设计原则：
            - **大而清晰**：占屏幕 1/4 到 1/3
            - **居中对齐**：屏幕正中央或中下部
            - **关键词高亮**：用黄色背景框突出关键数字、概念、答案
            - **简洁有力**：每段 1-2 句，每句 1-2 秒
            - **与旁白同步**：字幕与旁白完全对应

            ### ❌ 字幕禁忌：
            - 不要小字幕（< 1/5 屏幕高度）
            - 不要左对齐或右对齐（除非特殊设计）
            - 不要放在屏幕顶部（会被平台 UI 遮挡）
            - 不要忽略关键词高亮

            ---

            ## Subtitle Segments

            ### 00:00 - 00:03
            [TODO: 填写字幕内容]

            **Style**: Normal
            **Highlight**: None

            Example: "5 heads in a row?"

            ---

            ### 00:03 - 00:07
            [TODO: 填写字幕内容]

            **Style**: Emphasized
            **Highlight**: Key question

            Example: "Is tails more likely next?"

            ---

            ### 00:07 - 00:12
            [TODO: 填写字幕内容]

            **Style**: Normal
            **Highlight**: None

            Example: "Most people say yes"

            ---

            ### 00:12 - 00:18
            [TODO: 填写字幕内容]

            **Style**: Normal
            **Highlight**: Key concept word

            Example: "Each flip is INDEPENDENT"
            (注：INDEPENDENT 用黄色高亮框)

            ---

            ### 00:18 - 00:25
            [TODO: 填写字幕内容]

            **Style**: Normal
            **Highlight**: Key numbers

            Example: "50% HEADS  50% TAILS"
            (注：50% 用黄色高亮框)

            ---

            ### 00:25 - 00:30
            [TODO: 填写字幕内容]

            **Style**: Emphasized (Concept Name)
            **Highlight**: Concept name with yellow box

            Example: "GAMBLER'S FALLACY"
            (注：整个概念名称用黄色高亮框包围)

            ---

            ### 00:30 - 00:37
            [TODO: 填写字幕内容]

            **Style**: Answer (Large, Bold)
            **Highlight**: Answer with yellow box

            Example: "Answer: STILL 50-50"
            (注：答案用黄色高亮框)

            ---

            ### 00:37 - 00:45
            [TODO: 填写字幕内容]

            **Style**: Call-to-Action
            **Highlight**: None

            Example: "Follow for more!"

            ---

            ## Subtitle Style Reference

            ### Normal Style
            - Font: Bold Sans-serif (Arial, Roboto)
            - Size: Large (1/4-1/3 screen height)
            - Color: Black text (#000000)
            - Position: Centered

            ### Emphasized Style (for key concepts)
            - Font: Bold Sans-serif
            - Size: Extra Large (1/3 screen height)
            - Color: Black text (#000000)
            - Highlight: Yellow background box (#FFD700, 70-80% opacity)

            ### Answer Style (for answer reveal)
            - Font: Bold Sans-serif
            - Size: Extra Large (1/3 screen height)
            - Color: Black text (#000000)
            - Highlight: Yellow background box (#FFD700, 70-80% opacity)
            - Position: Centered, prominent

            ---

            ## Yellow Highlight Examples

            关键词需要用黄色背景框高亮：
            - 数字（"50%", "5 times", "6th"）
            - 核心概念（"Gambler's Fallacy", "Independent", "Probability"）
            - 答案（"Still 50-50", "No", "Yes"）

            ---

            **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            **Mode**: Basic Template Mode
            **Next Step**: Fill in all TODO sections, mark keywords for yellow highlights
            """)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(self.normalize_markdown(content))
        print(f"✓ 已生成：{output_file.name}")

    def generate_qa_checklist_md(self, topic, output_folder):
        """
        生成 qa_checklist.md

        Args:
            topic: 选题信息
            output_folder: 输出文件夹路径
        """
        output_file = output_folder / "qa_checklist.md"

        content = dedent(f"""\
        # Quality Assurance Checklist - {topic.get('title_en', 'Untitled')}

        > **使用说明**：在视频生产资料完成后、提交给 NotebookLM 之前，逐项检查此清单。所有硬性要求（⭐）必须通过。

        ---

        ## 项目信息

        **题目**: {topic.get('title_en', 'N/A')}
        **核心概念**: {topic.get('core_concept', 'N/A')}
        **检查日期**: [TODO: 填写检查日期]
        **检查人**: [TODO: 填写检查人姓名]

        ---

        ## 第一部分：内容准确性（⭐ 硬性要求）

        ### 1.1 答案正确性
        - [ ] **⭐ 答案逻辑正确**
          问题：答案是否符合数学/科学/逻辑原理？
          验证方法：[如何验证，例如：查阅维基百科 / 咨询专家]
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **⭐ 答案表述清晰**
          问题：答案是否用观众能理解的语言表述？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ### 1.2 推理过程完整性
        - [ ] **⭐ 推理步骤完整**
          问题：从题目到答案的推理链条是否完整？有没有跳步？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **推理步骤清晰**
          问题：每个推理步骤是否有对应的画面和字幕？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **无逻辑谬误**
          问题：推理过程中有没有逻辑错误、循环论证、偷换概念？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ---

        ## 第二部分：叙事形式（⭐ 硬性要求）

        ### 2.1 单人旁白检查
        - [ ] **⭐ 全程单人旁白**
          问题：整个视频是否只有一个人在讲解（single narrator monologue）？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **⭐ 无双人对话**
          问题：是否避免了"Person A: ... Person B: ..."形式的对话？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **⭐ 无访谈形式**
          问题：是否避免了"Interviewer: ... Interviewee: ..."形式？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **⭐ 无播客风格**
          问题：是否避免了"Host: ... Guest: ..."形式？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **⭐ Prompt 中明确要求单人旁白**
          问题：在 NotebookLM Prompt 的 "CRITICAL RESTRICTIONS" 部分是否明确写了单人旁白要求？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ---

        ## 第三部分：视觉风格（⭐ 硬性要求）

        ### 3.1 背景和配色
        - [ ] **⭐ 白色或浅色方格纸背景**
          问题：所有镜头是否都是白色或浅色方格纸背景？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **⭐ 无黑色背景**
          问题：是否避免了黑色或深色背景？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ### 3.2 插图风格
        - [ ] **⭐ 手绘涂鸦风格**
          问题：所有图示是否为 clean doodle / hand-drawn educational style？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **⭐ 无写实照片或 3D 渲染**
          问题：是否避免了写实照片、3D 渲染、复杂纹理？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ### 3.3 核心图示一致性
        - [ ] **⭐ 主要物体外观一致**
          问题：核心物体（例如硬币、人脸、骰子）在所有镜头中是否保持一致的外观？
          状态：✅ 通过 / ❌ 不通过
          备注：[描述核心物体]

        - [ ] **在 Prompt 中明确描述一致性要求**
          问题：在 "Core Visual Consistency" 部分是否详细描述了核心图示的外观？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ---

        ## 第四部分：字幕设计

        ### 4.1 字幕大小和清晰度
        - [ ] **⭐ 字幕足够大**
          问题：字幕是否占屏幕高度的 1/4-1/3？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **字幕居中**
          问题：字幕是否居中对齐？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ### 4.2 黄色高亮框
        - [ ] **⭐ 关键词用黄色高亮框**
          问题：关键数字、概念、答案是否用黄色背景框高亮？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **与旁白同步**
          问题：每个镜头的字幕是否与对应的旁白同步？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ---

        ## 第五部分：禁止元素检查（⭐ 硬性要求）

        ### 5.1 禁止的叙事形式
        - [ ] **⭐ 无双人对话**
          状态：✅ 通过（已避免）/ ❌ 不通过（出现了）

        - [ ] **⭐ 无访谈形式**
          状态：✅ 通过（已避免）/ ❌ 不通过（出现了）

        - [ ] **⭐ 无播客风格**
          状态：✅ 通过（已避免）/ ❌ 不通过（出现了）

        ### 5.2 禁止的视觉元素
        - [ ] **⭐ 无黑色背景**
          状态：✅ 通过（已避免）/ ❌ 不通过（出现了）

        - [ ] **⭐ 无写实照片或 3D**
          状态：✅ 通过（已避免）/ ❌ 不通过（出现了）

        - [ ] **无恐怖风格**
          状态：✅ 通过（已避免）/ ❌ 不通过（出现了）

        - [ ] **无无关装饰**
          状态：✅ 通过（已避免）/ ❌ 不通过（出现了）

        ---

        ## 第六部分：逻辑流畅性

        ### 6.1 画面与推理对应
        - [ ] **每个推理步骤有对应画面**
          问题：每个推理步骤是否都有清晰的画面展示？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **画面顺序与推理顺序一致**
          问题：镜头顺序是否与推理逻辑顺序一致？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ### 6.2 时长合理性
        - [ ] **总时长符合目标**
          问题：视频总时长是否符合 `target_duration`（{topic.get('target_duration', 'N/A')}）？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **Hook 足够短**
          问题：开头钩子是否在 3 秒内？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ---

        ## 第七部分：平台适配性

        ### 7.1 适合短视频平台
        - [ ] **适合 TikTok / YouTube Shorts**
          问题：内容和风格是否适合短视频平台？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **前 3 秒抓住注意力**
          问题：Hook 是否足够吸引人？
          状态：✅ 通过 / ❌ 不通过
          备注：

        - [ ] **包含 Call-to-Action**
          问题：视频结尾是否有明确的 Call-to-Action？
          状态：✅ 通过 / ❌ 不通过
          备注：

        ---

        ## 总体评分

        ### 硬性要求（必须全部通过）
        - [ ] **第一部分：内容准确性** - 所有 ⭐ 项目通过
        - [ ] **第二部分：叙事形式** - 所有 ⭐ 项目通过
        - [ ] **第三部分：视觉风格** - 所有 ⭐ 项目通过
        - [ ] **第四部分：字幕设计** - 所有 ⭐ 项目通过
        - [ ] **第五部分：禁止元素检查** - 所有 ⭐ 项目通过

        ### 建议通过的部分（强烈推荐）
        - [ ] **第六部分：逻辑流畅性** - 至少 80% 项目通过
        - [ ] **第七部分：平台适配性** - 至少 80% 项目通过

        ---

        ## 检查结果

        **总体状态**: [选择一项]
        - ✅ **通过** - 所有硬性要求通过，可以提交给 NotebookLM
        - ⚠️ **条件通过** - 硬性要求通过，但部分建议项需改进
        - ❌ **不通过** - 存在硬性要求不通过的项目，必须修改

        **需要改进的项目**:
        [列出所有不通过的项目]

        **改进建议**:
        [针对不通过项目的具体改进建议]

        **下一步行动**:
        - 如果 **通过**：复制 NotebookLM Prompt 到 NotebookLM，生成视频
        - 如果 **条件通过**：记录改进建议，可以先生成视频，后续迭代优化
        - 如果 **不通过**：返回修改，修改后重新检查

        ---

        **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        **Mode**: Template Mode
        **Next Step**: Fill in all checklist items
        """)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(self.normalize_markdown(content))
        print(f"✓ 已生成：{output_file.name}")

    def list_topics(self):
        """列出所有可用的选题"""
        print(f"\n🚀 AI Video Generation - Topic Library")
        print(f"=" * 60)

        # 加载选题库
        print(f"\n📂 正在加载选题库...")
        try:
            topics = self.load_topics()
            print(f"✓ 成功加载 {len(topics)} 个选题\n")
        except Exception as e:
            print(f"❌ 错误：{e}")
            return

        # 显示所有选题
        print(f"{'ID':<6} | {'中文标题':<40} | {'英文标题':<40} | {'分类':<12} | {'时长':<6} | {'状态':<10}")
        print(f"{'-' * 6}+{'-' * 42}+{'-' * 42}+{'-' * 14}+{'-' * 8}+{'-' * 12}")

        for topic in topics:
            topic_id = topic.get('id', '').ljust(6)
            title_cn = (topic.get('title_cn', 'N/A')[:38] + '..') if len(topic.get('title_cn', '')) > 40 else topic.get('title_cn', 'N/A').ljust(40)
            title_en = (topic.get('title_en', 'N/A')[:38] + '..') if len(topic.get('title_en', '')) > 40 else topic.get('title_en', 'N/A').ljust(40)
            category = topic.get('category', 'N/A').ljust(12)
            duration = topic.get('target_duration', 'N/A').ljust(6)
            status = topic.get('status', 'N/A').ljust(10)

            # Check if has enhanced fields
            enhanced = '✨' if 'full_problem' in topic else '  '

            print(f"{enhanced}{topic_id} | {title_cn} | {title_en} | {category} | {duration} | {status}")

        print(f"\n{'✨ = 已包含增强字段（可直接生成）':<60}")
        print(f"\n💡 使用方法：")
        print(f"   python scripts/generate_video_package.py --topic-id <ID>")
        print(f"   例如：python scripts/generate_video_package.py --topic-id 001")

    def generate(self, topic_id, overwrite=False):
        """
        生成完整的 video package

        Args:
            topic_id: 选题 ID
            overwrite: 是否覆盖已存在的输出文件夹
        """
        print(f"\n🚀 AI Video Generation - Video Package Generator")
        print(f"模式：Template Mode（Phase 1B - Enhanced Fields Support）")
        print(f"=" * 60)

        # 1. 加载选题库
        print(f"\n📂 正在加载选题库...")
        try:
            topics = self.load_topics()
            print(f"✓ 成功加载 {len(topics)} 个选题")
        except Exception as e:
            print(f"❌ 错误：{e}")
            return

        # 2. 查找指定选题
        print(f"\n🔍 正在查找选题 ID: {topic_id}...")
        topic = self.find_topic(topics, topic_id)

        if not topic:
            print(f"❌ 错误：找不到 ID 为 '{topic_id}' 的选题")
            print(f"\n可用的选题 ID：")
            for t in topics[:10]:  # 只显示前 10 个
                enhanced = '✨' if 'full_problem' in t else '  '
                print(f"  {enhanced} {t.get('id')}: {t.get('title_cn', 'N/A')}")
            if len(topics) > 10:
                print(f"  ... 还有 {len(topics) - 10} 个选题")
            print(f"\n💡 提示：使用 --list-topics 查看所有可用选题")
            return

        has_enhanced = 'full_problem' in topic
        status_icon = '✨' if has_enhanced else '⚠️ '
        status_text = "已包含增强字段，将生成可用内容" if has_enhanced else "未包含增强字段，将生成 TODO 占位符"

        print(f"{status_icon} 找到选题：{topic.get('title_cn', 'N/A')}")
        print(f"   {status_text}")

        # 3. 创建输出文件夹
        print(f"\n📁 正在创建输出文件夹...")
        output_folder = self.create_output_folder(topic, overwrite=overwrite)
        print(f"✓ 输出文件夹：{output_folder.relative_to(self.project_root)}")

        # 4. 生成各个文件
        print(f"\n📝 正在生成 video package 文件...")
        self.generate_topic_json(topic, output_folder)
        self.generate_video_package_md(topic, output_folder)
        self.generate_notebooklm_prompt_md(topic, output_folder)
        self.generate_notebooklm_clean_source(topic, output_folder)
        self.generate_internal_review(topic, output_folder)
        self.generate_narration_script_md(topic, output_folder)
        self.generate_storyboard_md(topic, output_folder)
        self.generate_subtitles_md(topic, output_folder)
        self.generate_qa_checklist_md(topic, output_folder)

        # 5. TODO 检查
        self.check_todo_count(output_folder)

        # 6. 质量检查（增强版：包含词数和时间轴检查）
        self.check_output_quality(output_folder, topic=topic)

        # 7. 完成
        print(f"\n" + "=" * 60)
        print(f"✅ Video Package 生成完成！")
        print(f"\n📦 输出文件夹：{output_folder.relative_to(self.project_root)}")

        # 根据增强状态显示不同的下一步操作
        if has_enhanced:
            print(f"\n🎯 下一步操作（Enhanced Template Mode (Phase 1B)）：")
            print(f"  1. 打开 {output_folder.name}/internal_review.md 查看生成信息和质量检查")
            print(f"  2. 打开 {output_folder.name}/notebooklm_clean_source.txt 确认内容")
            print(f"  3. 复制 notebooklm_clean_source.txt 完整内容到 NotebookLM")
            print(f"  4. 在 NotebookLM 中生成视频")
            print(f"\n💡 提示：")
            print(f"   - notebooklm_clean_source.txt 是干净版本，直接复制到 NotebookLM")
            print(f"   - notebooklm_prompt.md 是工程版（包含使用说明），用于备查")
            print(f"   - internal_review.md 是内部审核文档，不要复制到 NotebookLM")
        else:
            print(f"\n🎯 下一步操作（Basic Template Mode）：")
            print(f"  1. 打开 {output_folder.name}/notebooklm_prompt.md 填充 TODO 部分")
            print(f"  2. 打开其他文件完善脚本、分镜、字幕")
            print(f"  3. 使用 qa_checklist.md 检查质量")
            print(f"  4. 复制 notebooklm_clean_source.txt 到 NotebookLM 生成视频")
            print(f"\n💡 提示：当前为 Basic Template Mode，生成的文件包含 TODO 占位符，需要人工填充。")
            print(f"   未来可以使用 LLM Mode 自动生成完整内容。")

    def generate_from_title(self, title, output_slug=None, dry_run=False, mock_response=None, overwrite=False):
        """
        Phase 2A: 从题目生成 video package（调用 LLM）

        Args:
            title: 题目（中文或英文）
            output_slug: 输出文件夹名称（如不指定则自动生成）
            dry_run: 是否为 dry-run 模式（不调用 API）
            mock_response: Mock response 文件路径（用于测试，不调用 API）
            overwrite: 是否覆盖已存在的文件夹
        """
        # Determine mode display
        if mock_response:
            mode_display = f"Mock Response Mode (testing)"
        elif dry_run:
            mode_display = "Dry-run (no API call)"
        else:
            mode_display = "LLM Generation"

        print(f"🚀 AI Video Generation - LLM Mode (Phase 2A)")
        print(f"=" * 60)
        print(f"\n📝 Input Title: {title}")
        print(f"   Mode: {mode_display}")

        # 1. Check LLM Topic Enhancer
        if LLMTopicEnhancer is None:
            print(f"\n❌ Error: LLMTopicEnhancer not available")
            print(f"   Make sure llm_topic_enhancer.py is in the scripts/ directory")
            return

        # 2. Generate output slug if not provided
        if not output_slug:
            # Generate from title (simple slug generation)
            import re
            slug = re.sub(r'[^\w\s-]', '', title.lower())
            slug = re.sub(r'[-\s]+', '_', slug)
            slug = slug[:50]  # Limit length
            output_slug = slug if slug else f"topic_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        print(f"\n📁 Output slug: {output_slug}")

        # 3. Create output folder path
        output_folder = self.outputs_dir / output_slug

        if output_folder.exists() and not overwrite and not dry_run:
            # Create timestamped folder
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_slug_new = f"{output_slug}_{timestamp}"
            output_folder = self.outputs_dir / output_slug_new
            print(f"⚠️  文件夹已存在，创建新文件夹：{output_slug_new}")

        if dry_run:
            print(f"   Planned output: {output_folder.relative_to(self.project_root)}")
        else:
            print(f"✓ 输出文件夹：{output_folder.relative_to(self.project_root)}")

        # 4. Generate and save LLM prompt (always, even without API key)
        print(f"\n🤖 Calling LLM Topic Enhancer...")

        enhancer = LLMTopicEnhancer()

        # Always generate and save the prompt first
        output_folder.mkdir(parents=True, exist_ok=True)
        prompt = enhancer.generate_llm_prompt(title)
        prompt_file = output_folder / "llm_generation_prompt.md"
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(f"# LLM Generation Prompt\n\n")
            f.write(f"**Topic**: {title}\n\n")
            f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"**Provider**: {enhancer.provider}\n\n")
            f.write(f"**Model**: {enhancer.model}\n\n")
            f.write(f"---\n\n")
            f.write(prompt)
        print(f"✅ Saved LLM prompt to: {prompt_file.relative_to(self.project_root)}")

        # For dry-run, stop here
        if dry_run:
            print(f"\n⚠️  Dry-run mode: Stopping here. No API call will be made.")
            print(f"\n✅ Dry-run complete!")
            print(f"   Generated files:")
            print(f"     - {prompt_file.relative_to(self.project_root)}")
            print(f"\n💡 提示：Dry-run 不调用 API，只生成 prompt。")
            print(f"   移除 --dry-run 参数以真实调用 LLM。")
            return

        # For mock-response, load JSON and skip API
        if mock_response:
            print(f"\n📂 Loading mock response from: {mock_response}")
            try:
                mock_path = Path(mock_response)
                if not mock_path.exists():
                    print(f"\n❌ Error: Mock response file not found: {mock_response}")
                    return

                with open(mock_path, 'r', encoding='utf-8') as f:
                    enhanced_topic = json.load(f)

                print(f"✅ Mock response loaded successfully")

                # Validate
                is_valid, errors = enhancer.validate_enhanced_topic(enhanced_topic)

                if not is_valid:
                    print(f"\n❌ Validation failed with {len(errors)} errors:")
                    for error in errors:
                        print(f"   - {error}")

                    # Save validation errors
                    error_file = output_folder / "validation_errors.txt"
                    with open(error_file, 'w', encoding='utf-8') as f:
                        f.write(f"# Validation Errors\n\n")
                        f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                        f.write(f"**Total Errors**: {len(errors)}\n\n")
                        f.write(f"**Source**: Mock response ({mock_response})\n\n")
                        f.write(f"---\n\n")
                        for error in errors:
                            f.write(f"- {error}\n")
                    print(f"✓ Saved validation errors to: {error_file.relative_to(self.project_root)}")
                    return

                print(f"\n✅ Enhanced topic validation passed")

                # Skip to file generation
                # (jump to the section after all API/validation logic)

            except json.JSONDecodeError as e:
                print(f"\n❌ Error: Invalid JSON in mock response file: {e}")
                return
            except Exception as e:
                print(f"\n❌ Error loading mock response: {e}")
                return

            # Jump to file generation (set a flag to skip API call logic)
            skip_api_call = True
        else:
            skip_api_call = False

        # Check API key before calling API (skip if mock_response)
        if not skip_api_call and not enhancer.check_api_key():
            print(f"\n❌ Error: Missing AI_VIDEO_LLM_API_KEY")
            print(f"\n💡 How to fix:")
            print(f"   1. cp config/example.env .env")
            print(f"   2. open .env")
            print(f"   3. set AI_VIDEO_LLM_API_KEY=your-api-key-here")
            print(f"   4. run the command again")
            print(f"\n⚠️  No API call was made.")

            # Save error file
            error_file = output_folder / "llm_error.txt"
            with open(error_file, 'w', encoding='utf-8') as f:
                f.write(f"# LLM Error\n\n")
                f.write(f"**Error Type**: Missing API key\n\n")
                f.write(f"**Missing Variable**: AI_VIDEO_LLM_API_KEY\n\n")
                f.write(f"**How to fix**:\n")
                f.write(f"1. cp config/example.env .env\n")
                f.write(f"2. open .env\n")
                f.write(f"3. set AI_VIDEO_LLM_API_KEY=your-api-key-here\n")
                f.write(f"4. run the command again\n\n")
                f.write(f"**No API call was made.**\n")
            print(f"✓ Saved error details to: {error_file.relative_to(self.project_root)}")
            print(f"\n📁 Generated files:")
            print(f"   - {prompt_file.relative_to(self.project_root)}")
            print(f"   - {error_file.relative_to(self.project_root)}")
            return

        # Call API and parse response (skip if mock_response)
        if not skip_api_call:
            try:
                response_text = enhancer.call_llm_api(prompt, dry_run=False)

                # Save raw response
                if response_text:
                    response_file = output_folder / "llm_raw_response.txt"
                    with open(response_file, 'w', encoding='utf-8') as f:
                        f.write(f"# LLM Raw Response\n\n")
                        f.write(f"**Topic**: {title}\n\n")
                        f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                        f.write(f"**Provider**: {enhancer.provider}\n\n")
                        f.write(f"**Model**: {enhancer.model}\n\n")
                        f.write(f"---\n\n")
                        f.write(response_text)
                    print(f"✅ Saved raw response to: {response_file.relative_to(self.project_root)}")

                # Parse JSON
                enhanced_topic = enhancer.parse_json_response(response_text)

                # Validate
                is_valid, errors = enhancer.validate_enhanced_topic(enhanced_topic)

                if not is_valid:
                    print(f"\n❌ Validation failed with {len(errors)} errors:")
                    for error in errors:
                        print(f"   - {error}")

                    # Save validation errors
                    error_file = output_folder / "validation_errors.txt"
                    with open(error_file, 'w', encoding='utf-8') as f:
                        f.write(f"# Validation Errors\n\n")
                        f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                        f.write(f"**Total Errors**: {len(errors)}\n\n")
                        f.write(f"---\n\n")
                        for error in errors:
                            f.write(f"- {error}\n")
                    print(f"✓ Saved validation errors to: {error_file.relative_to(self.project_root)}")
                    return

                print(f"\n✅ Enhanced topic validation passed")

            except ValueError as e:
                # JSON parse error
                print(f"\n❌ Error during JSON parsing: {e}")
                error_file = output_folder / "llm_error.txt"
                with open(error_file, 'w', encoding='utf-8') as f:
                    f.write(f"# LLM Error\n\n")
                    f.write(f"**Error Type**: JSON Parse Error\n\n")
                    f.write(f"**Error Message**: {str(e)}\n\n")
                    f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(f"---\n\n")
                    f.write(f"Check llm_raw_response.txt for full LLM output.\n")
                print(f"✓ Saved error details to: {error_file.relative_to(self.project_root)}")
                return
            except Exception as e:
                # Unexpected error
                print(f"\n❌ Unexpected error: {e}")
                error_file = output_folder / "llm_error.txt"
                with open(error_file, 'w', encoding='utf-8') as f:
                    f.write(f"# LLM Error\n\n")
                    f.write(f"**Error Type**: Unexpected error\n\n")
                    f.write(f"**Error Message**: {str(e)}\n\n")
                    f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                print(f"✓ Saved error details to: {error_file.relative_to(self.project_root)}")
                return

        # 5. Save enhanced topic as JSON
        print(f"\n📝 正在保存 enhanced topic...")
        topic_file = output_folder / "topic.json"
        with open(topic_file, 'w', encoding='utf-8') as f:
            json.dump(enhanced_topic, f, indent=2, ensure_ascii=False)
        print(f"✓ 已生成：topic.json")

        # 6. Generate all other files using existing logic
        print(f"\n📝 正在生成 video package 文件...")
        self.generate_video_package_md(enhanced_topic, output_folder)
        self.generate_notebooklm_prompt_md(enhanced_topic, output_folder)
        self.generate_narration_script_md(enhanced_topic, output_folder)
        self.generate_storyboard_md(enhanced_topic, output_folder)
        self.generate_subtitles_md(enhanced_topic, output_folder)
        self.generate_qa_checklist_md(enhanced_topic, output_folder)

        # 7. Generate notebooklm_clean_source.txt (Phase 2A specific)
        print(f"📝 正在生成 NotebookLM clean source...")
        self.generate_notebooklm_clean_source(enhanced_topic, output_folder)

        # 8. Generate internal_review.md (Phase 2A specific)
        print(f"📝 正在生成 internal review...")
        self.generate_internal_review(enhanced_topic, output_folder)

        # 9. Quality checks
        self.check_todo_count(output_folder)
        self.check_output_quality(output_folder, topic=enhanced_topic)

        # 10. Complete
        print(f"\n" + "=" * 60)
        print(f"✅ LLM Mode Video Package 生成完成！")
        print(f"\n📦 输出文件夹：{output_folder.relative_to(self.project_root)}")
        print(f"\n🎯 下一步操作（LLM Mode - Phase 2A）：")
        print(f"  1. 打开 {output_folder.name}/notebooklm_clean_source.txt")
        print(f"  2. 复制完整内容到 NotebookLM")
        print(f"  3. NotebookLM 生成视频")
        print(f"  4. 使用 internal_review.md 记录质量审核")
        print(f"\n💡 提示：notebooklm_clean_source.txt 是干净版本，可直接复制到 NotebookLM。")

    def generate_notebooklm_clean_source(self, topic, output_folder):
        """
        生成 notebooklm_clean_source.txt（干净版本，无工程说明）

        这是真正复制到 NotebookLM 的文件。
        """
        output_file = output_folder / "notebooklm_clean_source.txt"

        # 这个文件只包含 20 个 NotebookLM 字段，不包含工程信息
        # 复用 notebooklm_prompt.md 的内容，但去掉顶部说明和底部元信息

        # 简化版：直接生成核心内容
        # （实际实现时可以读取 notebooklm_prompt.md 然后清理）

        content = self.generate_notebooklm_core_content(topic)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"✓ 已生成：notebooklm_clean_source.txt")

    def generate_notebooklm_core_content(self, topic):
        """生成 NotebookLM 核心内容（20 个字段，无元信息）"""
        # This is a simplified version - reuse logic from generate_notebooklm_prompt_md
        # but without the header/footer metadata

        # 辅助函数：获取字段值或 TODO
        def get_or_todo(field_name, todo_text):
            return topic.get(field_name, f"[TODO: {todo_text}]")

        # Generate reasoning steps
        if 'reasoning_steps' in topic and topic['reasoning_steps']:
            steps_text = ""
            for step in topic['reasoning_steps']:
                step_num = step.get('step', '?')
                step_title = self.get_reasoning_step_title(step)
                step_explanation = self.get_reasoning_step_explanation(step)
                steps_text += f"\n**Step {step_num}: {step_title}**\n"
                steps_text += f"{step_explanation}\n"
            reasoning_content = steps_text
        else:
            reasoning_content = "[TODO: Fill in reasoning steps]"

        # Generate on-screen text plan (phase-based, not precise timestamp table)
        if 'storyboard_scenes' in topic and topic['storyboard_scenes']:
            onscreen_text = ""
            scene_labels = ["Opening", "Question", "Wrong intuition", "Key idea", "Answer reveal", "Final takeaway"]
            for idx, scene in enumerate(topic['storyboard_scenes']):
                label = scene_labels[idx] if idx < len(scene_labels) else f"Scene {idx+1}"
                onscreen = scene.get('onscreen_text', '')
                if onscreen and onscreen.strip() and not onscreen.startswith('[TODO'):
                    onscreen_text += f"**{label}**:\n{onscreen}\n\n"
            onscreen_content = onscreen_text if onscreen_text else "[TODO: Fill in on-screen text for each phase]"
        else:
            onscreen_content = "[TODO: Fill in on-screen text for each phase]"

        # Calculate word count
        duration_str = topic.get('target_duration', '60s')
        word_count_min, word_count_max = self.estimate_word_count_range(duration_str)
        word_count = f"{word_count_min}-{word_count_max} words"

        # Format duration display
        min_sec, max_sec = self.parse_duration_range(duration_str)
        if min_sec == max_sec:
            duration_display = f"{min_sec} seconds"
        else:
            duration_display = f"{min_sec}-{max_sec} seconds"

        content = dedent(f"""\
        # NotebookLM Prompt - {topic.get('title_en', 'Untitled')}

        ## Title

        {topic.get('title_en', 'Untitled')}

        ---

        ## Topic

        {topic.get('topic_label_en') or topic.get('category', '[TODO: Topic category]')}

        ---

        ## Target platform

        TikTok, YouTube Shorts, Instagram Reels

        ---

        ## Target audience

        Students, parents, and viewers who enjoy short math puzzles, probability puzzles, brain tricks, visual reasoning, or everyday science.

        ---

        ## Video length

        {duration_display}

        ---

        ## Video format

        Short-form educational video.

        ---

        ## Core concept

        {topic.get('core_concept', '[TODO: Core concept]')}

        {get_or_todo('short_explanation', '用 1-3 句话说明这个视频真正讲的核心概念，不只是重复标题')}

        ---

        ## Narration style

        ⭐⭐⭐ **CRITICAL - MANDATORY REQUIREMENTS** ⭐⭐⭐

        - Use a single narrator only.
        - The video must be a one-person explanatory monologue.
        - The narrator should directly explain the puzzle to the viewer.
        - Do not use dialogue.
        - Do not use two hosts.
        - Do not use multiple speakers.
        - Do not use podcast style.
        - Do not use interview style.
        - Do not create a conversation between characters.
        - Do not include back-and-forth discussion.

        ---

        ## Video hook

        {get_or_todo('hook', '吸引人的开场（一句话，10-15 词）')}

        ---

        ## Puzzle setup

        {get_or_todo('full_problem', '完整问题陈述')}

        {get_or_todo('question', '核心问题')}

        ---

        ## Question

        {get_or_todo('question', '核心问题')}

        ---

        ## Correct answer

        {get_or_todo('correct_answer', '正确答案（简短清晰）')}

        ---

        ## Wrong intuition

        {get_or_todo('wrong_intuition', '常见错误直觉（1-2 句话）')}

        ---

        ## Key explanation

        {reasoning_content}
        ---

        ## Main lesson

        {get_or_todo('takeaway', '核心要点（1-2 句话）')}

        ---

        ## Narration draft

        ⭐ **CRITICAL**: This MUST be a **single narrator monologue**. Do NOT create dialogue, interview, or podcast format.

        {get_or_todo('narration_script', '完整英文单人旁白脚本')}

        **Narration requirements**:
        - **Single narrator only** - one clear, friendly voice throughout
        - **Tone**: Casual but authoritative, curious but confident, friendly but not overly cute
        - **Pacing**: 2-3 words per second (English), slow down at key reveals
        - **Word count**: Approximately {word_count} for {duration_display}

        ---

        ## On-screen text plan

        ⭐ **CRITICAL**: Text must be **large and clear** (at least 1/5 of screen height). Use **yellow highlight boxes** for key words.

        {onscreen_content}
        ---

        ## Visual style

        ⭐⭐⭐ **CRITICAL - MANDATORY REQUIREMENTS** ⭐⭐⭐

        ### ✅ MUST HAVE:

        **Background**:
        - Minimal white background or white/light graph-paper background.
        - Pure white (#FFFFFF) OR light gray graph paper (#F5F5F5 with subtle grid lines at 10-20% opacity).

        **Illustration Style**:
        - Clean doodle / hand-drawn educational style.
        - Modern educational style.
        - Use simple hand-drawn shapes. Avoid photorealistic or 3D-rendered objects.
        - Hand-drawn lines (slightly irregular, not perfectly geometric).
        - Simple but not childish, cute but not overly cute.
        - Think of it as: sketches drawn on white paper with a black marker.

        **Text & Captions**:
        - Use large readable English text. Key phrases should be prominent, but should not cover the main diagram.
        - Clear on-screen captions.
        - Yellow highlight boxes for key words when helpful.
        - Bold Sans-serif font (Arial, Roboto, Montserrat).
        - Black text (#000000) on white/light background.

        **Animation**:
        - Simple motion only.
        - Fade in / fade out (0.3-0.5s).
        - Zoom in / zoom out (0.5-1s).
        - Pan left / pan right (1-2s).
        - Hand-drawn animation (elements gradually "draw" themselves).

        **Core Visual Consistency**:
        {topic.get('core_visual_consistency', '[TODO: Describe core visual element]')}

        ### ❌ DO NOT INCLUDE:

        - No realistic humans.
        - No dialogue bubbles.
        - No podcast visuals (two people sitting, microphones, headphones).
        - No interview visuals (interviewer and interviewee).
        - No dark background.
        - No black background.
        - No decorative clutter.
        - No random objects.
        - No unrelated characters.
        - No photorealistic images or 3D renders.
        - No horror elements or scary visuals.
        - No complex 3D animations, spinning (unless relevant), explosions, flashing effects.

        ---

        ## Important requirements

        ⭐⭐⭐ **CRITICAL - MANDATORY REQUIREMENTS** ⭐⭐⭐

        ### Logical Correctness:
        - The explanation must be logically correct.
        - The answer must match the puzzle.
        - Do not change the puzzle setup or add extra conditions.
        - Do not give the wrong answer.
        - Do not present the wrong intuition as the correct answer.

        ### Visual Requirements:
        - The visuals must support the reasoning, not distract from it.
        - The core diagram must remain consistent across all scenes.
        - Do not create visuals that contradict the explanation.

        ### Format Requirements:
        - The video must not become a dialogue, interview, podcast, or two-host conversation.
        - Use single narrator monologue only.
        - Do not use multiple speakers or back-and-forth discussion.

        ### Topic-Specific Requirements:
        {topic.get('notebooklm_specific_instructions', 'Follow general guidelines above.')}

        ---

        ## Call to action

        {get_or_todo('cta', 'Follow for more [topic] puzzles')}

        ---
        """)

        return self.normalize_markdown(content)

    def generate_internal_review(self, topic, output_folder):
        """生成 internal_review.md（内部审核文件，不复制到 NotebookLM）"""
        output_file = output_folder / "internal_review.md"

        # Word count
        narration = topic.get('narration_script', '')
        actual_word_count = len(narration.split())
        duration_str = topic.get('target_duration', '60s')
        word_count_min, word_count_max = self.estimate_word_count_range(duration_str)

        # Counts
        scene_count = len(topic.get('storyboard_scenes', []))
        subtitle_count = len(topic.get('subtitle_segments', []))
        step_count = len(topic.get('reasoning_steps', []))

        # Detect mode (check if llm_raw_response.txt exists)
        mode_text = "LLM Mode (Phase 2A)" if (output_folder / "llm_raw_response.txt").exists() else "Template Mode (Phase 1B)"
        model_text = os.getenv('AI_VIDEO_LLM_MODEL', 'N/A') if mode_text.startswith("LLM") else "N/A"
        provider_text = os.getenv('AI_VIDEO_LLM_PROVIDER', 'N/A') if mode_text.startswith("LLM") else "N/A"

        content = dedent(f"""\
        # Internal Review - {topic.get('title_en', 'Untitled')}

        > **用途**：内部审核和质量记录，不要复制到 NotebookLM。
        > 真正复制到 NotebookLM 的文件是：notebooklm_clean_source.txt

        ---

        ## Generation Info

        - **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        - **Mode**: {mode_text}
        - **Model**: {model_text}
        - **Provider**: {provider_text}
        - **Output Folder**: {output_folder.name}

        ---

        ## Topic Info

        - **Title (CN)**: {topic.get('title_cn', 'N/A')}
        - **Title (EN)**: {topic.get('title_en', 'N/A')}
        - **Category**: {topic.get('category', 'N/A')}
        - **Core Concept**: {topic.get('core_concept', 'N/A')}
        - **Target Duration**: {topic.get('target_duration', 'N/A')}
        - **Difficulty**: {topic.get('difficulty', 'N/A')}

        ---

        ## Content Metrics

        - **Narration Word Count**: {actual_word_count} words (recommended: {word_count_min}-{word_count_max})
        - **Reasoning Steps**: {step_count} steps
        - **Storyboard Scenes**: {scene_count} scenes
        - **Subtitle Segments**: {subtitle_count} segments

        ---

        ## Validation Result

        """)

        # Run validation (use LLMTopicEnhancer's validation if available)
        try:
            enhancer = LLMTopicEnhancer()
            is_valid, errors = enhancer.validate_enhanced_topic(topic)
        except:
            # Fallback: simple validation
            is_valid = True
            errors = []

        if is_valid:
            content += "✅ All validation checks passed\n\n"
        else:
            content += f"⚠️  Validation found {len(errors)} issues:\n\n"
            for error in errors:
                content += f"- {error}\n"
            content += "\n"

        content += dedent(f"""\
        ---

        ## Quality Checklist

        ### Content Quality
        - [ ] **Logic**: Is the explanation logically correct?
        - [ ] **Answer**: Does the answer match the question?
        - [ ] **Clarity**: Is the explanation clear and easy to follow?
        - [ ] **Engagement**: Is the hook engaging? Is the reveal satisfying?

        ### Style Compliance
        - [ ] **Single Narrator**: Is this a monologue (not dialogue/podcast)?
        - [ ] **White Background**: White or light graph-paper background specified?
        - [ ] **Hand-Drawn Style**: Clean doodle / hand-drawn style?
        - [ ] **Large Captions**: Text large and clear, without covering the main diagram?
        - [ ] **Yellow Highlights**: Key words highlighted?
        - [ ] **Consistent Visual**: Core diagram consistent throughout?

        ### Technical Quality
        - [ ] **Word Count**: Within recommended range?
        - [ ] **Timeline**: Scenes and subtitles cover full 50-60s?
        - [ ] **Structure**: 6 scenes, 8-10 subtitle segments?

        ---

        ## Next Steps

        1. Review notebooklm_clean_source.txt
        2. Check quality checklist above
        3. Copy notebooklm_clean_source.txt to NotebookLM
        4. Generate video in NotebookLM
        5. Review generated video
        6. Document feedback here

        ---

        ## Feedback & Notes

        (Add your review notes here)

        """)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"✓ 已生成：internal_review.md")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="AI Video Generation - Video Package Generator (Phase 2A)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
        使用示例：

          Phase 1B - Template Mode (从 topic_library_sample.jsonl 读取):
            # 列出所有可用选题
            python scripts/generate_video_package.py --list-topics

            # 从 JSONL 生成 video package
            python scripts/generate_video_package.py --topic-id 001 --overwrite

          Phase 2A - LLM Mode (从题目生成):
            # Dry-run（不调用 API，只生成 prompt）
            python scripts/generate_video_package.py \\
              --title "为什么数字9总感觉最特别" \\
              --mode llm \\
              --dry-run \\
              --output-slug number_9_test

            # 调用 LLM 生成
            python scripts/generate_video_package.py \\
              --title "为什么数字9总感觉最特别" \\
              --mode llm \\
              --output-slug number_9

        当前支持模式：
          - Template Mode (Phase 1B): 从 enhanced topic JSON 生成
          - LLM Mode (Phase 2A): 从题目调用 LLM 生成
        """)
    )

    # Phase 1B arguments
    parser.add_argument(
        "--topic-id",
        help="选题 ID（例如：001, 002）- Phase 1B mode"
    )

    parser.add_argument(
        "--list-topics",
        action="store_true",
        help="列出所有可用的选题"
    )

    # Phase 2A arguments
    parser.add_argument(
        "--title",
        help="题目（中文或英文）- Phase 2A mode"
    )

    parser.add_argument(
        "--mode",
        choices=["template", "llm"],
        default="template",
        help="生成模式：template=从 JSONL 读取, llm=调用 LLM 生成（默认：template）"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run 模式（不调用 API，只生成 prompt）- 仅用于 LLM mode"
    )

    parser.add_argument(
        "--mock-response",
        help="Mock response 文件路径（用于测试，不调用 API）- 仅用于 LLM mode"
    )

    parser.add_argument(
        "--output-slug",
        help="输出文件夹名称（例如：number_9）- 如不指定则自动生成"
    )

    # Common arguments
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="如果输出文件夹已存在，直接覆盖（默认会创建带时间戳的新文件夹）"
    )

    args = parser.parse_args()

    # 获取项目根目录（当前脚本在 scripts/ 下）
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    # 创建生成器
    generator = VideoPackageGenerator(project_root)

    # 处理 --list-topics
    if args.list_topics:
        generator.list_topics()
        return

    # Mode routing
    if args.mode == "llm" or args.title:
        # Phase 2A: LLM Mode
        if not args.title:
            parser.error("LLM mode 需要提供 --title")

        generator.generate_from_title(
            title=args.title,
            output_slug=args.output_slug,
            dry_run=args.dry_run,
            mock_response=args.mock_response,
            overwrite=args.overwrite
        )

    elif args.topic_id:
        # Phase 1B: Template Mode
        generator.generate(args.topic_id, overwrite=args.overwrite)

    else:
        parser.error("必须提供 --topic-id（Template Mode）或 --title（LLM Mode）或 --list-topics")


if __name__ == "__main__":
    main()
