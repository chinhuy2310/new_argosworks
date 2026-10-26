"""
ai_usage_service.py — AI Usage & Token Tracking Service
Logs AI usage metrics and provides aggregated reporting per user/department.
"""
from datetime import datetime
from db import query, execute

def record_ai_usage(user_name, dept_id, provider, model, prompt_tokens=0, completion_tokens=0, total_tokens=0, session_id="", feature="chat"):
    """Ghi nhận số lượng token và lượt gọi AI phục vụ thống kê chi phí."""
    try:
        user = user_name or "시스템"
        dept = dept_id or ""
        p_tok = int(prompt_tokens or 0)
        c_tok = int(completion_tokens or 0)
        t_tok = int(total_tokens or (p_tok + c_tok))

        execute(
            """INSERT INTO ai_usage(user_name, dept_id, provider, model, prompt_tokens, completion_tokens, total_tokens, session_id, feature, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user, dept, provider or "unknown", model or "unknown", p_tok, c_tok, t_tok, str(session_id or ""), feature, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[ai_usage] Failed to record token usage: {e}")

def get_ai_usage_stats(period="month", from_date=None, to_date=None):
    """
    Thống kê tổng hợp lượng sử dụng AI:
    - Tổng số token & lượt gọi
    - Phân bổ theo người dùng (by_user)
    - Phân bổ theo phòng ban (by_department)
    - Phân bổ theo nhà cung cấp AI (by_provider)
    - Xu hướng sử dụng theo ngày (daily_trend)
    """
    where_sql = ""
    params = []

    if from_date and to_date:
        where_sql = "WHERE created_at >= ? AND created_at <= ?"
        params = [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]
    elif period == "today":
        where_sql = "WHERE created_at >= ?"
        params = [datetime.now().strftime("%Y-%m-%d 00:00:00")]
    elif period == "week":
        # 7 ngày gần nhất
        from datetime import timedelta
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
        where_sql = "WHERE created_at >= ?"
        params = [week_ago]
    elif period == "month":
        # 30 ngày gần nhất
        from datetime import timedelta
        month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
        where_sql = "WHERE created_at >= ?"
        params = [month_ago]

    # 1. Tổng quát
    summary_row = query(
        f"""SELECT COUNT(*) as total_calls,
                  COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                  COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                  COALESCE(SUM(total_tokens), 0) as total_tokens
           FROM ai_usage {where_sql}""",
        tuple(params)
    )
    summary = summary_row[0] if summary_row else {
        "total_calls": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0, "total_tokens": 0
    }

    # 2. Theo người dùng
    # PostgreSQL requires every non-aggregated column to be in GROUP BY — grouping
    # by user_name alone made this query fail (HTTP 500) on Postgres.
    users_rows = query(
        f"""SELECT user_name, dept_id,
                  COUNT(*) as calls,
                  COALESCE(SUM(total_tokens), 0) as tokens
           FROM ai_usage {where_sql}
           GROUP BY user_name, dept_id
           ORDER BY tokens DESC LIMIT 20""",
        tuple(params)
    )

    # 3. Theo phòng ban
    dept_rows = query(
        f"""SELECT dept_id,
                  COUNT(*) as calls,
                  COALESCE(SUM(total_tokens), 0) as tokens
           FROM ai_usage {where_sql}
           GROUP BY dept_id
           ORDER BY tokens DESC""",
        tuple(params)
    )

    # 4. Theo AI Provider
    prov_rows = query(
        f"""SELECT provider, model,
                  COUNT(*) as calls,
                  COALESCE(SUM(total_tokens), 0) as tokens
           FROM ai_usage {where_sql}
           GROUP BY provider, model
           ORDER BY tokens DESC""",
        tuple(params)
    )

    # 5. Xu hướng 14 ngày gần nhất
    daily_rows = query(
        f"""SELECT substr(created_at, 1, 10) as date_str,
                  COUNT(*) as calls,
                  COALESCE(SUM(total_tokens), 0) as tokens
           FROM ai_usage {where_sql}
           GROUP BY substr(created_at, 1, 10)
           ORDER BY date_str DESC LIMIT 14""",
        tuple(params)
    )

    return {
        "ok": True,
        "summary": summary,
        "by_user": [dict(r) for r in users_rows],
        "by_department": [dict(r) for r in dept_rows],
        "by_provider": [dict(r) for r in prov_rows],
        "daily_trend": [dict(r) for r in daily_rows]
    }
