import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import math
import datetime
import requests
import re

# --- ฟังก์ชันต่างๆ (คงเดิม) ---
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

# --- Algorithms (คงเดิม) ---
def nearest_neighbor_route(df):
    unvisited = list(range(1, len(df))); route = [0]; current = 0
    while unvisited:
        next_node = min(unvisited, key=lambda x: calculate_distance(df.iloc[current]['Lat'], df.iloc[current]['Lon'], df.iloc[x]['Lat'], df.iloc[x]['Lon']))
        route.append(next_node); current = next_node; unvisited.remove(next_node)
    return route

def kruskal_route(df):
    n = len(df)
    if n <= 1: return list(range(n))
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            dist = calculate_distance(df.iloc[i]['Lat'], df.iloc[i]['Lon'], df.iloc[j]['Lat'], df.iloc[j]['Lon'])
            edges.append((dist, i, j))
    edges.sort(key=lambda x: x[0])
    parent = list(range(n))
    def find(i):
        if parent[i] == i: return i
        parent[i] = find(parent[i]); return parent[i]
    def union(i, j):
        root_i = find(i); root_j = find(j)
        if root_i != root_j: parent[root_i] = root_j
    mst = {i: [] for i in range(n)}
    for dist, i, j in edges:
        if find(i) != find(j):
            union(i, j); mst[i].append(j); mst[j].append(i)
    visited = [False] * n; route = []; stack = [0]
    while stack:
        node = stack.pop()
        if not visited[node]:
            visited[node] = True; route.append(node)
            for neighbor in reversed(mst[node]):
                if not visited[neighbor]: stack.append(neighbor)
    return route

def nearest_insertion_route(df):
    if len(df) <= 2: return list(range(len(df)))
    unvisited = list(range(1, len(df))); route = [0]
    first_node = min(unvisited, key=lambda x: calculate_distance(df.iloc[0]['Lat'], df.iloc[0]['Lon'], df.iloc[x]['Lat'], df.iloc[x]['Lon']))
    route.append(first_node); unvisited.remove(first_node)
    while unvisited:
        best_node = None; min_dist_to_route = float('inf')
        for u in unvisited:
            for r in route:
                d = calculate_distance(df.iloc[u]['Lat'], df.iloc[u]['Lon'], df.iloc[r]['Lat'], df.iloc[r]['Lon'])
                if d < min_dist_to_route: min_dist_to_route = d; best_node = u
        best_pos = 1; min_added_dist = float('inf')
        for i in range(1, len(route) + 1):
            prev_n = route[i-1]; next_n = route[i] if i < len(route) else route[0]
            dist_added = (calculate_distance(df.iloc[prev_n]['Lat'], df.iloc[prev_n]['Lon'], df.iloc[best_node]['Lat'], df.iloc[best_node]['Lon']) +
                          calculate_distance(df.iloc[best_node]['Lat'], df.iloc[best_node]['Lon'], df.iloc[next_n]['Lat'], df.iloc[next_n]['Lon']) -
                          calculate_distance(df.iloc[prev_n]['Lat'], df.iloc[prev_n]['Lon'], df.iloc[next_n]['Lat'], df.iloc[next_n]['Lon']))
            if dist_added < min_added_dist: min_added_dist = dist_added; best_pos = i
        route.insert(best_pos, best_node); unvisited.remove(best_node)
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
# เริ่มหน้าเว็บ Streamlit
# ==========================================
st.set_page_config(page_title="Milk Run Optimization & Dashboard", layout="wide")
st.title("🚚 SUT Daily Route Planing")

uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์สถานที่ (Excel / CSV)", type=["xlsx", "csv"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file)
        else: df = pd.read_excel(uploaded_file)
        
        # --- [ส่วนใหม่: เลือกวันที่โดยตรงผ่านปฏิทิน] ---
        st.subheader("📅 1. เลือกวันที่ปฏิบัติงาน")
        selected_date = st.date_input("จิ้มเลือกวันที่ต้องการวิ่งงาน", datetime.date.today())
        st.info(f"ระบบกำลังจัดการตารางงานสำหรับวันที่: **{selected_date}**")
        # -------------------------------------------
            
        if 'ชื่อสถานที่' in df.columns and 'Lat' in df.columns and 'Lon' in df.columns:
            st.subheader("📝 2. ข้อมูลสถานที่ต้นทางและลูกค้า")
            if 'เริ่มรับได้' not in df.columns: df['เริ่มรับได้'] = ""
            if 'ต้องส่งก่อน' not in df.columns: df['ต้องส่งก่อน'] = ""
            edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

            st.markdown("---")
            with st.expander("⚙️ 3. ตั้งค่าพารามิเตอร์รถขนส่งและสิ่งแวดล้อม", expanded=True):
                w_m200_net, w_m200_pkg = 0.200, 0.015
                w_m2l_net, w_m2l_pkg = 2.000, 0.070
                w_m5l_net, w_m5l_pkg = 5.000, 0.140
                w_y65_net, w_y65_pkg = 0.065, 0.006
                col_m200, col_m2l, col_m5l, col_y65 = '200cc', '2L', '5L', 'Yogurt'
                t_col1, t_col2, t_col3, t_col4 = st.columns(4)
                with t_col1: empty_speed = st.number_input("ความเร็วรถเปล่า (กม./ชม.)", value=50.0)
                with t_col2: full_speed = st.number_input("ความเร็วรถตอนหนักสุด (กม./ชม.)", value=35.0)
                with t_col3: max_capacity = st.number_input("พิกัดความจุรถสูงสุด (กก.)", value=1200.0)
                with t_col4: start_time = st.time_input("เวลาออกเดินทาง", datetime.time(11, 0))
                c_col1, c_col2, c_col3, c_col4, c_col5 = st.columns(5)
                with c_col1: service_time = st.number_input("เวลาลงของ/จุด (นาที)", value=3)
                with c_col2: fuel_rate = st.number_input("สิ้นเปลือง (กม./ลิตร)", value=10.0)
                with c_col3: co2_rate = st.number_input("ปล่อย CO2 (kg/ลิตร)", value=2.70757206, format="%.8f")
                fuel_prices_dict = get_auto_fuel_prices()
                fuel_options = list(fuel_prices_dict.keys())
                with c_col4: selected_fuel = st.selectbox("ชนิดน้ำมัน", fuel_options)
                with c_col5: fuel_price = st.number_input(f"ราคา (บาท/ลิตร)", value=float(fuel_prices_dict.get(selected_fuel, 32.50)))

            st.subheader("🧠 4. เลือกวิธีจัดเรียงเส้นทาง")
            algo_choice = st.radio("รูปแบบการจัดเส้นทาง:", ("1. ลำดับตามไฟล์ดั้งเดิม", "2. Nearest Neighbor Heuristic", "3. Kruskal's Heuristic", "4. Insertion Heuristic", "5. Saving Heuristic"))
            
            if "Nearest Neighbor" in algo_choice:
                best_indices = nearest_neighbor_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            elif "Kruskal's" in algo_choice:
                best_indices = kruskal_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            elif "Insertion" in algo_choice:
                best_indices = nearest_insertion_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            elif "Saving" in algo_choice:
                best_indices = savings_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            else:
                optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)

            road_geometry, road_distances = get_osrm_route(optimized_df)
            col_weight_total = 'น้ำหนักที่ส่ง (กก.)'
            if all(c in optimized_df.columns for c in [col_m200, col_m2l, col_m5l, col_y65]):
                weight_list = (pd.to_numeric(optimized_df[col_m200], errors='coerce').fillna(0) * (w_m200_net + w_m200_pkg) + 
                               pd.to_numeric(optimized_df[col_m2l], errors='coerce').fillna(0) * (w_m2l_net + w_m2l_pkg) + 
                               pd.to_numeric(optimized_df[col_m5l], errors='coerce').fillna(0) * (w_m5l_net + w_m5l_pkg) + 
                               pd.to_numeric(optimized_df[col_y65], errors='coerce').fillna(0) * (w_y65_net + w_y65_pkg)).tolist()
            elif col_weight_total in optimized_df.columns:
                weight_list = pd.to_numeric(optimized_df[col_weight_total], errors='coerce').fillna(0).tolist()
            else:
                weight_list = [0.0] * len(optimized_df)

            weight_list[-1] = 0.0; current_weight = sum(weight_list)
            current_datetime = datetime.datetime.combine(selected_date, start_time)
            schedule_data = []; total_distance = 0.0

            for i in range(len(optimized_df)):
                row = optimized_df.iloc[i]
                current_speed = max(empty_speed - ((empty_speed - full_speed) * min(current_weight / max_capacity, 1.0)), 10.0) if max_capacity > 0 else empty_speed
                if i == 0: dist = 0.0; travel_mins = 0
                else:
                    dist = road_distances[i-1] if road_distances else calculate_distance(optimized_df.iloc[i-1]['Lat'], optimized_df.iloc[i-1]['Lon'], row['Lat'], row['Lon'])
                    travel_mins = (dist / current_speed) * 60
                total_distance += dist; current_datetime += datetime.timedelta(minutes=travel_mins)
                
                status = "✅ ปกติ"; wait_mins = 0
                if i > 0 and i < len(optimized_df) - 1:
                    open_dt = datetime.datetime.combine(selected_date, parse_time_val(row.get('เริ่มรับได้', ''), datetime.time(0, 0)))
                    close_dt = datetime.datetime.combine(selected_date, parse_time_val(row.get('ต้องส่งก่อน', ''), datetime.time(23, 59)))
                    if current_datetime < open_dt:
                        wait_mins = (open_dt - current_datetime).total_seconds() / 60.0; current_datetime = open_dt; status = f"⏳ รอเริ่มรับ {int(wait_mins)} นาที"
                    elif current_datetime > close_dt: status = "❌ ล่าช้า"
                
                if i == len(optimized_df) - 1: departure_time = "-"
                else: current_datetime += datetime.timedelta(minutes=service_time); departure_time = current_datetime.strftime("%H:%M:%S")
                
                schedule_data.append({"ลำดับ": i, "ชื่อสถานที่": f"🔄 กลับสู่: {row['ชื่อสถานที่']}" if i == len(optimized_df)-1 else row['ชื่อสถานที่'], "สถานะ": status, "ถึง (ETA)": current_datetime.strftime("%H:%M:%S"), "เวลาออก": departure_time, "ระยะทาง (กม.)": f"{dist:.2f}", "นน. บรรทุก": f"{current_weight:.2f}"})
                current_weight = max(current_weight - weight_list[i], 0)

            st.subheader("📊 5. สรุปผลลัพธ์")
            st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)
            m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)
            if road_geometry: AntPath(road_geometry, color="blue", weight=5).add_to(m)
            st_folium(m, width=1000, height=500)
    except Exception as e: st.error(f"Error: {e}")
else: st.info("อัปโหลดไฟล์เพื่อเริ่มต้น")
