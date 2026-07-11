import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import math
import datetime
import requests
import re

# --- ฟังก์ชันต่างๆ ---
def create_kml(df, geometry):
    kml_header = '<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n<name>Milk Run Route</name>\n'
    kml_footer = '</Document>\n</kml>'
    kml_body = ""
    for i in range(len(df) - 1):
        row = df.iloc[i]
        kml_body += f"<Placemark><name>{i}: {row['ชื่อสถานที่']}</name><Point><coordinates>{row['Lon']},{row['Lat']},0</coordinates></Point></Placemark>\n"
    coords_str = " ".join([f"{lon},{lat},0" for lat, lon in geometry])
    kml_body += f"<Placemark><name>Route Path</name><LineString><coordinates>{coords_str}</coordinates></LineString></Placemark>\n"
    return kml_header + kml_body + kml_footer

def create_gpx(df, geometry):
    gpx = '<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="MilkRunApp">\n'
    for i in range(len(df) - 1):
        row = df.iloc[i]
        gpx += f'<wpt lat="{row["Lat"]}" lon="{row["Lon"]}"><name>{i}: {row["ชื่อสถานที่"]}</name></wpt>\n'
    gpx += '<trk><name>Milk Run Route Path</name><trkseg>\n'
    for lat, lon in geometry:
        gpx += f'<trkpt lat="{lat}" lon="{lon}"></trkpt>\n'
    gpx += '</trkseg></trk>\n</gpx>'
    return gpx

def get_auto_fuel_prices():
    return {"Diesel": 32.94, "Gasohol 95": 36.55, "Gasohol 91": 36.18, "Gasohol E20": 34.44, "Benzine": 44.34}

def parse_time_val(time_val, default_time):
    if pd.isna(time_val) or time_val == "": return default_time
    if isinstance(time_val, datetime.time): return time_val
    time_str = str(time_val).strip()
    match = re.search(r'(\d{1,2}):(\d{2})', time_str)
    if match: return datetime.time(int(match.group(1)), int(match.group(2)))
    return default_time

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

# --- อัลกอริทึมที่เหลืออยู่ ---
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
            elif r_i[0] == i and r_j[0] == j: routes.remove(r_i); routes.remove(r_j); routes.insert(0, list(reversed(r_i)) + r_j)
            elif r_i[-1] == i and r_j[-1] == j: routes.remove(r_i); routes.remove(r_j); routes.insert(0, r_i + list(reversed(r_j)))
    final_nodes = []
    for r in routes: final_nodes.extend(r)
    return [0] + final_nodes

# ==========================================
# หน้าเว็บ Streamlit
# ==========================================
st.set_page_config(page_title="Milk Run Optimization & Dashboard", layout="wide")
st.title("🚚 SUT Daily Route Planing")

uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์สถานที่ (Excel / CSV)", type=["xlsx", "csv"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file)
        else: df = pd.read_excel(uploaded_file)
        
        # เลือกวันที่ผ่านปฏิทิน
        st.subheader("📅 1. เลือกวันที่ปฏิบัติงาน")
        selected_date = st.date_input("จิ้มเลือกวันที่ต้องการวิ่งงาน", datetime.date.today())
        
        if 'ชื่อสถานที่' in df.columns and 'Lat' in df.columns and 'Lon' in df.columns:
            st.subheader("📝 2. ข้อมูลสถานที่ต้นทางและลูกค้า")
            if 'เริ่มรับได้' not in df.columns: df['เริ่มรับได้'] = ""
            if 'ต้องส่งก่อน' not in df.columns: df['ต้องส่งก่อน'] = ""
            edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

            st.markdown("---")
            with st.expander("⚙️ 3. ตั้งค่าพารามิเตอร์รถขนส่ง", expanded=True):
                col1, col2, col3 = st.columns(3)
                with col1: empty_speed = st.number_input("ความเร็วรถเปล่า (กม./ชม.)", value=50.0)
                with col2: full_speed = st.number_input("ความเร็วรถตอนหนักสุด (กม./ชม.)", value=35.0)
                with col3: max_capacity = st.number_input("พิกัดความจุสูงสุด (กก.)", value=1200.0)

            st.subheader("🧠 4. เลือกวิธีจัดเรียงเส้นทาง")
            algo_choice = st.radio("รูปแบบ:", ("1. ลำดับตามไฟล์ดั้งเดิม", "2. Nearest Neighbor Heuristic", "3. Saving Heuristic"))
            
            if "Nearest Neighbor" in algo_choice:
                best_indices = nearest_neighbor_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            elif "Saving" in algo_choice:
                best_indices = savings_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            else:
                optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)

            # คำนวณตารางเดินรถ
            road_geometry, road_distances = get_osrm_route(optimized_df)
            current_datetime = datetime.datetime.combine(selected_date, datetime.time(11, 0))
            schedule_data = []
            
            for i in range(len(optimized_df)):
                row = optimized_df.iloc[i]
                dist = 0 if i == 0 else (road_distances[i-1] if road_distances else calculate_distance(optimized_df.iloc[i-1]['Lat'], optimized_df.iloc[i-1]['Lon'], row['Lat'], row['Lon']))
                current_datetime += datetime.timedelta(minutes=(dist/50)*60)
                schedule_data.append({"ลำดับ": i, "ชื่อสถานที่": row['ชื่อสถานที่'], "เวลาถึง (ETA)": current_datetime.strftime("%H:%M:%S")})

            st.subheader("📊 5. สรุปผลลัพธ์")
            st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)
            m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)
            if road_geometry: AntPath(road_geometry, color="blue", weight=5).add_to(m)
            st_folium(m, width=1000, height=500)
    except Exception as e: st.error(f"Error: {e}")
else: st.info("อัปโหลดไฟล์เพื่อเริ่มต้น")
