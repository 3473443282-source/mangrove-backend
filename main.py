import os
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="红树林数据查询 API")

# --- 1. 开启跨域支持 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 2. 数据库连接配置 (云端适配版) ---
# 这里的顺序是：优先找环境变量 DATABASE_URL，找不到就用本地地址
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # 这是你原来的本地数据库地址
    DATABASE_URL = "postgresql+asyncpg://postgres:546103@localhost:5432/mangrove_health"

# 特别注意：Render/Supabase 提供的链接通常是 postgres://
# 但 asyncpg 驱动要求必须是 postgresql+asyncpg://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL)

# --- 接口 1：根据坐标获取 NDVI ---
@app.get("/api/ndvi")
async def get_ndvi(lon: float, lat: float, year: int):
    if not (2020 <= year <= 2025):
        raise HTTPException(status_code=400, detail="年份超出数据范围(2020-2025)")

    try:
        async with engine.connect() as conn:
            query = text("""
                SELECT longitude, latitude, ndvi_value, 
                       SQRT(POWER(longitude - :lon, 2) + POWER(latitude - :lat, 2)) as distance
                FROM public.mangrove_ndvi_data
                WHERE year = :year
                ORDER BY distance ASC
                LIMIT 1
            """)
            result = await conn.execute(query, {"lon": lon, "lat": lat, "year": year})
            row = result.fetchone()

            if row:
                if row.distance > 1.0:
                    return {"status": "no_data", "message": "太偏了，全省都没数据"}
                return {
                    "lon": row.longitude,
                    "lat": row.latitude,
                    "ndvi": round(row.ndvi_value, 4),
                    "year": year
                }
            return {"status": "error", "message": "未找到匹配记录"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据库查询失败: {str(e)}")

# --- 接口 2：根据年份获取全域统计数据 ---
@app.get("/api/yearly_stats")
async def get_yearly_stats(year: int = Query(..., description="查询年份，范围2020-2025")):
    if not (2020 <= year <= 2025):
        raise HTTPException(status_code=400, detail="年份超出数据范围(2020-2025)")

    try:
        async with engine.connect() as conn:
            query = text("""
                SELECT health_level, area_km2, ndvi_mean 
                FROM public.mangrove_yearly_stats 
                WHERE year = :year
            """)
            result = await conn.execute(query, {"year": str(year)})
            rows = result.fetchall()

            if not rows:
                return {"status": "no_data", "year": year, "data": []}

            stats_list = []
            for row in rows:
                stats_list.append({
                    "health_level": row.health_level,
                    "area_km2": round(row.area_km2, 4),
                    "ndvi_mean": round(row.ndvi_mean, 4)
                })

            return {
                "status": "success",
                "year": year,
                "data": stats_list
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"统计数据获取失败: {str(e)}")

# --- 接口 3：月度趋势数据 ---
@app.get("/api/ndvi_monthly_trend")
async def get_ndvi_monthly_trend(year: int = Query(..., description="查询年份")):
    try:
        async with engine.connect() as conn:
            query = text("""
                 SELECT CAST(month AS INTEGER) as month, ndvi 
                 FROM public.beibu_gulf_ndvi 
                 WHERE CAST(year AS INTEGER) = :year
                 ORDER BY month ASC
             """)
            result = await conn.execute(query, {"year": year})
            rows = result.fetchall()

            if not rows:
                return {"status": "no_data", "year": year, "months": [], "values": []}

            months = []
            ndvi_values = []
            for row in rows:
                months.append(row.month)
                val = round(row.ndvi, 4) if row.ndvi is not None else None
                ndvi_values.append(val)

            return {
                "status": "success",
                "year": year,
                "xAxis": months,
                "yAxis": ndvi_values,
                "count": len(months)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"月度数据获取失败: {str(e)}")

# --- 启动配置 ---
if __name__ == "__main__":
    # 在本地运行时，通过 python main.py 启动
    # 在云端部署时，Render 会使用 uvicorn main:app 命令，不会进入这个 if
    uvicorn.run(app, host="0.0.0.0", port=8002)