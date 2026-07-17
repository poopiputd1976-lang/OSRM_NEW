import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import math
import datetime
import requests

# --- ฟังก์ชันดึงราคาน้ำมัน ---
def get_fuel_prices_api():
    url = "https://api.chnwt.dev/thai-oil-api/latest"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json().get("response")
        return None
    except:
        return None

# --- ฟังก์ชันคำนวณและเส้นทาง ---
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
    except Exception: pass
    return None, None

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0 
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def nearest_neighbor_route(df):
    unvisited = list(range(1, len(df))); route = [0]; current = 0
    while unvisited:
        next_node = min(unvisited, key=lambda x: calculate_distance(df.iloc[current]['Lat'], df.iloc[current]['Lon'], df.iloc[x]['Lat'], df.iloc[x]['Lon']))
        route.append(next_node); current = next_node; unvisited.remove(next_node)
    return route

def savings_route(df):
    if len(df) <= 2: return list(range(len(df)))
    n = len(df); savings = []; depot_lat, depot_lon = df.iloc[0]['Lat'], df.iloc[0]['Lon']
    for i in range(1, n):
        for j in range(i + 1, n):
            s = calculate_distance(depot_lat, depot_lon, df.iloc[i]['Lat'], df.iloc[i]['Lon']) + calculate_distance(depot_lat, depot_lon, df.iloc[j]['Lat'], df.iloc[j]['Lon']) - calculate_distance(df.iloc[i]['Lat'], df.iloc[i]['Lon'], df.iloc[j]['Lat'], df.iloc[j]['Lon'])
            savings.append((s, i, j))
    savings.sort(key=lambda x: x[0], reverse=True); routes = [[i] for i in range(1, n)]
    for s, i, j in savings:
        r_i, r_j = None, None
        for r in routes:
            if i in r: r_i = r
            if j in r: r_j = r
        if r_i != r_j and r_i is not None and r_j is not None:
            if r_i[-1] == i and r_j[0] == j: routes.remove(r_i); routes.remove(r_j); routes.insert(0, r_i + r_j)
            elif r_i[0] == i and r_j[-1] == j: routes.remove(r_i); routes.remove(r_j); routes.insert(0, r_j + r_i)
    final_nodes = []
    for r in routes: final_nodes.extend(r)
    return [0] + final_nodes

# --- ส่วนหน้าเว็บ ---
st.set_page_config(page_title="Milk Run Optimization & Dashboard", layout="wide")
st.title("🚚 SUT Daily Route Planning")

# ส่วนแสดงราคาน้ำมัน
st.subheader("⛽ ราคาน้ำมันอัปเดตล่าสุด (Real-time)")
fuel_data = get_fuel_prices_api()

if fuel_data:
    try:
        rows = []
        for brand, fuels in fuel_data.items():
            if isinstance(fuels, dict):
                record = {"ปั๊มน้ำมัน": brand.upper()}
                for fuel_name, info in fuels.items():
                    val = info.get("price") if isinstance(info, dict) else info
                    record[fuel_name.upper()] = val if val else "-"
                rows.append(record)
        
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.write("พบข้อมูลแต่ไม่สามารถประมวลผลตารางได้")
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาด: {e}")
else:
    st.error("ไม่สามารถเชื่อมต่อ API ราคาน้ำมันได้")

# --- ส่วนอัปโหลดและคำนวณ ---
uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์สถานที่ (Excel / CSV)", type=["xlsx", "csv"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file)
        else: df = pd.read_excel(uploaded_file)
        
        st.subheader("📅 1. กำหนดการและค่าพารามิเตอร์")
        col1, col2, col3 = st.columns(3)
        with col1: selected_date = st.date_input("วันที่ปฏิบัติงาน", datetime.date.today())
        with col2: start_time = st.time_input("เวลาเริ่มปฏิบัติงาน", datetime.time(8, 0))
        with col3: service_time_input = st.number_input("เวลาจอดลงของต่อจุด (วินาที)", min_value=0, value=300, step=10)
        
        if 'ชื่อสถานที่' in df.columns and 'Lat' in df.columns and 'Lon' in df.columns:
            st.subheader("📝 2. ข้อมูลสถานที่ต้นทางและลูกค้า")
            edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

            st.subheader("🧠 3. เลือกวิธีจัดเรียงเส้นทาง")
            algo_choice = st.radio("รูปแบบ:", ("1. ลำดับตามไฟล์ดั้งเดิม", "2. Nearest Neighbor Heuristic", "3. Saving Heuristic"))
            
            if "Nearest Neighbor" in algo_choice:
                best_indices = nearest_neighbor_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            elif "Saving" in algo_choice:
                best_indices = savings_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            else:
                optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)

            road_geometry, road_distances = get_osrm_route(optimized_df)
            current_datetime = datetime.datetime.combine(selected_date, start_time)
            schedule_data = []
            
            for i in range(len(optimized_df)):
                row = optimized_df.iloc[i]
                if i > 0:
                    dist = road_distances[i-1] if road_distances else calculate_distance(optimized_df.iloc[i-1]['Lat'], optimized_df.iloc[i-1]['Lon'], row['Lat'], row['Lon'])
                    current_datetime += datetime.timedelta(minutes=(dist/50)*60)
                current_datetime += datetime.timedelta(seconds=service_time_input)
                schedule_data.append({"ลำดับ": i, "ชื่อสถานที่": row['ชื่อสถานที่'], "เวลาถึง (ETA)": current_datetime.strftime("%H:%M:%S")})

            st.subheader("📊 4. สรุปผลลัพธ์")
            st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)
            
            # --- แผนที่ ---
            m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)
            if road_geometry: AntPath(road_geometry, color="blue", weight=5).add_to(m)
            for i in range(len(optimized_df)):
                row = optimized_df.iloc[i]
                folium.Marker([row['Lat'], row['Lon']], popup=f"{i}: {row['ชื่อสถานที่']}").add_to(m)
            st_folium(m, width=1000, height=500)
    except Exception as e: st.error(f"เกิดข้อผิดพลาด: {e}")
