import altair as alt
import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz

# --- 1. SETUP & AUTHENTICATION (Simple Password) ---
# Since you want to "leave the complex auth for now", we use the simple password check.
def check_password():
    if "general" not in st.secrets:
        return True # If no secrets set, allow access (for dev)

    def password_entered():
        if st.session_state["password"] == st.secrets["general"]["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("סיסמה", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("סיסמה", type="password", on_change=password_entered, key="password")
        st.error("😕 סיסמה שגויה")
        return False
    else:
        return True

if not check_password():
    st.stop()

# --- 2. GOOGLE SHEETS CONNECTION ---
@st.cache_resource
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def save_to_google_sheet(timestamp, level, abs_level, volume):
    try:
        client = get_gsheet_client()
        sheet = client.open("WaterLevelDB").sheet1
        sheet.append_row([str(timestamp), level, abs_level, volume])
        return True
    except Exception as e:
        st.error(f"שגיאה בשמירה: {e}")
        return False

def get_data_from_sheet():
    try:
        client = get_gsheet_client()
        sheet = client.open("WaterLevelDB").sheet1
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

# --- 3. DATA CONSTANTS ---
HEIGHT_VOLUME = { 
    0.0: 0, 0.5: 4027, 1.0: 11655, 1.5: 27344, 2.0: 53448, 2.5: 88216,
    3.0: 126617, 3.5: 166744, 4.0: 208327, 4.5: 251136, 5.0: 295066,
    5.5: 340074, 6.0: 386135, 6.5: 433278, 7.0: 481569, 7.5: 531074,
    8.0: 581888, 8.5: 634177,
}
SEA_LEVEL_ZERO = 50.0
MAX_RELATIVE_HEIGHT = 8.5
MAX_ABSOLUTE_HEIGHT = SEA_LEVEL_ZERO + MAX_RELATIVE_HEIGHT

# --- 4. UI START ---
st.markdown(
    "<h4 style='margin-bottom:0.25rem; white-space:nowrap; text-align:right; direction:rtl;'>💧 מאגר בית שערים</h4>",
    unsafe_allow_html=True,
)

# INPUT SECTION
st.markdown("<div style='text-align:right; direction:rtl;'>הכנס גובה (מטר או אבסולוטי)</div>", unsafe_allow_html=True)
user_input = st.number_input("", value=6.4, min_value=0.0, step=0.01, label_visibility="collapsed")

# LOGIC: Check Validity
is_valid = False
selected_height = 0.0
above_sea_level = 0.0

# 1. Check Range
if 0.0 <= user_input <= MAX_RELATIVE_HEIGHT:
    selected_height = user_input
    above_sea_level = SEA_LEVEL_ZERO + selected_height
    is_valid = True
elif SEA_LEVEL_ZERO <= user_input <= MAX_ABSOLUTE_HEIGHT:
    selected_height = user_input - SEA_LEVEL_ZERO
    above_sea_level = user_input
    is_valid = True
else:
    # ERROR HANDLING: Just show message, do NOT stop app
    if user_input > 0: # Don't show error on initial 0.0
        st.error(f"⚠️ טווח לא חוקי. נא להזין בין 0-{MAX_RELATIVE_HEIGHT} או {SEA_LEVEL_ZERO}-{MAX_ABSOLUTE_HEIGHT}")
    is_valid = False

# IF VALID: Show Calculation, Graph, and Save Button
if is_valid:
    # --- Calculation ---
    lower_step = round((selected_height // 0.5) * 0.5, 2)
    upper_step = round(min(lower_step + 0.5, 8.5), 2)
    lower_volume = HEIGHT_VOLUME[lower_step]
    upper_volume = HEIGHT_VOLUME[upper_step]

    if upper_step == lower_step:
        cumulative_volume = lower_volume
    else:
        fraction = (selected_height - lower_step) / 0.5
        cumulative_volume = lower_volume + (upper_volume - lower_volume) * fraction

    # Display Text Stats
    st.markdown(
        f"""
        <div style="display:flex; gap:12px; align-items:flex-start; justify-content:space-between; direction:rtl; margin-top:10px;">
          <div style="text-align:right;">
            <strong>נפח מצטבר</strong><br><span style="font-size:1.2rem; color:#1f77b4;">{cumulative_volume:,.0f}</span> מ״ק
          </div>
          <div style="text-align:right;">
            <strong>גובה מעל הים</strong><br>{above_sea_level:.2f} מ׳
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- THE GRAPH (Restored) ---
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Prepare Data
    points = [{"Height": h, "AbsHeight": h + SEA_LEVEL_ZERO, "Volume": v} for h, v in sorted(HEIGHT_VOLUME.items())]
    
    # Split into "Past" (Blue) and "Future" (Gray)
    blue_points = [p for p in points if p["Height"] <= selected_height]
    # Add current point to Blue
    if not any(p["Height"] == selected_height for p in blue_points):
        blue_points.append({"Height": selected_height, "AbsHeight": above_sea_level, "Volume": cumulative_volume})
    blue_points = sorted(blue_points, key=lambda p: p["Height"])

    gray_points = [{"Height": selected_height, "AbsHeight": above_sea_level, "Volume": cumulative_volume}]
    gray_points.extend([p for p in points if p["Height"] > selected_height])
    gray_points = sorted(gray_points, key=lambda p: p["Height"])

    blue_df = pd.DataFrame(blue_points)
    gray_df = pd.DataFrame(gray_points)
    
    x_domain = [SEA_LEVEL_ZERO, SEA_LEVEL_ZERO + 8.5]

    # Chart
    blue_line = alt.Chart(blue_df).mark_line(color="#1f77b4", strokeWidth=3).encode(
        x=alt.X("AbsHeight", title="גובה מעל פני הים", scale=alt.Scale(domain=x_domain, zero=False)),
        y=alt.Y("Volume", title="נפח (מ״ק)"),
    )
    gray_line = alt.Chart(gray_df).mark_line(color="#d3d3d3", strokeDash=[5, 5]).encode(
        x="AbsHeight", y="Volume"
    )
    # Add a big dot for the current point
    current_point = pd.DataFrame([{"AbsHeight": above_sea_level, "Volume": cumulative_volume}])
    dot = alt.Chart(current_point).mark_circle(size=100, color="red").encode(x="AbsHeight", y="Volume")

    final_chart = (blue_line + gray_line + dot).properties(height=250)
    st.altair_chart(final_chart, use_container_width=True)

    # --- SAVE BUTTON (Explicit Action) ---
    # Logic: Only save when this button is clicked
    if st.button("💾 שמור נתונים", use_container_width=True, type="primary"):
        tz = pytz.timezone('Asia/Jerusalem')
        current_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        
        if save_to_google_sheet(current_time, selected_height, above_sea_level, cumulative_volume):
            st.success("✅ הנתונים נשמרו בהצלחה!")
            st.cache_data.clear() # Refresh table
        else:
            st.error("❌ שגיאה בשמירה")

# --- 5. HISTORY TABLE ---
st.divider()
st.markdown("<div style='text-align:right; direction:rtl; font-weight:bold;'>היסטוריית מדידות</div>", unsafe_allow_html=True)

df = get_data_from_sheet()

if not df.empty:
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 הורד נתונים (CSV)",
        data=csv,
        file_name='water_level_log.csv',
        mime='text/csv',
    )
    st.dataframe(df.tail(5).iloc[::-1], use_container_width=True)
else:
    st.info("אין נתונים עדיין.")
st.markdown(
    "<div style='text-align:right; direction:rtl; font-size:0.75rem; margin-top:0.05rem;'>"
    "מופעל על ידי יאיר ועמית כהנוביץ. צאצאי משפחת כהנוביץ, ממיסדי מושב בית שערים"
    "</div>",
    unsafe_allow_html=True,
)   
