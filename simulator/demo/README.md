# 巡知演示数据

把两个黄瓜大棚的演示数据装进一个**空的**平台数据库，打开前端就能看到工作台、大棚详情、待确认、巡检回放、环境曲线、研究闭环和盲法复核。

> 全部是造的数据：照片是程序画的绿叶加褐斑，温湿度是按「夜里高湿结露」编的曲线，株数、株距也是演示值。
> 只用来演示界面和流程，不能当识别效果或田间结论。

## 文件

| 文件 | 内容 |
|---|---|
| `load_demo.py` | 加载脚本：只走平台 HTTP 接口（与模拟器、rover 同口径，红线 6），日期按「今天」往前推，哪天加载都能看到当天的计划 |
| `data/layout-1号日光温室.json` | 1 号棚布局：4 垄 × 12 株，株距 0.4 米 |
| `data/layout-2号塑料大棚.json` | 2 号棚布局：3 垄 × 10 株，株距 0.4 米 |

加载后平台里会有：

| 内容 | 1 号日光温室 | 2 号塑料大棚 |
|---|---|---|
| 株档案 | 48 株（R01-P001 … R04-P012） | 30 株 |
| 巡检 | 5 趟：12 天前全棚叶背；5 天前 R01-P005 出现褐斑；3 天前扩散到邻株；今天 06:20 全棚（叶背 + 部分正面，3 株补拍）；今天 07:05 按计划补拍 7 株 | 1 趟：今天 06:10，R02-P004 有褐斑 |
| 温湿度 | 记录仪 `th-01`，12 天前到现在每 10 分钟一条；5 天前起夜里湿度 97%（结露） | 没装记录仪（页面显示「环境数据不足」） |
| 今日计划 | 推给人确认、叶背补拍、随机抽查名单 | 同左 |
| 研究闭环 | 今天 06:20 那趟的风险预测和复巡 / 标注任务；一个盲评批次（16 张，等两人判读） | — |

R04-P012 一直没拍到，用来展示「缺拍」；有几张叶背照片故意标成虚焦、过曝或欠曝，用来展示补拍。

## 怎么用

1. 准备一个空库并启动后端（不要用正在用的库）：

   ```bash
   cd backend
   export DATABASE_URL=sqlite:///./demo.db MEDIA_DIR=./media-demo
   .venv/bin/python -m alembic upgrade head
   .venv/bin/python -m app.tools.create_user --username admin --role admin   # 按提示输入两遍口令
   .venv/bin/python -m uvicorn app.main:app --port 8000
   ```

2. 另开一个终端加载演示数据（本机几秒钟，要等后台分析完照片）：

   ```bash
   export AGRISCOUT_USERNAME=admin AGRISCOUT_PASSWORD='<刚才设的口令>'
   cd simulator/demo && ../../backend/.venv/bin/python load_demo.py --api http://127.0.0.1:8000
   ```

   不需要研究闭环的预测、任务和盲评批次时加 `--skip-research`。

3. 启动前端（`cd frontend && pnpm dev`），浏览器打开 http://localhost:5173 ，用上面的账号登录。

## 注意

- **重复运行是安全的**：大棚按名字复用，株档案已有的跳过，同一天的巡检包按包号判为重复，温湿度按「传感器 + 时刻」去重。
  换一天再运行会再加一组按新日期的巡检，所以演示前建议用新的空库重新加载。
- **清晨 7:30 之前加载**时，「今天」的巡检会放在昨天清晨（照片时间不能晚于上传时间，否则平台会标「时间存疑」，决策 D26），
  今日计划仍按今天生成。
- 加载完会在 `simulator/out/demo/th-01.csv` 留一份同样的温湿度数据，可以用 rover 的上传工具练习（平台会按重复跳过）：

  ```bash
  cd rover
  .venv/bin/python env_upload.py --api http://127.0.0.1:8000 --field-id 1 --csv ../simulator/out/demo/th-01.csv \
    --sensor-key th-01 --time-col 时间 --temp-col 温度 --rh-col 湿度 --time-format "%Y/%m/%d %H:%M:%S"
  ```

- 两个布局文件也可以直接给 rover 用，例如 `rover/run.py --fake --layout ../simulator/demo/data/layout-1号日光温室.json`。
- 盲评批次要两位不同的判读人：先在「用户」页建两个操作员账号，分别登录后在「盲法复核」页判读。
