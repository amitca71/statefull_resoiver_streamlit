import altair as alt
import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz
# --- UNIVERSAL USER EMAIL FUNCTION ---
def get_user_email():
    # 1. Try the new official 'st.context' (Streamlit 1.40+)
    try:
        # st.context.headers is a dictionary-like object
        if st.context.headers and "X-Streamlit-User-Email" in st.context.headers:
            return st.context.headers["X-Streamlit-User-Email"]
    except Exception:
        pass

    # 2. Try the internal WebSocket headers (The "Hack" method)
    # This works on many cloud versions where st.context might be empty
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        if headers and "X-Streamlit-User-Email" in headers:
            return headers["X-Streamlit-User-Email"]
    except Exception:
        pass

    # 3. Last Resort: Old experimental_user (Pre-1.40)
    try:
        if hasattr(st, "experimental_user"):
            return st.experimental_user.email
    except Exception:
        pass
    
    # 4. If all else fails, return a debug string
    return "User_Not_Found_In_Headers"

# Get the email
current_user_email = get_user_email()

# --- DEBUG DISPLAY (Remove this after it works) ---
st.write(f"Logged in as: **{current_user_email}**")
current_user_email = get_user_email()
# --- 1. GET CURRENT USER (Option 3 Magic) ---
# Streamlit Cloud automatically provides this if the user logged in via the "Share" invite.
# If running locally, it might be None, so we set a fallback.
current_user_email = get_user_email()

# --- 2. GOOGLE SHEETS CONNECTION ---
@st.cache_resource
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    # Load credentials from Streamlit Secrets
    # Make sure your secrets.toml has the [gcp_service_account] section!
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def save_to_google_sheet(timestamp, level, abs_level, volume, user_email):
    try:
        client = get_gsheet_client()
        sheet = client.open("WaterLevelDB").sheet1
        # Appending the user_email to know WHO updated it
        sheet.append_row([str(timestamp), level, abs_level, volume, user_email])
        return True
    except Exception as e:
        st.error(f"שגיאה בשמירה ל-Google Sheets: {e}")
        return False

def get_data_from_sheet():
    try:
        client = get_gsheet_client()
        sheet = client.open("WaterLevelDB").sheet1
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

# --- 3. APP UI & LOGIC ---

# Header
st.markdown(
    "<h4 style='margin-bottom:0.25rem; white-space:nowrap; text-align:right; direction:rtl;'>💧 מאגר בית שערים</h4>",
    unsafe_allow_html=True,
)

# Show who is logged in
st.markdown(
    f"<div style='text-align:right; direction:rtl; font-size:0.8rem; color:gray;'>מחובר כמשתמש: <b>{current_user_email}</b></div>", 
    unsafe_allow_html=True
)

HEIGHT_VOLUME = { 
    0.0: 0, 0.5: 4027, 1.0: 11655, 1.5: 27344, 2.0: 53448, 2.5: 88216,
    3.0: 126617, 3.5: 166744, 4.0: 208327, 4.5: 251136, 5.0: 295066,
    5.5: 340074, 6.0: 386135, 6.5: 433278, 7.0: 481569, 7.5: 531074,
    8.0: 581888, 8.5: 634177,
}

SEA_LEVEL_ZERO = 50.0
MAX_RELATIVE_HEIGHT = 8.5
MAX_ABSOLUTE_HEIGHT = SEA_LEVEL_ZERO + MAX_RELATIVE_HEIGHT

# Input Form
with st.form("entry_form"):
    st.markdown("<div style='text-align:right; direction:rtl;'>הכנס גובה (מטר או גובה אבסולוטי)</div>", unsafe_allow_html=True)
    user_input = st.number_input("", min_value=0.0, step=0.01, label_visibility="collapsed")
    
    # Logic: Convert Absolute to Relative if needed
    if 0.0 <= user_input <= MAX_RELATIVE_HEIGHT:
        selected_height = user_input
        above_sea_level = SEA_LEVEL_ZERO + selected_height
    elif SEA_LEVEL_ZERO <= user_input <= MAX_ABSOLUTE_HEIGHT:
        selected_height = user_input - SEA_LEVEL_ZERO
        above_sea_level = user_input
    else:
        st.error(f"טווח לא חוקי. נא להזין בין 0-{MAX_RELATIVE_HEIGHT} או {SEA_LEVEL_ZERO}-{MAX_ABSOLUTE_HEIGHT}")
        st.stop()

    # Calculate Volume (Interpolation)
    lower_step = round((selected_height // 0.5) * 0.5, 2)
    upper_step = round(min(lower_step + 0.5, 8.5), 2)
    lower_volume = HEIGHT_VOLUME[lower_step]
    upper_volume = HEIGHT_VOLUME[upper_step]

    if upper_step == lower_step:
        cumulative_volume = lower_volume
    else:
        fraction = (selected_height - lower_step) / 0.5
        cumulative_volume = lower_volume + (upper_volume - lower_volume) * fraction

    # Show calculated volume inside the form
    st.markdown(f"<div style='direction:rtl; text-align:right; margin-top:10px;'>נפח מחושב: <b>{cumulative_volume:,.0f}</b> מ״ק</div>", unsafe_allow_html=True)
    
    submitted = st.form_submit_button("שמור נתונים")

    if submitted:
        tz = pytz.timezone('Asia/Jerusalem')
        current_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        
        # Save to Google Sheet with User Email
        if save_to_google_sheet(current_time, selected_height, above_sea_level, cumulative_volume, current_user_email):
            st.success("✅ הנתונים נשמרו בהצלחה!")
            st.cache_data.clear() # Refresh the data table below
        else:
            st.error("❌ שגיאה בשמירה")

# --- 4. GRAPH & HISTORY ---

st.divider()
st.markdown("<div style='text-align:right; direction:rtl; font-weight:bold;'>היסטוריית מדידות</div>", unsafe_allow_html=True)

df = get_data_from_sheet()

if not df.empty:
    # 1. Download Button
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 הורד נתונים (CSV)",
        data=csv,
        file_name='water_level_log.csv',
        mime='text/csv',
    )
    
    # 2. Display Table (Last 5 records)
    st.dataframe(df.tail(5).iloc[::-1], use_container_width=True)
else:
    st.info("אין נתונים עדיין בגיליון.")

# Footer
st.markdown(
    "<div style='text-align:right; direction:rtl; font-size:0.75rem; margin-top:2rem; color:gray;'>"
    "מופעל על ידי יאיר ועמית כהנוביץ."
    "</div>",
    unsafe_allow_html=True,
)
