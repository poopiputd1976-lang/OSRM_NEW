import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import math
import datetime
import requests
import time

# --- ฟังก์ชันดึงราคาน้ำมัน Real-time ---
def get_fuel_prices_api():
    # ดึงข้อมูลจาก API ราคาน้ำมันไทย
    url = "https://api.chnwt.dev/thai-oil-api/latest"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()["response"]
        return None
    except:
        return None

# --- ฟังก์ชันจัดเส้นทาง (เหมือนเดิม) ---
def get_osrm_route(df):
    try:
        coords = ";".join([f"{row['Lon']},{row['Lat']}" for _, row in df.iterrows()])
        url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"
        response = requests.get(url).json()
        if response.get("code") == "Ok":
            route = response["routes"][0]
            geometry = [[coord[1], coord[0]] for coord in route["geometry"]["coordinates"]]
            leg_distances = [leg["distance"] / 1000.0 for leg in route["legs"]]
            return geometry, leg_distances
    except: pass
    return None, None

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    a = math.sin((lat2_rad - lat1_rad) / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin((lon2_rad - lon1_rad) / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# --- หน้าจอหลัก ---
st.set_page_config(page_title="Milk Run Optimization", layout="wide")
st.title("🚚 SUT Daily Route Planning")

# ดึงราคาน้ำมัน
with st.spinner('กำลังอัปเดตราคาน้ำมันล่าสุด...'):
    fuel_data = get_fuel_prices_api()

if fuel_data:
    st.subheader("⛽ ราคาน้ำมันอัปเดตล่าสุดจากหน้าเว็บ")
    brands = ["ptt", "bangchak", "shell", "caltex", "esso", "susco"]
    selected_brand = st.selectbox("เลือกปั๊มน้ำมัน:", brands)
    
    # แสดงราคาของปั๊มที่เลือก
    brand_prices = fuel_data.get(selected_brand, {})
    cols = st.columns(len(brand_prices))
    for idx, (fuel_type, price) in enumerate(brand_prices.items()):
        cols[idx % 5].metric(label=fuel_type.upper(), value=f"{price} บาท")
else:
    st.error("ไม่สามารถดึงข้อมูลราคาน้ำมันได้ในขณะนี้")

# --- ส่วนอัปโหลดไฟล์และการคำนวณ ---
uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์สถานที่ (Excel / CSV)", type=["xlsx", "csv"])

if uploaded_file is not None:
    # (วาง Logic การคำนวณเส้นทางและวนลูปสร้างแผนที่ของคุณไว้ตรงนี้เหมือนเดิมครับ)
    st.info("ระบบพร้อมคำนวณเส้นทางแล้ว!")
