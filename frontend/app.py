"""Streamlit 前端（平台后台 / 商户后台 / 业务员共用入口）。

启动方式：
    streamlit run frontend/app.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# 把项目根目录加到 sys.path，保证 backend.* 可导入
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import requests
import streamlit as st

from backend.config import settings

API_BASE = settings.api_base_url.rstrip("/")

st.set_page_config(page_title="智能报价平台", page_icon="💡", layout="wide")

# 全局视觉样式注入（只在首次渲染执行一次）
# 设计语言：苹果风极简 · 细腻阴影 · 呼吸感 · 高质感
_GLOBAL_CSS = """
<style>
/* ================================================================
   智能报价平台 · 苹果科技风视觉系统
   ================================================================ */
:root {
    --apple-bg: #F5F5F7;
    --apple-card: #FFFFFF;
    --apple-text: #1D1D1F;
    --apple-text-secondary: #6E6E73;
    --apple-text-muted: #86868B;
    --apple-border: #D2D2D7;
    --apple-border-light: rgba(0,0,0,0.06);
    --apple-blue: #0071E3;
    --apple-blue-hover: #0077ED;
    --apple-red: #FF3B30;
    --apple-radius-sm: 8px;
    --apple-radius: 12px;
    --apple-shadow-sm: 0 1px 3px rgba(0,0,0,0.04);
    --apple-shadow: 0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03);
    --apple-shadow-md: 0 8px 20px rgba(0,0,0,0.06), 0 4px 8px rgba(0,0,0,0.03);
    --apple-transition: all 0.2s cubic-bezier(0.25, 0.1, 0.25, 1);
}
html, body, [class*="st-"], .stApp {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif !important;
    -webkit-font-smoothing: antialiased;
}
[data-testid="stAppViewContainer"] {
    background: radial-gradient(ellipse at 0% 0%, rgba(0,113,227,0.03) 0%, transparent 50%), radial-gradient(ellipse at 100% 100%, rgba(52,199,89,0.02) 0%, transparent 50%), var(--apple-bg) !important;
}
[data-testid="stSidebar"] { background: var(--apple-card); border-right: 1px solid var(--apple-border-light); padding: 8px 0; }
div[role="radiogroup"] { padding: 4px 8px; }
div[role="radiogroup"] label[data-baseweb="radio"] { padding: 10px 14px !important; border-radius: var(--apple-radius-sm) !important; margin-bottom: 3px; font-size: 14px !important; font-weight: 500 !important; color: var(--apple-text-secondary) !important; transition: var(--apple-transition); border: 1px solid transparent; }
div[role="radiogroup"] label[data-baseweb="radio"]:hover { background: #F5F5F7; color: var(--apple-text) !important; }
div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked) { background: rgba(0,113,227,0.06); color: var(--apple-text) !important; font-weight: 600 !important; border-color: rgba(0,113,227,0.15); }
h1 { font-size: 26px !important; font-weight: 700 !important; letter-spacing: -0.3px; }
h2 { font-size: 20px !important; font-weight: 600 !important; letter-spacing: -0.2px; }
h3 { font-size: 15px !important; font-weight: 600 !important; }
[data-testid="stContainer"] { background: var(--apple-card); border: 1px solid var(--apple-border-light); border-radius: var(--apple-radius); padding: 22px 24px; box-shadow: var(--apple-shadow); margin-bottom: 18px; transition: box-shadow 0.2s ease; }
[data-testid="stContainer"]:hover { box-shadow: var(--apple-shadow-md); }
div[data-baseweb="input"], div[data-baseweb="textarea"] { border-radius: var(--apple-radius-sm) !important; border: 1px solid var(--apple-border) !important; transition: var(--apple-transition); }
div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within { border-color: var(--apple-blue) !important; box-shadow: 0 0 0 3px rgba(0,113,227,0.12) !important; }
.stButton > button { border-radius: var(--apple-radius-sm) !important; border: 1px solid var(--apple-border) !important; background: var(--apple-card) !important; font-size: 14px !important; font-weight: 500 !important; padding: 6px 16px !important; transition: var(--apple-transition); white-space: nowrap !important; }
.stButton > button:hover { background: #F8F8FA !important; border-color: #B8B8BE !important; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"] { background: var(--apple-blue) !important; color: #FFFFFF !important; border: 1px solid var(--apple-blue) !important; padding: 8px 20px !important; }
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primaryFormSubmit"]:hover { background: var(--apple-blue-hover) !important; box-shadow: 0 4px 12px rgba(0,113,227,0.25) !important; transform: translateY(-1px); }
.stButton > button[kind="secondary"] { background: rgba(255,59,48,0.06) !important; color: var(--apple-red) !important; border-color: rgba(255,59,48,0.15) !important; }
.stButton > button[kind="secondary"]:hover { background: rgba(255,59,48,0.10) !important; }
[data-testid="stDataFrame"] { border-radius: var(--apple-radius-sm); overflow: hidden; border: 1px solid var(--apple-border-light); }
[data-testid="stDataFrame"] table th { background: #FAFAFA !important; color: var(--apple-text-secondary) !important; font-weight: 600 !important; padding: 10px 14px !important; }
[data-testid="stDataFrame"] table td { padding: 10px 14px !important; border-bottom: 1px solid #F0F0F2 !important; }
[data-testid="stDataFrame"] table tbody tr:hover { background: #F8F8FA !important; }
[data-testid="stExpander"] { background: var(--apple-card); border: 1px solid var(--apple-border-light); border-radius: var(--apple-radius); box-shadow: var(--apple-shadow); }
.erp-section-title { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-weight: 600; font-size: 15px; }
.erp-section-title::before { content: ""; width: 3.5px; height: 16px; background: var(--apple-blue); border-radius: 2px; flex-shrink: 0; opacity: 0.8; }
.placeholder-muted { color: var(--apple-text-muted); text-align: center; padding: 48px 12px; background: rgba(0,0,0,0.02); border-radius: var(--apple-radius-sm); border: 1px dashed var(--apple-border); }
@media (max-width: 768px) { [data-testid="stContainer"] { padding: 16px 14px !important; } }
</style>"""

st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


def _section_title(text: str):
    """左侧带色条的统一小节标题。"""
    st.markdown(f'<div class="erp-section-title">{text}</div>', unsafe_allow_html=True)


def _headers():
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def api_get(path: str, params=None):
    return requests.get(f"{API_BASE}{path}", headers=_headers(), params=params, timeout=120)


def api_post(path: str, json=None):
    return requests.post(f"{API_BASE}{path}", headers=_headers(), json=json, timeout=180)


def api_put(path: str, json=None):
    return requests.put(f"{API_BASE}{path}", headers=_headers(), json=json, timeout=120)


def api_delete(path: str):
    return requests.delete(f"{API_BASE}{path}", headers=_headers(), timeout=30)


# ----------------------------- 登录页（独立布局 + 居中卡片，CSS 仅限本页注入） -----------------------------
# 注意：此 CSS 必须在 login_page() 内部注入，而不是模块顶层。否则它会写入全局 DOM，
# 导致登录后进入其他页面时「登录卡片」的 CSS 残留，出现「报价看板里还显示登录输入框」的问题。
_LOGIN_CSS = """
<style>
/* 隐藏 Streamlit 默认元素 */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header { visibility: hidden; }

/* 整体背景 */
[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(ellipse at 10% 20%, rgba(96,165,250,0.18) 0%, transparent 60%),
        radial-gradient(ellipse at 90% 80%, rgba(59,130,246,0.14) 0%, transparent 60%),
        linear-gradient(135deg, #eaf0ff 0%, #eef3ff 50%, #f0f4ff 100%) !important;
    background-attachment: fixed;
}
[data-testid="stHeader"] { background: transparent; }

/* 登录页的"卡片"：就是紧随 #login-page-marker 的 stHorizontalBlock */
#login-page-marker + [data-testid="stHorizontalBlock"] {
    max-width: 620px;
    margin: 7vh auto 4vh auto !important;
    background: rgba(255,255,255,0.72);
    border: 1px solid rgba(200,215,240,0.85);
    border-radius: 16px;
    box-shadow: 0 20px 50px rgba(37,99,235,0.18), 0 2px 6px rgba(16,24,40,0.04);
    overflow: hidden;
    gap: 0 !important;
    padding: 0 !important;
}

/* 左列 —— 插图区 */
#login-page-marker + [data-testid="stHorizontalBlock"]
> [data-testid="column"]:nth-child(1) {
    background: linear-gradient(160deg, rgba(37,99,235,0.05) 0%, rgba(96,165,250,0.03) 100%);
    padding: 28px 22px !important;
    border-right: 1px solid rgba(200,215,240,0.7);
}

/* 右列 —— 表单区 */
#login-page-marker + [data-testid="stHorizontalBlock"]
> [data-testid="column"]:nth-child(2) {
    padding: 26px 28px !important;
}

/* 左侧：品牌 + 描述 */
#login-page-marker .login-left .brand {
    display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
}
#login-page-marker .login-left .brand .logo {
    width: 34px; height: 34px; border-radius: 8px;
    background: linear-gradient(135deg, #2563eb, #60a5fa);
    color: #fff; font-size: 18px; font-weight: 700;
    display: inline-flex; align-items: center; justify-content: center;
    box-shadow: 0 4px 10px rgba(37,99,235,0.25);
}
#login-page-marker .login-left .brand .title {
    font-size: 16px; font-weight: 700; color: #1f2d3d; letter-spacing: 0.3px;
}
#login-page-marker .login-left .desc {
    font-size: 12px; color: #5b6476; line-height: 1.6; margin-bottom: 14px;
}

/* 装饰柱状图 */
#login-page-marker .login-left .decor {
    height: 110px; border-radius: 12px;
    background: linear-gradient(160deg, #ffffff 0%, #eef3ff 100%);
    border: 1px solid rgba(200,215,240,0.9);
    display: flex; align-items: flex-end; justify-content: center;
    gap: 5px; padding: 22px 14px 12px 14px; position: relative;
}
#login-page-marker .login-left .decor::before {
    content: "报价趋势"; position: absolute;
    top: 6px; left: 10px; font-size: 10px; color: #8690a5; font-weight: 500;
}
#login-page-marker .login-left .decor .bar {
    width: 14px; border-radius: 3px 3px 0 0;
    background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%);
}
#login-page-marker .login-left .decor .bar:nth-child(1) { height: 30%; opacity: 0.55; }
#login-page-marker .login-left .decor .bar:nth-child(2) { height: 50%; opacity: 0.65; }
#login-page-marker .login-left .decor .bar:nth-child(3) { height: 65%; opacity: 0.75; }
#login-page-marker .login-left .decor .bar:nth-child(4) { height: 80%; }
#login-page-marker .login-left .decor .bar:nth-child(5) { height: 55%; opacity: 0.70; }
#login-page-marker .login-left .decor .bar:nth-child(6) { height: 92%; }
#login-page-marker .login-left .decor .bar:nth-child(7) { height: 72%; }

#login-page-marker .login-left .tip {
    margin-top: 12px; font-size: 11px; color: #6b7280;
    display: flex; align-items: center; gap: 6px;
}
#login-page-marker .login-left .tip .dot {
    display: inline-block; width: 6px; height: 6px; border-radius: 50%;
    background: #22c55e; box-shadow: 0 0 0 3px rgba(34,197,94,0.10);
}

/* 右侧：标题 / 副标题 */
#login-page-marker .form-head .form-title {
    font-size: 16px; font-weight: 600; color: #1f2d3d; margin: 0 0 4px 0;
}
#login-page-marker .form-head .form-sub {
    font-size: 12px; color: #8690a5; margin: 0 0 10px 0;
}

/* 右侧：表单输入框样式 */
#login-page-marker + [data-testid="stHorizontalBlock"]
> [data-testid="column"]:nth-child(2) div[data-baseweb="input"] {
    border-radius: 8px !important;
    border-color: #d0d8ea !important;
    background: #ffffff !important;
    min-height: 38px;
    transition: all 0.15s ease;
}
#login-page-marker + [data-testid="stHorizontalBlock"]
> [data-testid="column"]:nth-child(2) div[data-baseweb="input"]:focus-within {
    border-color: #2563eb !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.14);
}
#login-page-marker + [data-testid="stHorizontalBlock"]
> [data-testid="column"]:nth-child(2) label p {
    font-size: 12px; color: #4b5563; font-weight: 500;
}

/* 右侧：登录按钮 */
#login-page-marker + [data-testid="stHorizontalBlock"]
> [data-testid="column"]:nth-child(2) button[kind="primaryFormSubmit"] {
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
    border-color: #1d4ed8 !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    padding: 8px 12px !important;
    margin-top: 4px !important;
    box-shadow: 0 4px 10px rgba(37,99,235,0.25);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
#login-page-marker + [data-testid="stHorizontalBlock"]
> [data-testid="column"]:nth-child(2) button[kind="primaryFormSubmit"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 14px rgba(37,99,235,0.32);
}

/* 响应式：窄屏 */
@media (max-width: 640px) {
    #login-page-marker + [data-testid="stHorizontalBlock"] {
        max-width: 92%;
        margin: 4vh auto 0 auto !important;
    }
}
</style>
"""


def login_page():
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)

    # 锚点：CSS 会把紧随其后的 stHorizontalBlock 当成"登录卡片"
    st.markdown('<div id="login-page-marker"></div>', unsafe_allow_html=True)

    col_left, col_right = st.columns([38, 62])

    # ===== 左侧：插图区（纯 HTML） =====
    with col_left:
        st.markdown(
            """
            <div class="login-left">
                <div class="brand">
                    <span class="logo">智</span>
                    <span class="title">智能报价平台</span>
                </div>
                <div class="desc">平台管理员 / 商户管理员 / 业务员三种角色统一登录入口。</div>
                <div class="decor">
                    <div class="bar"></div>
                    <div class="bar"></div>
                    <div class="bar"></div>
                    <div class="bar"></div>
                    <div class="bar"></div>
                    <div class="bar"></div>
                    <div class="bar"></div>
                </div>
                <div class="tip"><span class="dot"></span>24 小时内免重复登录</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ===== 右侧：标题 + 表单 =====
    with col_right:
        st.markdown(
            """
            <div class="form-head">
                <div class="form-title">账号登录</div>
                <div class="form-sub">公司代码留空，即为平台管理员登录</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("login_form", clear_on_submit=False):
            tenant_code = st.text_input(
                "公司代码", value="", placeholder="如：DEMO（留空 = 平台管理员）"
            )
            username = st.text_input("用户名", value="", placeholder="请输入用户名")
            password = st.text_input(
                "密码", type="password", value="", placeholder="请输入密码"
            )
            submitted = st.form_submit_button("🔐 登录", use_container_width=True, type="primary")

    if submitted:
        resp = api_post(
            "/api/auth/login",
            json={
                "tenant_code": tenant_code.strip(),
                "username": username.strip(),
                "password": password,
            },
        )
        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = resp.text
            st.error(f"登录失败：{detail}")
            return
        data = resp.json()
        st.session_state["token"] = data["access_token"]
        st.session_state["username"] = data["username"]
        st.session_state["display_name"] = data.get("display_name") or data["username"]
        st.session_state["role"] = data["role"]
        st.session_state["tenant_code"] = data["tenant_code"]
        st.session_state["tenant_name"] = data.get("tenant_name") or ""
        st.success("登录成功")
        st.rerun()


# ----------------------------- 顶部信息（苹果风扁平卡片）-----------------------------
def topbar():
    role_label = {
        "platform_admin": "🧑‍💼 平台运营管理员",
        "tenant_admin": "🏢 商户管理员",
        "sales": "🧑‍💻 业务员",
    }.get(st.session_state.get("role"), st.session_state.get("role", ""))

    tenant_name = st.session_state.get("tenant_name", "")
    username = st.session_state.get("username", "")
    display_name = st.session_state.get("display_name") or username

    # 关键改动：用一级 columns（4 列），不再嵌套，保证每个按钮有足够宽度不换行
    # 60% 信息区 + 12% 刷新 + 14% 清除缓存 + 14% 退出登录
    cols = st.columns([60, 12, 14, 14])

    with cols[0]:
        st.markdown(
            f'<div style="display:flex;align-items:center;flex-wrap:nowrap;">'
            f'  <span style="font-size:15px;font-weight:600;color:#1D1D1F;">{tenant_name}</span>'
            f'  <span style="color:#86868B;font-size:14px;margin-left:8px;">· 你好，{display_name}</span>'
            f'  <span style="font-size:13px;color:#86868B;margin-left:8px;">{role_label}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with cols[1]:
        st.button("🔄 刷新", use_container_width=True, key="_top_refresh", on_click=lambda: st.rerun())

    with cols[2]:
        st.button("🧹 清除缓存", use_container_width=True, key="_top_clear", on_click=_clear_cache)

    with cols[3]:
        st.button("🚪 退出登录", use_container_width=True, key="_top_logout", on_click=_do_logout)


def _clear_cache():
    for k in list(st.session_state.keys()):
        if k.startswith("_"):
            del st.session_state[k]
    st.success("已清除页面缓存")


def _do_logout():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()


# ----------------------------- 修改密码 -----------------------------
def page_change_password():
    st.subheader("🔑 修改我的密码")
    with st.container():
        _section_title("账号安全")
        with st.form("pwd_form"):
            old = st.text_input("原密码", type="password")
            new1 = st.text_input("新密码（>=6位）", type="password")
            new2 = st.text_input("再次输入新密码", type="password")
            if st.form_submit_button("提交", use_container_width=True, type="primary"):
                if not new1 or len(new1) < 6:
                    st.error("新密码至少 6 位")
                elif new1 != new2:
                    st.error("两次新密码不一致")
                else:
                    resp = api_post("/api/auth/change-password", {"old_password": old, "new_password": new1})
                    if resp.status_code == 200:
                        st.success("密码已更新")
                    else:
                        st.error(resp.json().get("detail") or "更新失败")


# ----------------------------- 平台后台：商户资质管理 -----------------------------
def page_platform_tenants():
    st.markdown("### 🏢 商户资质管理")
    st.caption("可在下方直接编辑基本信息，也可选择商户维护其飞书/LLM/DB配置。")

    resp = api_get("/api/platform/tenants")
    if resp.status_code != 200:
        st.error(resp.json().get("detail") or "加载失败")
        return
    rows = resp.json() or []

    data = []
    for r in rows:
        data.append({
            "序号": int(r.get("id", 0)),
            "公司代码": r.get("code", ""),
            "商户名称": r.get("name", ""),
            "启用状态": "启用" if int(r.get("is_active", 1)) == 1 else "停用",
            "数据源": "飞书表格" if r.get("source_mode") != "db" else "DB 直连",
            "联系人": r.get("contact") or "",
            "联系方式": r.get("contact_info") or "",
            "员工数": int(r.get("user_count", 0)),
            "飞书配置": "已配置" if r.get("feishu_configured") else "未配置",
            "DB配置": "已配置" if r.get("db_configured") else "未配置",
        })
    columns = ["序号", "公司代码", "商户名称", "启用状态", "数据源", "联系人", "联系方式", "员工数", "飞书配置", "DB配置"]
    df = pd.DataFrame(data, columns=columns) if data else pd.DataFrame(columns=columns)

    column_config = {
        "启用状态": st.column_config.SelectboxColumn("启用状态", options=["启用", "停用"], default="启用"),
        "数据源": st.column_config.SelectboxColumn("数据源", options=["飞书表格", "DB 直连"], default="飞书表格"),
        "序号": st.column_config.NumberColumn("序号", format="%d"),
        "员工数": st.column_config.NumberColumn("员工数", format="%d"),
        "公司代码": st.column_config.TextColumn("公司代码"),
        "商户名称": st.column_config.TextColumn("商户名称"),
        "联系人": st.column_config.TextColumn("联系人"),
        "联系方式": st.column_config.TextColumn("联系方式"),
        "飞书配置": st.column_config.TextColumn("飞书配置"),
        "DB配置": st.column_config.TextColumn("DB配置"),
    }

    with st.container():
        _section_title("📋 商户列表（可编辑）")
        edited = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config=column_config,
            disabled=["序号", "公司代码", "员工数", "飞书配置", "DB配置"],
            key="tenant_editor",
        )
        c1, c2 = st.columns([1, 5])
        with c1:
            if st.button("💾 保存修改", use_container_width=True, type="primary"):
                changes = st.session_state.get("tenant_editor", {}).get("edited_rows") or {}
                if not changes:
                    st.info("未检测到修改，请先在表格中编辑单元格再保存。")
                else:
                    errors = []
                    updated = 0
                    for idx, changed_cols in changes.items():
                        row = rows[idx]
                        payload = {}
                        for cn_col, new_val in changed_cols.items():
                            if cn_col == "商户名称":
                                payload["name"] = "" if new_val is None else str(new_val)
                            elif cn_col == "启用状态":
                                payload["is_active"] = 1 if str(new_val) == "启用" else 0
                            elif cn_col == "数据源":
                                payload["source_mode"] = "db" if str(new_val) == "DB 直连" else "feishu"
                            elif cn_col == "联系人":
                                payload["contact"] = "" if new_val is None else str(new_val)
                            elif cn_col == "联系方式":
                                payload["contact_info"] = "" if new_val is None else str(new_val)
                        if payload:
                            r = api_put(f"/api/platform/tenants/{row['id']}", payload)
                            if r.status_code == 200:
                                updated += 1
                            else:
                                errors.append(f"{row.get('code')}: {r.json().get('detail') or '保存失败'}")
                    if updated:
                        st.success(f"已更新 {updated} 条。")
                    for e in errors:
                        st.error(e)
                    if updated:
                        st.rerun()
        with c2:
            if st.button("🔄 刷新列表", use_container_width=True):
                st.rerun()

    # ---- 点击商户维护配置 ----
    if rows:
        with st.container():
            _section_title("⚙️ 商户数据源配置（飞书 / LLM / DB 直连）")
            merchant_options = {f"[{r['code']}] {r['name']}": r for r in rows}
            picked_label = st.selectbox("选择一个商户以编辑其配置", list(merchant_options.keys()), key="config_merchant_pick")
            if picked_label:
                cur_merchant = merchant_options[picked_label]
                tenant_id = cur_merchant["id"]
                # 加载该商户的现有配置
                config_resp = api_get(f"/api/platform/tenants/{tenant_id}/config")
                cur_cfg = config_resp.json() if config_resp.status_code == 200 else {}

                with st.expander(f"📘 飞书多维表格", expanded=False):
                    with st.form(f"feishu_cfg_{tenant_id}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            feishu_app_id = st.text_input("APP ID", value=cur_cfg.get("feishu_app_id", ""), key=f"fs_appid_{tenant_id}")
                            feishu_app_secret = st.text_input("APP Secret（留空=不改，当前：" + ("已设置" if cur_cfg.get("has_app_secret") else "未设置") + "）",
                                type="password", value="", key=f"fs_secret_{tenant_id}")
                        with c2:
                            feishu_app_token = st.text_input("APP Token", value=cur_cfg.get("feishu_app_token", ""), key=f"fs_token_{tenant_id}")
                            feishu_table_id = st.text_input("Table ID", value=cur_cfg.get("feishu_table_id", ""), key=f"fs_tid_{tenant_id}")
                        if st.form_submit_button("💾 保存飞书配置", type="primary"):
                            r = api_put(f"/api/platform/tenants/{tenant_id}/config", {
                                "feishu_app_id": feishu_app_id.strip(), "feishu_app_secret": feishu_app_secret.strip(),
                                "feishu_app_token": feishu_app_token.strip(), "feishu_table_id": feishu_table_id.strip(),
                                "feishu_field_name": cur_cfg.get("feishu_field_name", "商品名称"), "feishu_price_field_name": cur_cfg.get("feishu_price_field_name", "报价"),
                                "llm_provider": cur_cfg.get("llm_provider", "gemini"), "llm_api_key": "", "llm_model": cur_cfg.get("llm_model", ""),
                                "db_url": cur_cfg.get("db_url", ""), "db_username": cur_cfg.get("db_username", ""), "db_password": "",
                                "db_company_code": cur_cfg.get("db_company_code", ""), "price_date": cur_cfg.get("price_date", ""),
                            })
                            if r.status_code == 200: st.success("飞书配置已保存"), st.rerun()
                            else: st.error(r.json().get("detail") or "保存失败")

                with st.expander(f"🤖 LLM 与字段映射", expanded=False):
                    with st.form(f"llm_cfg_{tenant_id}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            field_name = st.text_input("商品名称列字段名", value=cur_cfg.get("feishu_field_name", "商品名称"), key=f"llm_fn_{tenant_id}")
                            llm_provider = st.selectbox("LLM 提供方", ["deepseek", "gemini", "disabled"],
                                index=["deepseek", "gemini", "disabled"].index(cur_cfg.get("llm_provider", "deepseek")), key=f"llm_prov_{tenant_id}")
                            llm_model = st.text_input("LLM 模型名", value=cur_cfg.get("llm_model", "DeepSeek-V4-Flash"), key=f"llm_mdl_{tenant_id}")
                        with c2:
                            price_field = st.text_input("报价列字段名", value=cur_cfg.get("feishu_price_field_name", "报价"), key=f"llm_pf_{tenant_id}")
                            llm_key = st.text_input("LLM API Key（留空=不改，当前：" + ("已设置" if cur_cfg.get("has_llm_api_key") else "未设置") + "）",
                                type="password", value="", key=f"llm_key_{tenant_id}")
                        if st.form_submit_button("💾 保存 LLM 配置", type="primary"):
                            r = api_put(f"/api/platform/tenants/{tenant_id}/config", {
                                "feishu_app_id": cur_cfg.get("feishu_app_id", ""), "feishu_app_secret": "",
                                "feishu_app_token": cur_cfg.get("feishu_app_token", ""), "feishu_table_id": cur_cfg.get("feishu_table_id", ""),
                                "feishu_field_name": field_name.strip() or "商品名称", "feishu_price_field_name": price_field.strip() or "报价",
                                "llm_provider": llm_provider, "llm_api_key": llm_key.strip(), "llm_model": llm_model.strip() or "DeepSeek-V4-Flash",
                                "db_url": cur_cfg.get("db_url", ""), "db_username": cur_cfg.get("db_username", ""), "db_password": "",
                                "db_company_code": cur_cfg.get("db_company_code", ""), "price_date": cur_cfg.get("price_date", ""),
                            })
                            if r.status_code == 200: st.success("LLM & 字段配置已保存"), st.rerun()
                            else: st.error(r.json().get("detail") or "保存失败")

                with st.expander(f"🗄️ 数据库直连配置", expanded=False):
                    # 显示当前数据源模式
                    cur_source_mode = cur_cfg.get("source_mode", "feishu")
                    mode_label = "飞书多维表格" if cur_source_mode != "db" else "DB 直连"
                    st.caption(f"当前数据源模式：**{mode_label}**（保存 DB 配置后将自动切换为 DB 直连）")

                    with st.form(f"db_cfg_{tenant_id}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            db_url = st.text_input("数据库连接串", value=cur_cfg.get("db_url", ""),
                                placeholder="192.168.80.102:3433/db1790", key=f"db_url_{tenant_id}")
                            db_username = st.text_input("数据库用户名", value=cur_cfg.get("db_username", ""), key=f"db_user_{tenant_id}")
                            db_password = st.text_input("数据库密码（留空=不改，当前：" + ("已设置" if cur_cfg.get("has_db_password") else "未设置") + "）",
                                type="password", value="", key=f"db_pass_{tenant_id}")
                        with c2:
                            db_company_code = st.text_input("ERP 公司代码（gsdm）", value=cur_cfg.get("db_company_code", ""),
                                placeholder="如 62816，脚本查询时需要此值", key=f"db_cc_{tenant_id}")
                            price_date = st.text_input("报价日期（留空则取当日）", value=cur_cfg.get("price_date", ""),
                                placeholder="如 2026-06-12，留空自动取当日", key=f"price_date_{tenant_id}")
                        # 数据源模式切换
                        source_mode = st.radio(
                            "数据源模式",
                            [("飞书表格", "feishu"), ("DB 直连", "db")],
                            format_func=lambda x: x[0],
                            index=0 if cur_source_mode != "db" else 1,
                            horizontal=True,
                            key=f"source_mode_{tenant_id}",
                        )
                        c1, c2, _ = st.columns([1, 1, 3])
                        with c1:
                            save_db = st.form_submit_button("💾 保存 DB 配置", type="primary")
                        with c2:
                            validate_btn = st.form_submit_button("🔍 连接测试")
                        if save_db:
                            r = api_put(f"/api/platform/tenants/{tenant_id}/config", {
                                "feishu_app_id": cur_cfg.get("feishu_app_id", ""), "feishu_app_secret": "",
                                "feishu_app_token": cur_cfg.get("feishu_app_token", ""), "feishu_table_id": cur_cfg.get("feishu_table_id", ""),
                                "feishu_field_name": cur_cfg.get("feishu_field_name", "商品名称"), "feishu_price_field_name": cur_cfg.get("feishu_price_field_name", "报价"),
                                "llm_provider": cur_cfg.get("llm_provider", "gemini"), "llm_api_key": "", "llm_model": cur_cfg.get("llm_model", ""),
                                "db_url": db_url.strip(), "db_username": db_username.strip(), "db_password": db_password.strip(),
                                "db_company_code": db_company_code.strip(), "price_date": price_date.strip(),
                                "source_mode": source_mode[1],
                            })
                            if r.status_code == 200: st.success("DB 配置已保存，数据源模式已切换"), st.rerun()
                            else: st.error(r.json().get("detail") or "保存失败")
                        if validate_btn:
                            api_put(f"/api/platform/tenants/{tenant_id}/config", {
                                "feishu_app_id": cur_cfg.get("feishu_app_id", ""), "feishu_app_secret": "",
                                "feishu_app_token": cur_cfg.get("feishu_app_token", ""), "feishu_table_id": cur_cfg.get("feishu_table_id", ""),
                                "feishu_field_name": cur_cfg.get("feishu_field_name", "商品名称"), "feishu_price_field_name": cur_cfg.get("feishu_price_field_name", "报价"),
                                "llm_provider": cur_cfg.get("llm_provider", "gemini"), "llm_api_key": "", "llm_model": cur_cfg.get("llm_model", ""),
                                "db_url": db_url.strip(), "db_username": db_username.strip(), "db_password": db_password.strip(),
                                "db_company_code": db_company_code.strip(), "price_date": price_date.strip(),
                                "source_mode": source_mode[1],
                            })
                            vr = api_post(f"/api/platform/tenants/{tenant_id}/validate-db")
                            if vr.status_code == 200:
                                vdata = vr.json()
                                if vdata.get("ok"):
                                    st.success(f"✅ {vdata.get('message')}")
                                else:
                                    st.error(f"❌ {vdata.get('message')}")
                            else:
                                st.error("校验请求失败")

                with st.expander(f"💰 报价等级配置", expanded=False):
                    st.caption("配置报价等级（如价格1、价格2、价格3），勾选后商户平台可展示对应报价。")
                    cur_price_fields = cur_cfg.get("price_fields") or []
                    with st.form(f"price_fields_cfg_{tenant_id}"):
                        pf_labels = ["价格1", "价格2", "价格3"]
                        pf_default_fields = ["jg2", "jg4", "jg5"]
                        new_price_fields = []
                        for idx in range(3):
                            existing = cur_price_fields[idx] if idx < len(cur_price_fields) else {}
                            c1, c2, c3 = st.columns([2, 2, 1])
                            with c1:
                                label = st.text_input(f"报价名称", value=existing.get("label", pf_labels[idx]),
                                    key=f"pf_label_{tenant_id}_{idx}", placeholder=pf_labels[idx])
                            with c2:
                                field = st.text_input(f"对应字段", value=existing.get("field", pf_default_fields[idx]),
                                    key=f"pf_field_{tenant_id}_{idx}", placeholder=pf_default_fields[idx])
                            with c3:
                                enabled = st.checkbox("启用", value=existing.get("enabled", False),
                                    key=f"pf_enabled_{tenant_id}_{idx}")
                            new_price_fields.append({"label": label.strip() or pf_labels[idx], "field": field.strip() or pf_default_fields[idx], "enabled": enabled})
                        if st.form_submit_button("💾 保存报价配置", type="primary"):
                            r = api_put(f"/api/platform/tenants/{tenant_id}/config", {
                                "feishu_app_id": cur_cfg.get("feishu_app_id", ""), "feishu_app_secret": "",
                                "feishu_app_token": cur_cfg.get("feishu_app_token", ""), "feishu_table_id": cur_cfg.get("feishu_table_id", ""),
                                "feishu_field_name": cur_cfg.get("feishu_field_name", "商品名称"), "feishu_price_field_name": cur_cfg.get("feishu_price_field_name", "报价"),
                                "llm_provider": cur_cfg.get("llm_provider", "gemini"), "llm_api_key": "", "llm_model": cur_cfg.get("llm_model", ""),
                                "db_url": cur_cfg.get("db_url", ""), "db_username": cur_cfg.get("db_username", ""), "db_password": "",
                                "db_company_code": cur_cfg.get("db_company_code", ""),
                                "price_fields": new_price_fields,
                            })
                            if r.status_code == 200: st.success("报价配置已保存"), st.rerun()
                            else: st.error(r.json().get("detail") or "保存失败")

    # ---- 新增商户 ----
    with st.container():
        _section_title("➕ 新增商户（默认创建 admin/123456 账号）")
        with st.form("new_tenant"):
            c1, c2 = st.columns(2)
            with c1:
                code = st.text_input("公司代码（唯一）")
                name = st.text_input("商户名称")
                is_active = st.selectbox("启用状态", [("启用", 1), ("停用", 0)], format_func=lambda x: x[0])
                source_mode = st.selectbox("数据源模式", [("飞书表格", "feishu"), ("DB 直连", "db")], format_func=lambda x: x[0])
            with c2:
                contact = st.text_input("联系人", "")
                contact_info = st.text_input("联系方式", "")

            st.markdown("##### 📘 飞书配置（选填，也可创建后单独维护）")
            cf1, cf2 = st.columns(2)
            with cf1:
                n_feishu_app_id = st.text_input("APP ID", value="", key="new_fs_appid")
                n_feishu_app_secret = st.text_input("APP Secret", type="password", value="", key="new_fs_secret")
            with cf2:
                n_feishu_app_token = st.text_input("APP Token", value="", key="new_fs_token")
                n_feishu_table_id = st.text_input("Table ID", value="", key="new_fs_tid")

            st.markdown("##### 🤖 LLM 配置（选填）")
            cl1, cl2 = st.columns(2)
            with cl1:
                n_field_name = st.text_input("商品名称列字段名", value="商品名称", key="new_llm_fn")
                n_llm_provider = st.selectbox("LLM 提供方", ["deepseek", "gemini", "disabled"], key="new_llm_prov")
                n_llm_model = st.text_input("LLM 模型名", value="DeepSeek-V4-Flash", key="new_llm_mdl")
            with cl2:
                n_price_field = st.text_input("报价列字段名", value="报价", key="new_llm_pf")
                n_llm_key = st.text_input("LLM API Key", type="password", value="", key="new_llm_key")

            st.markdown("##### 🗄️ DB 直连配置（选填）")
            cd1, cd2 = st.columns(2)
            with cd1:
                n_db_url = st.text_input("数据库连接串", value="", placeholder="192.168.80.102:3433/db1790", key="new_db_url")
                n_db_username = st.text_input("数据库用户名", value="", key="new_db_user")
                n_db_password = st.text_input("数据库密码", type="password", value="", key="new_db_pass")
            with cd2:
                n_db_company_code = st.text_input("ERP 公司代码（gsdm）", value="", placeholder="如 62816", key="new_db_cc")
                n_price_date = st.text_input("报价日期（留空则取当日）", value="", placeholder="如 2026-06-12", key="new_price_date")

            if st.form_submit_button("创建商户", use_container_width=True, type="primary"):
                if not code or not name:
                    st.error("公司代码和商户名称不能为空")
                else:
                    r = api_post("/api/platform/tenants", json={
                        "code": code.strip(), "name": name.strip(),
                        "is_active": is_active[1], "source_mode": source_mode[1],
                        "contact": contact, "contact_info": contact_info,
                    })
                    if r.status_code == 200:
                        new_id = r.json().get("id")
                        if new_id:
                            # 同步写入飞书/LLM/DB配置
                            api_put(f"/api/platform/tenants/{new_id}/config", {
                                "feishu_app_id": n_feishu_app_id.strip(), "feishu_app_secret": n_feishu_app_secret.strip(),
                                "feishu_app_token": n_feishu_app_token.strip(), "feishu_table_id": n_feishu_table_id.strip(),
                                "feishu_field_name": n_field_name.strip() or "商品名称", "feishu_price_field_name": n_price_field.strip() or "报价",
                                "llm_provider": n_llm_provider, "llm_api_key": n_llm_key.strip(), "llm_model": n_llm_model.strip(),
                                "db_url": n_db_url.strip(), "db_username": n_db_username.strip(), "db_password": n_db_password.strip(),
                                "db_company_code": n_db_company_code.strip(), "price_date": n_price_date.strip(),
                            })
                        st.success(f"商户 {code} 已创建，默认管理员 admin/123456")
                        st.rerun()
                    else:
                        st.error(r.json().get("detail") or "创建失败")

    # ---- 删除商户 ----
    with st.container():
        _section_title("🗑 删除已有商户")
        if not rows:
            st.info("暂无可删除商户")
        else:
            picked = st.selectbox(
                "选择要删除的商户",
                [f"{r['code']} — {r['name']}" for r in rows],
                key="delete_tenant_pick",
            )
            if picked:
                cur = next((r for r in rows if f"{r['code']} — {r['name']}" == picked), None)
                if cur and st.button(f"删除「{cur.get('name')}」", type="secondary", use_container_width=True):
                    r = api_delete(f"/api/platform/tenants/{cur['id']}")
                    if r.status_code == 200:
                        st.success("已删除")
                        st.rerun()
                    else:
                        st.error(r.json().get("detail") or "删除失败")



# ----------------------------- 平台后台：全局报价监控 -----------------------------
def page_platform_monitor():
    st.subheader("📡 全局报价监控（查看任一商户的报价）")
    resp = api_get("/api/platform/tenants")
    if resp.status_code != 200:
        st.error(resp.json().get("detail") or "加载失败")
        return
    rows = resp.json()
    # 过滤掉平台内部租户（byadmin / platform），运营平台账号不应出现在报价监控中
    cfgd = [r for r in rows if (r.get("feishu_configured") or r.get("db_configured")) and r.get("code", "").lower() not in ("byadmin", "platform")]
    if not cfgd:
        st.info("暂无已配置数据源凭证的商户")
        return
    # 下拉框显示商户名称
    merchant_options = {f"[{r['code']}] {r['name']}": r for r in cfgd}
    picked_label = st.selectbox("选择商户", list(merchant_options.keys()))
    if not picked_label:
        return
    picked_merchant = merchant_options[picked_label]
    picked = picked_merchant["code"]

    # 获取该商户的报价等级配置
    config_resp = api_get(f"/api/platform/tenants/{picked_merchant['id']}/config")
    cur_cfg = config_resp.json() if config_resp.status_code == 200 else {}
    price_fields = cur_cfg.get("price_fields") or []
    enabled_price_fields = [pf for pf in price_fields if pf.get("enabled")]

    tab1, tab2 = st.tabs(["📋 报价列表", "🤖 AI 批量查价"])

    # 刷新缓存按钮
    col_btn1, col_btn2 = st.columns([1, 5])
    with col_btn1:
        if st.button("🔄 刷新缓存", key="platform_refresh_cache", help="清除缓存并重新从数据源拉取最新报价数据"):
            r = api_post(f"/api/platform/tenants/{picked}/refresh-cache", {})
            if r.status_code == 200:
                st.success(r.json().get("message", "缓存刷新成功"))
            else:
                st.error(r.json().get("detail") or "刷新失败")
    with col_btn2:
        st.caption("更新商户数据源配置后，点击此按钮立即刷新缓存数据")

    with tab1:
        with st.container():
            _section_title(f"🔎 报价列表（商户：{picked_merchant['name']}）")
            r = api_get(f"/api/platform/tenants/{picked}/rows")
            if r.status_code != 200:
                st.error(r.json().get("detail") or "加载失败")
            else:
                data = r.json()
                if not data.get("rows"):
                    st.info("暂无记录")
                else:
                    df = pd.DataFrame(
                        data["rows"],
                        columns=data["columns"] or data["rows"][0].keys()
                    )
                    # 库存为 0 的商品整行显示橙色
                    stock_col = None
                    for c in (data["columns"] or data["rows"][0].keys()):
                        if "库存" in str(c):
                            stock_col = c
                            break
                    if stock_col:
                        def _style_stock_zero(row):
                            styles = [''] * len(row)
                            try:
                                val = str(row.get(stock_col, '')).strip()
                                if val == '0':
                                    for i in range(len(row)):
                                        styles[i] = 'color: #e67e22; font-weight: 500'
                            except Exception:
                                pass
                            return styles
                        styled_df = df.style.apply(_style_stock_zero, axis=1)
                        st.dataframe(styled_df, use_container_width=True, height=540, hide_index=True)
                    else:
                        st.dataframe(df, use_container_width=True, height=540, hide_index=True)
                    # 显示商品总数和最后刷新时间
                    total_count = data.get("total", len(df))
                    last_synced = data.get("last_synced_at")
                    time_info = ""
                    if last_synced:
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(last_synced)
                            time_info = f" · 最后更新：{dt.strftime('%Y-%m-%d %H:%M:%S')}"
                        except Exception:
                            time_info = f" · 最后更新：{last_synced}"
                    st.caption(f"共 {total_count} 条商品{time_info}")

    with tab2:
        with st.container():
            _section_title("🚀 智能批量查价")
            # 报价等级选择
            price_field = None
            if len(enabled_price_fields) > 1:
                pf_options = {pf["label"]: pf["field"] for pf in enabled_price_fields}
                pf_pick = st.radio("选择报价等级", list(pf_options.keys()), horizontal=True, key="platform_monitor_pf")
                price_field = pf_options.get(pf_pick)
            elif len(enabled_price_fields) == 1:
                price_field = enabled_price_fields[0]["field"]
            # 清空标记：在 text_area 渲染前处理，避免 Streamlit 报错
            if st.session_state.get("_clear_platform_monitor"):
                st.session_state["platform_monitor_text"] = ""
                st.session_state["_clear_platform_monitor"] = False
            text = st.text_area(
                "粘贴商品描述（每行一条）",
                height=180,
                placeholder="A3i星辰紫6+128一台\n红米K90暗影黑8+128三台",
                key="platform_monitor_text",
            )
            c1, c2 = st.columns([1, 4])
            with c1:
                if st.button("🗑 清空", use_container_width=True, key="platform_monitor_clear"):
                    st.session_state["_clear_platform_monitor"] = True
                    st.rerun()
            with c2:
                if st.button("🚀 智能查询", use_container_width=True, type="primary"):
                    if not text.strip():
                        st.warning("请输入至少一条商品描述")
                    else:
                        body = {"text": text}
                        if price_field:
                            body["price_field"] = price_field
                        r = api_post(f"/api/platform/tenants/{picked}/check-price", body)
                        if r.status_code != 200:
                            st.error(r.json().get("detail") or "查询失败")
                        else:
                            data = r.json()
                            st.markdown(
                                '<div class="erp-section-title">📋 输出结果（可复制）</div>',
                                unsafe_allow_html=True,
                            )
                            st.code(data["result"], language=None)
                            detail = []
                            for d in data["details"]:
                                if d.get("multi_matches"):
                                    is_first = True
                                    total = len(d["multi_matches"])
                                    for idx, m in enumerate(d["multi_matches"]):
                                        detail.append({
                                            "原始": d["original"] if is_first else "",
                                            "关键词": " / ".join(m["keywords"]) if m.get("keywords") else "",
                                            "命中商品": m.get("matched_name") or "-",
                                            "报价": m.get("price") or "-",
                                            "匹配": f"✅ ({idx+1}/{total})",
                                        })
                                        is_first = False
                                else:
                                    detail.append({
                                        "原始": d["original"],
                                        "关键词": " / ".join(d["keywords"]) if d["keywords"] else "",
                                        "命中商品": d.get("matched_name") or "-",
                                        "报价": d.get("price") or "-",
                                        "匹配": "✅" if d.get("matched") else "❌",
                                    })
                            st.dataframe(pd.DataFrame(detail), use_container_width=True, hide_index=True)
                            # 显示最后同步时间
                            last_synced = data.get("last_synced_at")
                            if last_synced:
                                try:
                                    from datetime import datetime
                                    dt = datetime.fromisoformat(last_synced)
                                    time_info = f"报价数据更新：{dt.strftime('%Y-%m-%d %H:%M:%S')}"
                                except Exception:
                                    time_info = f"报价数据更新：{last_synced}"
                                st.caption(time_info)



# ----------------------------- 商户后台：员工管理 -----------------------------
def page_user_management():
    st.subheader("👥 员工管理")
    
    # 加载员工列表
    resp = api_get("/api/admin/users")
    if resp.status_code != 200:
        st.error(resp.json().get("detail") or "加载失败")
        return
    rows = resp.json()
    
    # 加载角色列表（供编辑/创建时选择）
    roles_resp = api_get("/api/admin/roles")
    roles = roles_resp.json() if roles_resp.status_code == 200 else []
    # 过滤掉 platform_admin
    roles = [r for r in roles if r["name"] != "platform_admin"]
    
    # ── 当前员工列表 ──
    with st.container():
        _section_title("📋 当前员工列表")
        if rows:
            df = pd.DataFrame(rows)
            df["role"] = df["role"].map(
                {r["name"]: r["name"] for r in roles}
            ).fillna(df["role"])
            display = df[["id", "username", "display_name", "role", "tenant_code"]].rename(
                columns={"id": "ID", "username": "用户名", "display_name": "姓名", "role": "角色", "tenant_code": "公司代码"}
            )
            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", width="small"),
                    "用户名": st.column_config.TextColumn("用户名", width="medium"),
                    "姓名": st.column_config.TextColumn("姓名", width="medium"),
                    "角色": st.column_config.TextColumn("角色", width="medium"),
                    "公司代码": st.column_config.TextColumn("公司代码", width="medium"),
                },
            )
        else:
            st.info("暂无员工账号")

    st.markdown("---")

    # ── 编辑员工 ──
    if rows:
        with st.container():
            _section_title("✏️ 编辑员工")
            edit_pick = st.selectbox(
                "选择要编辑的员工",
                [r["username"] for r in rows],
                key="edit_pick",
            )
            edit_user = next((r for r in rows if r["username"] == edit_pick), None)
            if edit_user:
                with st.form("edit_user_form"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        new_uname = st.text_input("用户名", value=edit_user["username"])
                    with c2:
                        new_dname = st.text_input("姓名", value=edit_user.get("display_name", ""))
                    with c3:
                        role_opts = {r["name"]: r["description"] or r["name"] for r in roles}
                        new_role = st.selectbox(
                            "角色",
                            options=list(role_opts.keys()),
                            index=list(role_opts.keys()).index(edit_user["role"]) if edit_user["role"] in role_opts else 0,
                            format_func=lambda x: f"{x}（{role_opts[x]}）" if role_opts[x] != x else x,
                        )
                    if st.form_submit_button("💾 保存修改", use_container_width=True, type="primary"):
                        body = {}
                        if new_uname.strip() and new_uname.strip() != edit_user["username"]:
                            body["username"] = new_uname.strip()
                        if new_dname.strip() != (edit_user.get("display_name") or ""):
                            body["display_name"] = new_dname.strip()
                        if new_role != edit_user["role"]:
                            body["role"] = new_role
                        if not body:
                            st.info("未做任何修改")
                        else:
                            r = api_put(f"/api/admin/users/{edit_user['id']}", body)
                            if r.status_code == 200:
                                st.success("员工信息已更新")
                                st.rerun()
                            else:
                                st.error(r.json().get("detail") or "保存失败")

    # ── 新增员工 ──
    with st.container():
        _section_title("➕ 新增员工账号")
        with st.form("new_user"):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                uname = st.text_input("用户名")
            with c2:
                dname = st.text_input("姓名")
            with c3:
                upwd = st.text_input("初始密码（>=6位）", type="password")
            with c4:
                role_opts = {r["name"]: r["description"] or r["name"] for r in roles}
                urole = st.selectbox(
                    "角色",
                    options=list(role_opts.keys()),
                    format_func=lambda x: f"{x}（{role_opts[x]}）" if role_opts[x] != x else x,
                )
            if st.form_submit_button("➕ 创建账号", use_container_width=True, type="primary"):
                if not uname or not upwd or len(upwd) < 6:
                    st.error("用户名和密码（>=6位）不可为空")
                else:
                    r = api_post("/api/admin/users", {"username": uname, "display_name": dname.strip(), "password": upwd, "role": urole})
                    if r.status_code == 200:
                        st.success("已创建")
                        st.rerun()
                    else:
                        st.error(r.json().get("detail") or "创建失败")

    # ── 重置密码 / 删除用户 ──
    if rows:
        st.markdown("---")
        with st.container():
            _section_title("🔑 重置密码 / 删除用户")
            pick = st.selectbox(
                "选择员工",
                [r["username"] for r in rows],
                key="reset_pick",
            )
            c1, c2 = st.columns(2)
            with c1:
                with st.form("reset_pwd"):
                    np_ = st.text_input("新密码（>=6位）", type="password")
                    if st.form_submit_button("🔄 重置密码", use_container_width=True):
                        if not np_ or len(np_) < 6:
                            st.error("新密码至少 6 位")
                        else:
                            r = api_post(
                                "/api/admin/users/reset-password",
                                {"username": pick, "new_password": np_},
                            )
                            if r.status_code == 200:
                                st.success("已重置")
                            else:
                                st.error(r.json().get("detail") or "失败")
            with c2:
                if st.button(
                    f"🗑 删除 {pick}",
                    type="secondary",
                    use_container_width=True,
                ):
                    uid = next((r["id"] for r in rows if r["username"] == pick), None)
                    if uid is None:
                        st.error("未找到")
                    else:
                        r = api_delete(f"/api/admin/users/{uid}")
                        if r.status_code == 200:
                            st.success("已删除")
                            st.rerun()
                        else:
                            st.error(r.json().get("detail") or "失败")


# ----------------------------- 商户后台：飞书/LLM 系统参数 -----------------------------
def page_admin_config():
    st.subheader("⚙️ 系统参数配置（飞书 / LLM）")
    resp = api_get("/api/admin/config")
    if resp.status_code != 200:
        st.error(resp.json().get("detail") or "加载失败")
        return
    cur = resp.json()

    source_mode = cur.get("source_mode", "feishu")
    with st.container():
        _section_title("📡 当前数据源模式")
        mode_label = "飞书多维表格" if source_mode != "db" else "DB 直连"
        st.info(f"当前模式：**{mode_label}** （如需切换，请联系运营平台管理员在「商户资质管理」中修改）")

    # —— 飞书配置：仅在飞书模式下可编辑 ——
    if source_mode != "db":
        with st.container():
            _section_title("📘 飞书多维表格配置")
            with st.form("feishu_cfg"):
                c1, c2 = st.columns(2)
                with c1:
                    feishu_app_id = st.text_input("APP ID", value=cur.get("feishu_app_id", ""))
                    feishu_app_secret = st.text_input(
                        "APP Secret（留空=不改，当前：" + ("已设置" if cur.get("has_app_secret") else "未设置") + "）",
                        type="password",
                        value="",
                    )
                with c2:
                    feishu_app_token = st.text_input("APP Token（链接中 bitable 后的串）", value=cur.get("feishu_app_token", ""))
                    feishu_table_id = st.text_input("Table ID", value=cur.get("feishu_table_id", ""))
                save_feishu = st.form_submit_button("💾 保存飞书配置", use_container_width=True, type="primary")
    else:
        st.info("当前为 DB 直连模式，飞书配置不可编辑。DB 连接信息由运营平台统一管理。")
        save_feishu = False
        feishu_app_id = feishu_app_secret = feishu_app_token = feishu_table_id = ""

    with st.container():
        _section_title("🤖 LLM 与字段映射")
        with st.form("llm_cfg"):
            c1, c2 = st.columns(2)
            with c1:
                field_name = st.text_input("商品名称列字段名", value=cur.get("feishu_field_name", "商品名称"))
                llm_provider = st.selectbox(
                    "LLM 提供方",
                    ["deepseek", "gemini", "disabled"],
                    index=["deepseek", "gemini", "disabled"].index(cur.get("llm_provider", "deepseek")),
                )
                llm_model = st.text_input("LLM 模型名", value=cur.get("llm_model", "DeepSeek-V4-Flash"))
            with c2:
                price_field = st.text_input("报价列字段名", value=cur.get("feishu_price_field_name", "报价"))
                llm_key = st.text_input(
                    "LLM API Key（留空=不改，当前：" + ("已设置" if cur.get("has_llm_api_key") else "未设置") + "）",
                    type="password",
                    value="",
                )
            save_llm = st.form_submit_button("💾 保存 LLM 与字段配置", use_container_width=True, type="primary")

    if save_feishu:
        r = api_put("/api/admin/config", {
            "feishu_app_id": feishu_app_id.strip(), "feishu_app_secret": feishu_app_secret.strip(),
            "feishu_app_token": feishu_app_token.strip(), "feishu_table_id": feishu_table_id.strip(),
            "feishu_field_name": cur.get("feishu_field_name", "商品名称"), "feishu_price_field_name": cur.get("feishu_price_field_name", "报价"),
            "llm_provider": cur.get("llm_provider", "gemini"), "llm_api_key": "", "llm_model": cur.get("llm_model", ""),
            "db_url": cur.get("db_url", ""), "db_username": cur.get("db_username", ""), "db_password": "",
            "db_company_code": cur.get("db_company_code", ""), "price_date": cur.get("price_date", ""),
        })
        if r.status_code == 200: st.success("飞书配置已保存"), st.rerun()
        else: st.error(r.json().get("detail") or "保存失败")

    if save_llm:
        r = api_put("/api/admin/config", {
            "feishu_app_id": cur.get("feishu_app_id", ""), "feishu_app_secret": "",
            "feishu_app_token": cur.get("feishu_app_token", ""), "feishu_table_id": cur.get("feishu_table_id", ""),
            "feishu_field_name": field_name.strip() or "商品名称", "feishu_price_field_name": price_field.strip() or "报价",
            "llm_provider": llm_provider, "llm_api_key": llm_key.strip(), "llm_model": llm_model.strip() or "DeepSeek-V4-Flash",
            "db_url": cur.get("db_url", ""), "db_username": cur.get("db_username", ""), "db_password": "",
            "db_company_code": cur.get("db_company_code", ""), "price_date": cur.get("price_date", ""),
        })
        if r.status_code == 200: st.success("LLM & 字段配置已保存"), st.rerun()
        else: st.error(r.json().get("detail") or "保存失败")


# ----------------------------- 审计日志页面 -----------------------------
def page_audit_logs():
    st.subheader("📋 操作审计日志")

    role = st.session_state.get("role", "")
    page_size = 100

    # 分页状态
    if "audit_page" not in st.session_state:
        st.session_state["audit_page"] = 1
    if "audit_triggered" not in st.session_state:
        st.session_state["audit_triggered"] = False

    # ---- 查询条件卡片 ----
    with st.container():
        st.markdown("##### 🔍 查询条件")

        # 第一行：商户选择（全宽）
        if role == "platform_admin":
            resp = api_get("/api/platform/tenants")
            tenants = resp.json() if resp.status_code == 200 else []
            tenant_options = ["请选择商户"] + [f"[{t['code']}]  {t['name']}" for t in tenants]
            picked = st.selectbox(
                "选择商户",
                tenant_options,
                key="audit_tenant_pick",
                label_visibility="collapsed",
            )
            if picked and picked != "请选择商户":
                tenant_code = picked.split("]")[0].replace("[", "").strip()
            else:
                tenant_code = "__none__"
        else:
            tenant_code = ""  # tenant_admin 自动绑定

        # 第二行：日期 + 操作类型 + 查询按钮
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
        with c1:
            date_from = st.date_input("开始日期", value=date.today(), key="audit_date_from")
        with c2:
            date_to = st.date_input("结束日期", value=date.today(), key="audit_date_to")
        with c3:
            action_labels_map = {
                "全部操作": "", "登录": "login", "退出": "logout",
                "智能查价": "price_check", "报价看板": "dashboard_view",
                "创建员工": "user_create", "编辑员工": "user_update", "删除员工": "user_delete",
                "创建角色": "role_create", "编辑角色": "role_update", "删除角色": "role_delete",
            }
            action_filter = st.selectbox("操作类型", list(action_labels_map.keys()), key="audit_action")
        with c4:
            st.markdown("<br>", unsafe_allow_html=True)  # 对齐按钮到同一行
            if st.button("🔍 查询", use_container_width=True, type="primary", key="audit_search_btn"):
                if tenant_code == "__none__":
                    st.warning("请先选择商户")
                else:
                    st.session_state["audit_triggered"] = True
                    st.session_state["audit_page"] = 1
                    st.rerun()

    # ---- 仅在用户点击查询后展示结果 ----
    if not st.session_state["audit_triggered"]:
        st.info("👆 请选择筛选条件后点击「查询」按钮")
        return

    if tenant_code == "__none__":
        st.info("请先选择一个商户，再点击查询")
        return

    cur_page = st.session_state.get("audit_page", 1)

    # 构建参数
    params = {"page": cur_page, "page_size": page_size}
    if tenant_code:
        params["tenant_code"] = tenant_code
    action_val = action_labels_map.get(action_filter, "")
    if action_val:
        params["action"] = action_val
    if date_from:
        params["date_from"] = str(date_from)
    if date_to:
        params["date_to"] = str(date_to)

    resp = api_get("/api/admin/audit-logs", params=params)
    if resp.status_code != 200:
        st.error(resp.json().get("detail") or "查询失败")
        return
    result = resp.json()
    rows = result.get("items", [])
    total = result.get("total", 0)
    action_labels_display = {v: k for k, v in action_labels_map.items()}

    # ---- 结果统计 ----
    total_pages = max(1, (total + page_size - 1) // page_size)
    st.caption(f"共 **{total}** 条记录 | 第 **{cur_page}/{total_pages}** 页")

    # ---- 表格 ----
    data = []
    for r in rows:
        act = r.get("action", "")
        data.append({
            "时间": (r.get("created_at", "") or "")[:19],
            "商户": r.get("tenant_code", ""),
            "用户": r.get("username", ""),
            "角色": r.get("role", ""),
            "操作": action_labels_display.get(act, act),
            "对象": (r.get("target") or "")[:80],
        })
    display_columns = ["时间", "用户", "角色", "操作", "对象"]
    if role == "platform_admin":
        display_columns = ["时间", "商户", "用户", "角色", "操作", "对象"]

    if data:
        df = pd.DataFrame(data, columns=display_columns)
        st.dataframe(df, use_container_width=True, hide_index=True, height=450)
    else:
        st.info("暂无符合条件的审计日志记录")

    # ---- 分页按钮 ----
    c_prev, c_next, c_empty = st.columns([1, 1, 5])
    with c_prev:
        if cur_page > 1:
            if st.button("⬅ 上一页", use_container_width=True, key="audit_prev"):
                st.session_state["audit_page"] = cur_page - 1
                st.rerun()
    with c_next:
        if cur_page < total_pages:
            if st.button("下一页 ➡", use_container_width=True, key="audit_next"):
                st.session_state["audit_page"] = cur_page + 1
                st.rerun()


# ----------------------------- 业务员：报价看板（默认不查询，点击按钮才加载） -----------------------------
def page_dashboard():
    st.subheader("📊 报价看板")

    # 顶部信息卡 + 主刷新按钮
    with st.container():
        c1, c2 = st.columns([5, 1])
        with c1:
            _section_title("🛒 当前商品库")
            st.caption("全表缓存 5 分钟；首次进入请点击右侧按钮加载。按关键词筛选后自动搜索。")
        with c2:
            if st.button("🔄 读取报价", use_container_width=True, type="primary"):
                st.session_state["_dashboard_force"] = True

    if "dashboard_page" not in st.session_state:
        st.session_state["dashboard_page"] = 1
    if "dashboard_kw" not in st.session_state:
        st.session_state["dashboard_kw"] = ""
    if "dashboard_price1_filter" not in st.session_state:
        st.session_state["dashboard_price1_filter"] = "gt0"  # 默认大于0
    if "dashboard_stock_filter" not in st.session_state:
        st.session_state["dashboard_stock_filter"] = "all"   # 默认全部

    # 筛选条：放在卡片中
    with st.container():
        _section_title("🔎 筛选条件")
        c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
        with c1:
            new_kw = st.text_input(
                "关键词筛选（模糊匹配任意列）",
                value=st.session_state.get("dashboard_kw", ""),
                placeholder="例如：A3i / 星辰紫 / 16+512",
                label_visibility="collapsed",
            )
        with c2:
            new_price1_filter = st.selectbox(
                "价格1",
                options=["gt0", "eq0", "all"],
                format_func=lambda x: {"gt0": "价格1 > 0", "eq0": "价格1 = 0", "all": "价格1 全部"}[x],
                index=["gt0", "eq0", "all"].index(st.session_state.get("dashboard_price1_filter", "gt0")),
            )
        with c3:
            new_stock_filter = st.selectbox(
                "库存数量",
                options=["all", "gt0", "eq0"],
                format_func=lambda x: {"all": "库存 全部", "gt0": "库存 > 0", "eq0": "库存 = 0"}[x],
                index=["all", "gt0", "eq0"].index(st.session_state.get("dashboard_stock_filter", "all")),
            )
        with c4:
            page_size = st.selectbox(
                "每页条数",
                options=[100, 50, 200, 500],
                index=0,
            )

    kw_changed = new_kw != st.session_state.get("dashboard_kw", "")
    price1_changed = new_price1_filter != st.session_state.get("dashboard_price1_filter", "gt0")
    stock_changed = new_stock_filter != st.session_state.get("dashboard_stock_filter", "all")
    if kw_changed or price1_changed or stock_changed:
        st.session_state["dashboard_kw"] = new_kw
        st.session_state["dashboard_price1_filter"] = new_price1_filter
        st.session_state["dashboard_stock_filter"] = new_stock_filter
        st.session_state["dashboard_page"] = 1

    # 判定是否触发查询：用户主动点刷新，或切换页面大小、或关键词变化（已有数据时）
    force = st.session_state.pop("_dashboard_force", False)
    has_cache = bool(st.session_state.get("_dashboard_rows"))

    # 关键词变化 / 翻页时，如果已有缓存则直接从缓存里做筛选（避免慢 API 再次调用）
    query_triggered = force or (not has_cache and new_kw.strip()) or (has_cache and (price1_changed or stock_changed))
    # 如果尚未拉过数据，且有关键词，也自动查询一次

    page = int(st.session_state.get("dashboard_page", 1))

    if query_triggered:
        params = {"page": page, "page_size": int(page_size)}
        if force:
            params["refresh"] = "1"
        if new_kw.strip():
            params["keyword"] = new_kw.strip()
        # 传递筛选条件到后端
        params["price1_filter"] = st.session_state.get("dashboard_price1_filter", "gt0")
        params["stock_filter"] = st.session_state.get("dashboard_stock_filter", "all")

        with st.container():
            _section_title("📋 商品列表")
            with st.spinner("正在读取报价数据...（首次会全量拉取，可能需要一会儿）"):
                try:
                    resp = requests.get(
                        f"{API_BASE}/api/feishu/rows",
                        headers=_headers(),
                        params=params,
                        timeout=300,  # 留给后端 5 分钟
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"读取失败：{exc}")
                    st.caption("如持续超时，可尝试缩小关键词范围，或联系管理员检查数据源配置。")
                    return
            if resp.status_code != 200:
                try:
                    st.error(resp.json().get("detail") or "读取失败")
                except Exception:  # noqa: BLE001
                    st.error("读取失败：" + resp.text)
                return

            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                st.error("响应格式异常，请检查后端服务")
                return

            rows = data.get("rows") or []
            cols = data.get("columns") or []
            total = int(data.get("total") or 0)
            cur_page = int(data.get("page") or 1)
            cur_ps = int(data.get("page_size") or 100)
            total_pages = max((total + cur_ps - 1) // cur_ps, 1) if total else 1
            sync_status = data.get("sync_status", "ok")
            sync_count = data.get("sync_count", 0)
            last_synced_at = data.get("last_synced_at")

            # 存入会话缓存，以便后续翻页、关键词变化时直接读取
            st.session_state["_dashboard_rows"] = rows
            st.session_state["_dashboard_cols"] = cols
            st.session_state["_dashboard_total"] = total
            st.session_state["_dashboard_cur_page"] = cur_page
            st.session_state["_dashboard_total_pages"] = total_pages
            st.session_state["_dashboard_page_size"] = cur_ps
            st.session_state["_dashboard_sync_status"] = sync_status
            st.session_state["_dashboard_sync_count"] = sync_count
            st.session_state["_dashboard_last_synced_at"] = last_synced_at
    else:
        # 展示占位（或已有缓存结果）
        with st.container():
            _section_title("📋 商品列表")
            if not has_cache:
                st.info("尚未加载数据。请先点击右上角「🔄 读取报价」，或在上方输入关键词直接搜索。")
                return
            rows = st.session_state.get("_dashboard_rows") or []
            cols = st.session_state.get("_dashboard_cols") or []
            total = int(st.session_state.get("_dashboard_total") or 0)
            cur_page = int(st.session_state.get("_dashboard_cur_page") or 1)
            cur_ps = int(st.session_state.get("_dashboard_page_size") or 100)
            total_pages = int(st.session_state.get("_dashboard_total_pages") or 1)

    if not rows:
        sync_status = st.session_state.get("_dashboard_sync_status", "ok")
        if sync_status.startswith("fetch_error"):
            # 提取具体错误信息
            err_msg = sync_status.split("|", 1)[1] if "|" in sync_status else ""
            if err_msg:
                st.error(f"数据拉取失败：{err_msg}")
            else:
                st.error("数据拉取失败！请检查「系统参数配置」中的凭证是否有效。")
        elif sync_status == "no_config":
            st.error("数据源凭证未完整配置！请在「系统参数配置」页面填写对应数据源（飞书/DB）的连接信息后保存。")
        elif sync_status == "empty":
            st.warning("数据源连接正常，但暂未拉取到报价数据。")
        elif sync_status == "syncing":
            st.info("正在后台拉取数据，请稍后刷新页面...")
        else:
            st.info("暂无数据，请先在「系统参数配置」里填写数据源凭证并点击保存，或调整关键词后再搜索。")
        return

    normalized: list[dict] = [{c: r.get(c, "") for c in cols} for r in rows]
    df = pd.DataFrame(normalized, columns=cols)
    # 库存为 0 的商品名称列显示橙色
    stock_col = None
    for c in cols:
        if "库存" in str(c):
            stock_col = c
            break
    if stock_col:
        def _style_stock_zero(row):
            styles = [''] * len(row)
            try:
                val = str(row.get(stock_col, '')).strip()
                if val == '0':
                    for i, c in enumerate(cols):
                        styles[i] = 'color: #e67e22; font-weight: 500'
            except Exception:
                pass
            return styles
        styled_df = df.style.apply(_style_stock_zero, axis=1)
        st.dataframe(styled_df, use_container_width=True, height=540)
    else:
        st.dataframe(df, use_container_width=True, height=540)

    # 获取最后同步时间
    last_synced_at = st.session_state.get("_dashboard_last_synced_at")
    time_info = ""
    if last_synced_at:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(last_synced_at)
            time_info = f" · 最后更新：{dt.strftime('%Y-%m-%d %H:%M:%S')}"
        except Exception:
            time_info = f" · 最后更新：{last_synced_at}"

    stat_line = f"当前展示 {len(rows)} 条 · 全表 {total} 条 · 第 {cur_page} / {total_pages} 页{time_info}"
    if new_kw.strip():
        stat_line += f"（关键词「{new_kw}」筛选后）"
    st.caption(stat_line)

    if total_pages > 1:
        cp1, cp2, cp3, cp4 = st.columns([1, 1, 2, 1])
        with cp1:
            if st.button("⬅ 上一页", disabled=(cur_page <= 1), use_container_width=True):
                st.session_state["dashboard_page"] = max(cur_page - 1, 1)
                st.session_state["_dashboard_force"] = True
                st.rerun()
        with cp2:
            goto = st.number_input(
                "跳转页",
                min_value=1,
                max_value=total_pages,
                value=cur_page,
                step=1,
            )
            if int(goto) != cur_page:
                st.session_state["dashboard_page"] = int(goto)
                st.session_state["_dashboard_force"] = True
                st.rerun()
        with cp3:
            st.write(f"共 {total_pages} 页，每页 {cur_ps} 条")
        with cp4:
            if st.button("下一页 ➡", disabled=(cur_page >= total_pages), use_container_width=True):
                st.session_state["dashboard_page"] = min(cur_page + 1, total_pages)
                st.session_state["_dashboard_force"] = True
                st.rerun()


# ----------------------------- 业务员：AI 智能查价（左右分栏版） -----------------------------
def page_price_check():
    st.subheader("🤖 AI 智能批量查价")
    st.caption("粘贴商品描述（每行一条），AI 自动拆分型号、颜色、容量等关键词，从报价表中模糊匹配并批量输出报价。")

    # 加载报价等级配置
    resp_cfg = api_get("/api/admin/config")
    cur_cfg = resp_cfg.json() if resp_cfg.status_code == 200 else {}
    price_fields = cur_cfg.get("price_fields") or []
    enabled_price_fields = [pf for pf in price_fields if pf.get("enabled")]

    col_left, col_right = st.columns(2)

    # —— 左侧输入卡片 ——
    with col_left:
        with st.container():
            _section_title("📥 批量输入")
            # 报价等级选择
            price_field = None
            if len(enabled_price_fields) > 1:
                pf_options = {pf["label"]: pf["field"] for pf in enabled_price_fields}
                pf_labels = list(pf_options.keys())
                # 记住上次选择
                last_pf = st.session_state.get("_price_field_pick")
                default_idx = pf_labels.index(last_pf) if last_pf in pf_labels else 0
                pf_pick = st.radio("选择报价等级", pf_labels, horizontal=True, index=default_idx, key="price_field_radio")
                st.session_state["_price_field_pick"] = pf_pick
                price_field = pf_options.get(pf_pick)
            elif len(enabled_price_fields) == 1:
                price_field = enabled_price_fields[0]["field"]
            # 清空标记：在 text_area 渲染前处理，避免 Streamlit 报错
            if st.session_state.get("_clear_price_check"):
                st.session_state["price_check_text"] = ""
                st.session_state["_pc_result"] = None
                st.session_state["_pc_input_hash"] = None
                st.session_state["_clear_price_check"] = False
            text = st.text_area(
                "商品描述（每行一条，示例：Turbo4暗影黑12+256一台）",
                height=260,
                placeholder="A3i星辰紫6+128一台\nK80至尊版冰峰蓝16+512一台\nk90promax12+256黑",
                label_visibility="collapsed",
                key="price_check_text",
            )
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            c1, c2 = st.columns([1, 4])

            # 加载状态：查询进行中时禁用按钮防重复提交
            _is_loading = st.session_state.get("_pc_loading", False)
            with c1:
                if st.button("🗑 清空", use_container_width=True, disabled=_is_loading):
                    st.session_state["_clear_price_check"] = True
                    st.rerun()
            with c2:
                query_clicked = st.button(
                    "🚀 智能批量查询",
                    use_container_width=True,
                    type="primary",
                    disabled=_is_loading,
                )
            # 快捷键：Command+Enter（Mac）/ Ctrl+Enter（Windows）触发查询
            st.components.v1.html("""
            <script>
            (function() {
                const doc = window.parent.document;
                doc.addEventListener('keydown', function(e) {
                    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                        e.preventDefault();
                        const buttons = doc.querySelectorAll('button');
                        for (let btn of buttons) {
                            if (btn.innerText && btn.innerText.includes('智能批量查询')) {
                                btn.click();
                                break;
                            }
                        }
                    }
                });
            })();
            </script>
            """, height=0)

    # —— 右侧结果卡片 ——
    with col_right:
        with st.container():
            _section_title("📋 查价结果")
            cache_key = "_pc_result"
            input_hash_key = "_pc_input_hash"

            # ── 状态 1：用户点击查询 → 立即清空旧结果，进入加载态 ──
            if query_clicked:
                if not text.strip():
                    st.warning("请至少输入一条商品描述")
                    if cache_key in st.session_state:
                        del st.session_state[cache_key]
                else:
                    # 立即清空旧结果（解决数据混淆问题）
                    if cache_key in st.session_state:
                        del st.session_state[cache_key]
                    # 保存查询参数（st.rerun() 后局部变量丢失）
                    st.session_state["_pc_query_text"] = text
                    st.session_state["_pc_query_price_field"] = price_field
                    st.session_state["_pc_loading"] = True
                    st.rerun()

            # ── 状态 2：加载中 → 执行 API 调用（含遮罩/禁用按钮） ──
            if st.session_state.get("_pc_loading"):
                query_text = st.session_state.get("_pc_query_text", "")
                query_pf = st.session_state.get("_pc_query_price_field")
                with st.spinner("⏳ 正在调用大模型拆分关键词，并在报价表中模糊匹配..."):
                    body = {"text": query_text}
                    if query_pf:
                        body["price_field"] = query_pf
                    r = api_post("/api/price/check", body)
                # 清理加载状态和查询参数
                st.session_state["_pc_loading"] = False
                st.session_state.pop("_pc_query_text", None)
                st.session_state.pop("_pc_query_price_field", None)
                if r.status_code != 200:
                    st.error(r.json().get("detail") or "查询失败")
                    if cache_key in st.session_state:
                        del st.session_state[cache_key]
                else:
                    st.session_state[cache_key] = r.json()
                    st.session_state[input_hash_key] = hash(query_text.strip())
                st.rerun()

            # ── 状态 3：无结果 → 占位提示 ──
            if not st.session_state.get(cache_key):
                st.markdown(
                    '<div class="placeholder-muted">暂无数据，请在左侧输入并点击「🚀 智能批量查询」...</div>',
                    unsafe_allow_html=True,
                )
            else:
                # ── 状态 4：有结果 → 渲染 ──
                data = st.session_state.get(cache_key)
                if data:
                    result_text = data["result"]
                    total = len(data["details"])
                    matched = sum(1 for d in data["details"] if d.get("matched"))
                    unmatched = total - matched

                    # 右侧标题 + 醒目的未匹配数量徽章
                    title_col, badge_col = st.columns([3, 1])
                    with title_col:
                        st.markdown(
                            '<div class="erp-section-title" style="margin-top:4px">📤 批量报价</div>',
                            unsafe_allow_html=True,
                        )
                    with badge_col:
                        if unmatched > 0:
                            st.markdown(
                                f'<div style="text-align:right; padding-top:8px">'
                                f'<span style="background:#e74c3c; color:white; font-weight:700; '
                                f'font-size:1.1rem; padding:4px 14px; border-radius:20px; '
                                f'display:inline-block; white-space:nowrap;">'
                                f'⚠ {unmatched} 个未匹配</span></div>',
                                unsafe_allow_html=True,
                            )

                    # 用 st.code 展示结果（保留原生样式和换行）
                    st.code(result_text, language=None)

                    # 复制全部按钮（带反馈）
                    st.markdown(f"""
                    <div style="text-align:right; margin-top:-20px; margin-bottom:10px">
                        <button id="_pc_copy_btn" onclick="
                            (function() {{
                                var text = {repr(result_text)};
                                var btn = document.getElementById('_pc_copy_btn');
                                navigator.clipboard.writeText(text).then(function() {{
                                    btn.innerHTML = '✓ 复制成功';
                                    btn.style.background = '#27ae60';
                                    btn.style.color = 'white';
                                    btn.style.borderColor = '#27ae60';
                                    setTimeout(function() {{
                                        btn.innerHTML = '📋 复制全部';
                                        btn.style.background = '';
                                        btn.style.color = '';
                                        btn.style.borderColor = '';
                                    }}, 2000);
                                }}).catch(function() {{
                                    var ta = document.getElementById('_pc_fallback');
                                    if (!ta) {{
                                        ta = document.createElement('textarea');
                                        ta.id = '_pc_fallback';
                                        ta.style.position = 'fixed';
                                        ta.style.left = '-9999px';
                                        ta.style.top = '-9999px';
                                        document.body.appendChild(ta);
                                    }}
                                    ta.value = text;
                                    ta.select();
                                    document.execCommand('copy');
                                    btn.innerHTML = '✓ 复制成功';
                                    setTimeout(function() {{ btn.innerHTML = '📋 复制全部'; }}, 2000);
                                }});
                            }})();
                        " style="
                            background:transparent; border:1px solid #bbb; border-radius:6px;
                            padding:2px 14px; font-size:12px; color:#666; cursor:pointer;
                            transition:all 0.2s;
                        ">📋 复制全部</button>
                    </div>
                    """, unsafe_allow_html=True)

                    # 获取最后同步时间 — 醒目显示
                    last_synced = data.get("last_synced_at")
                    time_info = ""
                    time_style = ""
                    if last_synced:
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(last_synced)
                            now_local = datetime.now()
                            # 检查是否今天的数据
                            is_today = dt.date() == now_local.date()
                            # 计算距离现在的小时数
                            hours_ago = (now_local - dt).total_seconds() / 3600 if is_today else 99
                            time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                            if is_today and hours_ago < 2:
                                # 今天、2h内：绿色（新鲜）
                                time_style = 'color:#27ae60; font-weight:700; background:#e8f8f0; padding:2px 10px; border-radius:8px;'
                                time_info = f' · <span style="{time_style}">📡 报价数据更新：{time_str}</span>'
                            elif is_today:
                                # 今天、超过 2h：橙色
                                time_style = 'color:#e67e22; font-weight:700; background:#fef5e7; padding:2px 10px; border-radius:8px;'
                                time_info = f' · <span style="{time_style}">📡 报价数据更新：{time_str}</span>'
                            else:
                                # 非今天数据：红色醒目警告
                                time_style = 'color:#e74c3c; font-weight:700; background:#fdedec; padding:2px 10px; border-radius:8px;'
                                time_info = f' · <span style="{time_style}">⚠️ 报价数据更新：{time_str}（未更新）</span>'
                        except Exception:
                            time_info = f' · 报价数据更新：{last_synced}'

                    summary_html = f'<span style="font-size:0.9rem; color:#555;">共 {total} 条 · 命中 {matched} 条 · 未命中 {unmatched} 条{time_info}</span>'
                    st.markdown(summary_html, unsafe_allow_html=True)

                    # 全链路耗时统计（帮助用户理解性能分布）
                    timing = data.get("timing", {})
                    if timing:
                        t_llm = timing.get("parallel_llm_db_s", 0)
                        t_match = timing.get("batch_matching_s", 0)
                        t_total = timing.get("total_s", 0)
                        n_rows = timing.get("row_count", 0)
                        # 色彩编码：<1s 绿色，1-5s 橙色，>5s 红色
                        def _time_color(secs):
                            if secs < 1: return "#27ae60"
                            elif secs < 5: return "#e67e22"
                            else: return "#e74c3c"
                        timing_html = (
                            f'<div style="margin-top:6px; padding:8px 14px; background:#f8f9fa; '
                            f'border-radius:8px; font-size:0.82rem; color:#666; line-height:1.8;">'
                            f'⏱️ <b>耗时分析</b> &nbsp;'
                            f'<span style="color:{_time_color(t_llm)}">LLM+加载 {t_llm}s</span> &nbsp;→&nbsp; '
                            f'<span style="color:{_time_color(t_match)}">匹配 {t_match}s</span> &nbsp;=&nbsp; '
                            f'<span style="color:{_time_color(t_total)}; font-weight:700">总计 {t_total}s</span>'
                            f'<span style="margin-left:16px; color:#999">| 数据集 {n_rows} 行</span>'
                            f'</div>'
                        )
                        st.markdown(timing_html, unsafe_allow_html=True)

                    # 展示数据同步诊断信息
                    ss = data.get("sync_status", "ok")
                    sc = data.get("sync_count", 0)
                    if ss == "refresh_ok":
                        st.success(f"✅ 数据已自动更新！共拉取 {sc} 条最新报价数据。")
                    elif ss.startswith("fetch_error"):
                        err_msg = ss.split("|", 1)[1] if "|" in ss else ""
                        if err_msg:
                            st.error(f"⚠️ 数据拉取失败（使用上次缓存数据）：{err_msg} — 请稍后重试或检查数据源连接")
                        else:
                            st.error("⚠️ 数据拉取失败！请检查「系统参数配置」中的凭证是否有效。")
                    elif ss == "no_config":
                        st.error("数据源凭证未完整配置！请在「系统参数配置」页面填写对应数据源（飞书/DB）的连接信息后保存。")
                    elif ss == "empty":
                        st.warning("数据源连接正常，但暂未拉取到报价数据。")

    # —— 底部：整宽 · 智能匹配详情对照表（带阴影卡片 & 默认展开）——
    data = st.session_state.get("_pc_result")
    with st.expander("🔍 智能匹配详情对照表（逐行查看命中商品与关键词）", expanded=True):
        if data:
            detail = []
            for d in data["details"]:
                if d.get("multi_matches"):
                    # 多颜色匹配：每个颜色展开为一行
                    is_first = True
                    total = len(d["multi_matches"])
                    for idx, m in enumerate(d["multi_matches"]):
                        detail.append({
                            "原始文本": d["original"] if is_first else "",
                            "关键词": " / ".join(m["keywords"]) if m.get("keywords") else "",
                            "命中商品": m.get("matched_name") or "-",
                            "报价": m.get("price") or "-",
                            "库存": m.get("stock") or "-",
                            "匹配状态": f"✅ 已匹配 ({idx+1}/{total})",
                        })
                        is_first = False
                else:
                    detail.append({
                        "原始文本": d["original"],
                        "关键词": " / ".join(d["keywords"]) if d["keywords"] else "",
                        "命中商品": d.get("matched_name") or "-",
                        "报价": d.get("price") or "-",
                        "库存": d.get("stock") or "-",
                        "匹配状态": "✅ 已匹配" if d.get("matched") else "❌ 未匹配",
                    })
            df = pd.DataFrame(detail)

            # 颜色区分：命中商品列 — 黑色=有报价 / 橙色=价格为0 / 红色=未命中
            def style_hit_product(row):
                styles = [''] * len(row)
                if '命中商品' in row.index:
                    idx = list(row.index).index('命中商品')
                    if row['匹配状态'] == '❌ 未匹配':
                        styles[idx] = 'color: #e74c3c; font-weight: 500'
                    elif row['报价'] == '0':
                        styles[idx] = 'color: #e67e22; font-weight: 500'
                    # 有报价：保持默认黑色，不额外设置样式
                return styles

            styled_df = df.style.apply(style_hit_product, axis=1)
            st.dataframe(styled_df, use_container_width=True, hide_index=True, height=380)
            st.caption("未命中的条目请回到报价看板确认「该型号/容量/颜色」是否在表中实际存在。")
        else:
            st.markdown(
                '<div class="placeholder-muted" style="margin:4px 0 0 0;">尚未查询 · 请在左侧输入后点击「🚀 智能批量查询」查看逐行匹配结果</div>',
                unsafe_allow_html=True,
            )


# ----------------------------- 商户后台：角色管理（可配置） -----------------------------
def page_role_management():
    st.subheader("🔐 角色管理")
    st.caption("管理所有角色及其描述。内置角色（platform_admin / tenant_admin / sales）不可删除或改名，但可修改描述。")

    resp = api_get("/api/admin/roles")
    if resp.status_code != 200:
        st.error(resp.json().get("detail") or "加载失败")
        return
    rows = resp.json()

    # ── 角色列表 ──
    with st.container():
        _section_title("📋 角色列表")
        if rows:
            df = pd.DataFrame(rows)
            # 标记内置角色
            df["builtin"] = df["name"].apply(
                lambda n: "✅ 是" if n in ("platform_admin", "tenant_admin", "sales") else "❌ 否"
            )
            display = df[["id", "name", "description", "menu_permissions", "user_count", "builtin"]].rename(
                columns={
                    "id": "ID",
                    "name": "角色标识",
                    "description": "描述",
                    "menu_permissions": "菜单权限",
                    "user_count": "用户数",
                    "builtin": "内置角色",
                }
            )
            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", width="small"),
                    "角色标识": st.column_config.TextColumn("角色标识", width="medium"),
                    "描述": st.column_config.TextColumn("描述", width="large"),
                    "用户数": st.column_config.NumberColumn("用户数", width="small"),
                    "内置角色": st.column_config.TextColumn("内置角色", width="small"),
                },
            )
        else:
            st.info("暂无角色数据")

    st.markdown("---")

    # ── 编辑角色 ──
    if rows:
        with st.container():
            _section_title("✏️ 编辑角色描述")
            edit_role = st.selectbox(
                "选择角色",
                rows,
                format_func=lambda r: f"{r['name']}（{r['description'] or '无描述'}）",
                key="edit_role",
            )
            if edit_role:
                with st.form("edit_role_form"):
                    is_builtin = edit_role["name"] in ("platform_admin", "tenant_admin", "sales")
                    if is_builtin:
                        st.info(f"「{edit_role['name']}」是内置角色，仅可编辑描述和菜单权限")
                        c1, c2 = st.columns([1, 3])
                        with c1:
                            _name = st.text_input("角色标识", value=edit_role["name"], disabled=True)
                        with c2:
                            _desc = st.text_input("角色描述", value=edit_role.get("description", ""))
                        save_body = {"description": _desc}
                    else:
                        c1, c2 = st.columns(2)
                        with c1:
                            _name = st.text_input("角色标识", value=edit_role["name"])
                        with c2:
                            _desc = st.text_input("角色描述", value=edit_role.get("description", ""))
                        save_body = {}
                        if _name.strip() and _name.strip() != edit_role["name"]:
                            save_body["name"] = _name.strip()
                        save_body["description"] = _desc

                    # 菜单权限配置
                    st.markdown("##### 📋 菜单权限")
                    menu_options = [
                        ("dashboard", "📊 报价看板"),
                        ("price_check", "🤖 AI 智能查价"),
                        ("users", "👥 员工管理"),
                        ("roles", "🔐 角色管理"),
                        ("config", "⚙️ 系统参数配置"),
                        ("audit", "📋 操作审计日志"),
                    ]
                    cur_perms = edit_role.get("menu_permissions") or []
                    new_perms = []
                    cols = st.columns(3)
                    for i, (key, label) in enumerate(menu_options):
                        with cols[i % 3]:
                            checked = st.checkbox(label, value=key in cur_perms, key=f"menu_perm_{edit_role['id']}_{key}")
                            if checked:
                                new_perms.append(key)
                    save_body["menu_permissions"] = new_perms

                    if st.form_submit_button("💾 保存角色", use_container_width=True, type="primary"):
                        if not save_body.get("name") and "name" not in save_body:
                            pass  # only description changed
                        r = api_put(f"/api/admin/roles/{edit_role['id']}", save_body)
                        if r.status_code == 200:
                            st.success("角色已更新")
                            st.rerun()
                        else:
                            st.error(r.json().get("detail") or "保存失败")

    # ── 新建角色 ──
    st.markdown("---")
    with st.container():
        _section_title("➕ 新建自定义角色")
        with st.form("new_role_form"):
            c1, c2 = st.columns(2)
            with c1:
                new_name = st.text_input("角色标识（英文）", placeholder="如：auditor")
            with c2:
                new_desc = st.text_input("角色描述", placeholder="如：审计员，可查看所有报价")
            # 菜单权限
            st.markdown("##### 📋 菜单权限")
            menu_options = [
                ("dashboard", "📊 报价看板"),
                ("price_check", "🤖 AI 智能查价"),
                ("users", "👥 员工管理"),
                ("roles", "🔐 角色管理"),
                ("config", "⚙️ 系统参数配置"),
                ("audit", "📋 操作审计日志"),
            ]
            new_perms = []
            cols = st.columns(3)
            for i, (key, label) in enumerate(menu_options):
                with cols[i % 3]:
                    if st.checkbox(label, key=f"new_role_perm_{key}"):
                        new_perms.append(key)
            if st.form_submit_button("➕ 创建角色", use_container_width=True, type="primary"):
                if not new_name.strip():
                    st.error("角色标识不可为空")
                else:
                    r = api_post("/api/admin/roles", {"name": new_name.strip(), "description": new_desc.strip(), "menu_permissions": new_perms})
                    if r.status_code == 200:
                        st.success("角色已创建")
                        st.rerun()
                    else:
                        st.error(r.json().get("detail") or "创建失败")

    # ── 删除角色 ──
    if rows:
        st.markdown("---")
        with st.container():
            _section_title("🗑 删除自定义角色")
            deletable = [r for r in rows if r["name"] not in ("platform_admin", "tenant_admin", "sales")]
            if not deletable:
                st.info("没有可删除的自定义角色")
            else:
                del_pick = st.selectbox(
                    "选择要删除的角色",
                    deletable,
                    format_func=lambda r: f"{r['name']}（{r['description'] or '无描述'}，{r['user_count']} 个用户）",
                    key="del_role",
                )
                if st.button(
                    f"🗑 删除「{del_pick['name']}」",
                    type="secondary",
                    use_container_width=True,
                ):
                    r = api_delete(f"/api/admin/roles/{del_pick['id']}")
                    if r.status_code == 200:
                        st.success("角色已删除")
                        st.rerun()
                    else:
                        st.error(r.json().get("detail") or "删除失败")


# ----------------------------- 路由 -----------------------------
def main():
    if "token" not in st.session_state or not st.session_state["token"]:
        login_page()
        return

    # 登录后注入「顶部工具栏卡片化 + 按钮样式覆盖」
    st.markdown(
        """
        <style>
        #MainMenu { visibility: hidden; }
        footer { visibility: hidden; }
        header { visibility: visible; background: transparent !important; }
        [data-testid="stAppViewContainer"] { background: #F5F5F7 !important; }
        [data-testid="stHeader"] { background: #FFFFFF; }
        .login-card, .login-shell { display: none !important; }

        /* 顶部工具栏卡片 */
        #topbar-marker + [data-testid="stHorizontalBlock"] {
            background: #FFFFFF !important;
            border: 1px solid rgba(0,0,0,0.06) !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03) !important;
            padding: 8px 18px !important;
            margin-bottom: 20px !important;
            gap: 10px !important;
        }
        #topbar-marker + [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(1) {
            display: flex;
            align-items: center;
        }

        /* 顶部按钮 */
        #topbar-marker + [data-testid="stHorizontalBlock"] .stButton > button {
            background: #FFFFFF !important;
            color: #1D1D1F !important;
            border: 1px solid #D2D2D7 !important;
            border-radius: 8px !important;
            padding: 6px 14px !important;
            min-height: 34px !important;
            font-size: 13px !important;
            font-weight: 500 !important;
            white-space: nowrap !important;
            box-shadow: none !important;
            transition: all 0.15s ease !important;
        }
        #topbar-marker + [data-testid="stHorizontalBlock"] .stButton > button:hover {
            background: #F5F5F7 !important;
            border-color: #B8B8BE !important;
        }

        /* 退出登录按钮 */
        #topbar-marker + [data-testid="stHorizontalBlock"]
        > [data-testid="column"]:nth-child(4) .stButton > button {
            background: rgba(255,59,48,0.06) !important;
            color: #FF3B30 !important;
            border-color: rgba(255,59,48,0.15) !important;
        }
        #topbar-marker + [data-testid="stHorizontalBlock"]
        > [data-testid="column"]:nth-child(4) .stButton > button:hover {
            background: rgba(255,59,48,0.10) !important;
            border-color: rgba(255,59,48,0.25) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 锚点：紧随其后的 stHorizontalBlock（即 topbar 里的 st.columns）会被美化为卡片
    st.markdown('<div id="topbar-marker"></div>', unsafe_allow_html=True)
    topbar()
    role = st.session_state.get("role")
    if role == "platform_admin":
        menu = {
            "🏢 商户资质管理": page_platform_tenants,
            "📊 全局报价监控": page_platform_monitor,
            "📋 操作审计日志": page_audit_logs,
            "🔑 修改密码": page_change_password,
        }
    elif role == "tenant_admin":
        menu = {
            "🤖 AI 智能查价": page_price_check,
            "📊 报价看板": page_dashboard,
            "👥 员工管理": page_user_management,
            "🔐 角色管理": page_role_management,
            "⚙️ 系统参数配置": page_admin_config,
            "📋 操作审计日志": page_audit_logs,
            "🔑 修改密码": page_change_password,
        }
    else:  # sales
        menu = {
            "🤖 AI 智能查价": page_price_check,   # 放第一个位置
            "📊 报价看板": page_dashboard,
            "🔑 修改密码": page_change_password,
        }

    # 记住上次选择的菜单，下次进来默认在同一项（避免每次都回到第一个）
    default_idx = 0
    last_choice = st.session_state.get("_last_menu_choice")
    if last_choice and last_choice in menu:
        default_idx = list(menu.keys()).index(last_choice)

    choice = st.sidebar.radio("功能菜单", list(menu.keys()), index=default_idx)
    # 页面切换时清除 AI 查价结果缓存，避免显示上次的旧数据
    if choice != last_choice and "_pc_result" in st.session_state:
        del st.session_state["_pc_result"]
        st.session_state.pop("_pc_input_hash", None)
    st.session_state["_last_menu_choice"] = choice
    st.sidebar.markdown("---")
    st.sidebar.caption(f"后端: {API_BASE}")
    menu[choice]()


if __name__ == "__main__":
    main()
