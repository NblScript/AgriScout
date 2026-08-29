# 数据库表结构（自动生成）

> **勿手改**：由 `backend/app/tools/gen_db_schema.py` 从 SQLAlchemy metadata 生成。
> 表结构变更后运行 `cd backend && .venv/bin/python -m app.tools.gen_db_schema` 重新生成，
`test_docs.py` 会校验本文件与模型定义一致。

## 基础管理（M1）

### fields

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| name | String(100) | NOT NULL、UNIQUE | — |
| boundary | JSON | NOT NULL | — |
| area_ha | Float | — | — |
| soil_type | String(50) | — | — |
| notes | Text | — | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

### crops

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| name | String(100) | NOT NULL、UNIQUE | — |
| variety | String(100) | — | — |
| lifecycle_days | Integer | NOT NULL | — |
| stages | JSON | NOT NULL | — |
| default_rules | JSON | — | — |
| description | Text | — | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

### plantings

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| field_id | Integer | FK→fields.id、NOT NULL | — |
| crop_id | Integer | FK→crops.id、NOT NULL | — |
| sowing_date | DATE | NOT NULL | — |
| expected_harvest_date | DATE | — | — |
| status | String(20) | NOT NULL | — |
| notes | Text | — | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

索引 `ix_plantings_crop_id`：(crop_id)

索引 `ix_plantings_field_id`：(field_id)

### devices

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| code | String(50) | NOT NULL、UNIQUE | — |
| name | String(100) | NOT NULL | — |
| type | String(20) | NOT NULL | — |
| model | String(100) | — | — |
| status | String(20) | NOT NULL | — |
| notes | Text | — | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

## 巡检接入（M2）

### patrols

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| field_id | Integer | FK→fields.id、NOT NULL | — |
| planting_id | Integer | FK→plantings.id | — |
| device_id | Integer | FK→devices.id | — |
| started_at | DateTime | NOT NULL | — |
| ended_at | DateTime | — | — |
| track | JSON | — | — |
| status | String(20) | NOT NULL | — |
| analysis_status | String(20) | NOT NULL | — |
| notes | Text | — | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

索引 `ix_patrols_device_id`：(device_id)

索引 `ix_patrols_field_id`：(field_id)

索引 `ix_patrols_planting_id`：(planting_id)

### capture_points

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| patrol_id | Integer | FK→patrols.id、NOT NULL | — |
| seq | Integer | NOT NULL | — |
| distance_m | Float | NOT NULL | — |
| lng | Float | NOT NULL | — |
| lat | Float | NOT NULL | — |
| captured_at | DateTime | NOT NULL | — |
| photo_url | String(500) | — | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

索引 `ix_capture_points_patrol_id`：(patrol_id)

### weather_samples

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| capture_point_id | Integer | FK→capture_points.id、NOT NULL | — |
| patrol_id | Integer | FK→patrols.id、NOT NULL | — |
| temp_c | Float | — | — |
| humidity_pct | Float | — | — |
| light_lux | Float | — | — |
| wind_mps | Float | — | — |
| rain_mm | Float | — | — |
| soil_temp_c | Float | — | — |
| soil_moisture_pct | Float | — | — |

索引 `ix_weather_samples_patrol_id`：(patrol_id)

## 分析与建议（M3/M4）

### analyses

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| capture_point_id | Integer | FK→capture_points.id、NOT NULL、UNIQUE | — |
| patrol_id | Integer | FK→patrols.id、NOT NULL | — |
| analyzer_version | String(50) | NOT NULL | — |
| growth_stage | JSON | — | — |
| vigor_level | Integer | — | — |
| ndvi | Float | — | — |
| disease_detections | JSON | — | — |
| risk_score | Float | — | — |
| detail | JSON | — | — |
| analyzed_at | DateTime | NOT NULL、default=now() | — |

索引 `ix_analyses_patrol_id`：(patrol_id)

### rules

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| rule_key | String(80) | NOT NULL、UNIQUE | — |
| crop_id | Integer | FK→crops.id | — |
| tier | String(20) | NOT NULL | — |
| condition | JSON | NOT NULL | — |
| action | Text | NOT NULL | — |
| params | JSON | — | — |
| priority | String(10) | NOT NULL | — |
| active | Boolean | NOT NULL | — |
| version | Integer | NOT NULL | — |
| source | String(300) | — | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

索引 `ix_rules_crop_id`：(crop_id)

### advices

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| patrol_id | Integer | FK→patrols.id、NOT NULL | — |
| capture_point_id | Integer | FK→capture_points.id | — |
| rule_id | Integer | FK→rules.id | — |
| rule_key | String(80) | NOT NULL | — |
| rule_snapshot | JSON | NOT NULL | — |
| content | Text | NOT NULL | — |
| priority | String(10) | NOT NULL | — |
| status | String(20) | NOT NULL | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

索引 `ix_advices_capture_point_id`：(capture_point_id)

索引 `ix_advices_patrol_id`：(patrol_id)

## 标注回流（M6+）

### annotations

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| capture_point_id | Integer | FK→capture_points.id、NOT NULL | — |
| patrol_id | Integer | FK→patrols.id、NOT NULL | — |
| label | String(50) | NOT NULL | — |
| annotator_name | String(80) | NOT NULL | — |
| bbox | JSON | — | — |
| note | Text | — | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

索引 `ix_annotations_capture_point_id`：(capture_point_id)

索引 `ix_annotations_patrol_id`：(patrol_id)

## 其他

### agent_conversations

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| patrol_id | Integer | FK→patrols.id | — |
| question | Text | NOT NULL | — |
| answer | Text | NOT NULL | — |
| tool_calls_trace | JSON | NOT NULL | — |
| model | String(80) | NOT NULL | — |
| prompt_version | String(20) | NOT NULL | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

索引 `ix_agent_conversations_patrol_id`：(patrol_id)

### patrol_reports

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | Integer | PK | — |
| patrol_id | Integer | FK→patrols.id、NOT NULL | — |
| content | Text | NOT NULL | — |
| model | String(80) | NOT NULL | — |
| prompt_version | String(20) | NOT NULL | — |
| input_digest | JSON | NOT NULL | — |
| created_at | DateTime | NOT NULL、default=now() | — |
| updated_at | DateTime | NOT NULL、default=now() | — |

索引 `ix_patrol_reports_patrol_id`：(patrol_id)
