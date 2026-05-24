# 任务状态

## 基本信息
- 博主: 治愈果
- 视频总数: 415
- 总时长: 27小时21分钟
- 输出目录: /Users/zhangnan53/workspace/dy/治愈果
- Whisper模型: medium
- 并发数: 2
- 预计总耗时: 6-7小时

## 当前状态
- 任务启动时间: 2026-05-22 18:54
- 状态: 运行中

## 进度
查看实时进度: `cat /Users/zhangnan53/workspace/dy/治愈果/_batch_progress.json | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(f'完成: {len(d[\"completed\"])} / 415')"`

查看日志: `tail -20 /Users/zhangnan53/workspace/dy/治愈果/_run.log`

## 后续步骤
1. [x] 获取视频列表 (415个)
2. [x] 脚本开发 (多进程并行 + 单视频文件夹)
3. [ ] 批量提取字幕 (进行中...)
4. [ ] 内容分类归档
5. [ ] 生成最终索引
