import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import math
import datetime
import requests

# --- ตั้งค่า Cache เพื่อไม่ให้แอปพังเวลาเน็ตแกว่ง ---
@st.cache_data(ttl=3600)
def get_fuel_prices_api():
    url = "https://api.chnwt.dev/thai-oil-api/latest"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get("response")
    except:
        return None
    return None

# --- ฟังก์ชันหลัก ---
st.set_page_config(page_title="Milk Run Optimization", layout="wide")
st.title("🚚 SUT Daily Route Planning")

# --- ส่วนแสดงราคาน้ำมัน (ปรับใหม่ให้สะอาดที่สุด) ---
st.subheader("⛽ ราคาน้ำมันอัปเดตล่าสุด")
fuel_data = get_fuel_prices_api()

if fuel_data:
    try:
        # วิธีใหม่: แปลง dict ซ้อน dict ให้กลายเป็นตารางแบนๆ (Flat Table)
        df_list = []
        for brand, fuels in fuel_data.items():
            if isinstance(fuels, dict):
                row = {"ปั๊มน้ำมัน": brand.upper()}
                for fuel_name, info in fuels.items():
                    # ดึงราคาออกมาแบบตรงไปตรงมา
                    price = info.get("price") if isinstance(info, dict) else "-"
                    row[fuel_name.upper()] = price
                df_list.append(row)
        
        df_display = pd.DataFrame(df_list)
        st.dataframe(df_display, use_container_width=True)
    except:
        st.write("ไม่สามารถแสดงตารางได้ กรุณาตรวจสอบข้อมูลดิบ:")
        st.json(fuel_data)
else:
    st.error("ดึงข้อมูลไม่ได้ (API อาจจะปิดปรับปรุง)")

# --- ส่วนที่เหลือ (เอาไว้ที่เดิมได้เลยครับ) ---
uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์สถานที่ (Excel / CSV)", type=["xlsx", "csv"])
# ... (ใส่โค้ดส่วนของ OSRM, Folium และตารางกำหนดการของคุณไว้ตรงนี้เหมือนเดิมได้เลยครับ)
