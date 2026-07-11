import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath  # เพิ่มการเรียกใช้ AntPath
from streamlit_folium import st_folium
import math
import datetime
import requests
import re

# --- ฟังก์ชันสร้างไฟล์ KML ---
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

# --- ฟังก์ชันสร้างไฟล์ GPX ---
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

# --- ฟังก์ชันดึงราคาน้ำมันอัตโนมัติ (ปตท.) ---
@st.cache_data(ttl=3600)
def get_auto_fuel_prices():
    fallback_prices = {
        "Diesel": 32.94, "Gasohol 95": 36.55, "Gasohol 91": 36.18, 
        "Gasohol E20": 34.44, "Benzine": 44.34
    }
    try:
        url = "https://api.chnwt.dev/thai-oil-api/latest"
        res = requests.get(url, timeout=5).json()
        ptt_data = res.get('response', {}).get('stations', {}).get('ptt', {})
        if not ptt_data: return fallback_prices
        fetched_prices = {}
        for name, info in ptt_data.items():
            if isinstance(info, dict) and 'price' in info and info['price']:
                try: fetched_prices[name] = float(info['price'])
                except: pass
        return fetched_prices if fetched_prices else fallback_prices
    except Exception:
        return fallback_prices

# --- ฟังก์ชันอ่านค่าเวลาจาก Excel อย่างปลอดภัย ---
def parse_time_val(time_val, default_time):
    if pd.isna(time_val) or time_val == "": return default_time
    if isinstance(time_val, datetime.time): return time_val
    if isinstance(time_val, datetime.datetime): return time_val.time()
    time_str = str(time_val).strip()
    match = re.search(r'(\d{1,2}):(\d{2})', time_str)
    if match: return datetime.time(int(match.group(1)), int(match.group(2)))
    return default_time

# --- ฟังก์ชันดึงเส้นทางถนนจริงจาก OSRM ---
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
    except Exception as e:
        pass
    return None, None

# --- ฟังก์ชันคำนวณระยะทางเส้นตรง ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0 
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# --- Algorithms ---
def nearest_neighbor_route(df):
    unvisited = list(range(1, len(df))); route = [0]; current = 0
    while unvisited:
        next_node = min(unvisited, key=lambda x: calculate_distance(df.iloc[current]['Lat'], df.iloc[current]['Lon'], df.iloc[x]['Lat'], df.iloc[x]['Lon']))
        route.append(next_node); current = next_node; unvisited.remove(next_node)
    return route

# --- Kruskal's MST Heuristic (แทนที่ Sweep) ---
def kruskal_route(df):
    n = len(df)
    if n <= 1: return list(range(n))
    
    # 1. สร้าง Edges ทั้งหมด
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            dist = calculate_distance(df.iloc[i]['Lat'], df.iloc[i]['Lon'], df.iloc[j]['Lat'], df.iloc[j]['Lon'])
            edges.append((dist, i, j))
    
    # เรียงลำดับ Edge จากสั้นไปยาว
    edges.sort(key=lambda x: x[0])
    
    # 2. Disjoint Set (Union-Find) สำหรับ Kruskal
    parent = list(range(n))
    def find(i):
        if parent[i] == i: return i
        parent[i] = find(parent[i]) # Path compression
        return parent[i]
    
    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j
            
    # 3. สร้าง Minimum Spanning Tree (MST)
    mst = {i: [] for i in range(n)}
    for dist, i, j in edges:
        if find(i) != find(j):
            union(i, j)
            mst[i].append(j)
            mst[j].append(i)
            
    # 4. เดินตามเส้นทางต้นไม้ (DFS Pre-order Traversal) เพื่อแปลงเป็นลูป
    visited = [False] * n
    route = []
    stack = [0] # เริ่มที่คลังสินค้า
    
    while stack:
        node = stack.pop()
        if not visited[node]:
            visited[node] = True
            route.append(node)
            # เพิ่มเพื่อนบ้านลงใน Stack
            for neighbor in reversed(mst[node]):
                if not visited[neighbor]:
                    stack.append(neighbor)
                    
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
            
        if 'ชื่อสถานที่' in df.columns and 'Lat' in df.columns and 'Lon' in df.columns:
            st.subheader("📝 1. ข้อมูลสถานที่ต้นทางและลูกค้า")
            
            if 'เริ่มรับได้' not in df.columns: df['เริ่มรับได้'] = ""
            if 'ต้องส่งก่อน' not in df.columns: df['ต้องส่งก่อน'] = ""
                
            edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

            st.markdown("---")
            with st.expander("⚙️ 2. ตั้งค่าพารามิเตอร์รถขนส่งและสิ่งแวดล้อม", expanded=True):
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
                default_index = next((idx for idx, opt in enumerate(fuel_options) if "diesel" in opt.lower() or "ดีเซล" in opt), 0)
                with c_col4: selected_fuel = st.selectbox("ชนิดน้ำมัน", fuel_options, index=default_index)
                with c_col5: fuel_price = st.number_input(f"ราคา (บาท/ลิตร)", value=float(fuel_prices_dict.get(selected_fuel, 32.50)))

            st.markdown("---")
            st.subheader("🧠 3. เลือกวิธีจัดเรียงเส้นทาง")
            algo_choice = st.radio(
                "รูปแบบการจัดเส้นทาง (ทุกวิธีจะวิ่งลูปกลับมาคลังจุดเริ่มต้นอัตโนมัติ และคำนวณกรอบเวลาความเร็วผกผัน):",
                ("1. ลำดับตามไฟล์ดั้งเดิม", "2. Nearest Neighbor Heuristic", "3. Kruskal's Heuristic", "4. Insertion Heuristic", "5. Saving Heuristic")
            )

            is_optimized = False
            if "Nearest Neighbor" in algo_choice:
                best_indices = nearest_neighbor_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True); is_optimized = True
            elif "Kruskal's" in algo_choice:
                best_indices = kruskal_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True); is_optimized = True
            elif "Insertion" in algo_choice:
                best_indices = nearest_insertion_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True); is_optimized = True
            elif "Saving" in algo_choice:
                best_indices = savings_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True); is_optimized = True
            else:
                optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)

            road_geometry, road_distances = get_osrm_route(optimized_df)

            col_weight_total = 'น้ำหนักที่ส่ง (กก.)'
            col_real_dist = 'ระยะห่างระหว่างแต่ละจุด (กม.)'
            has_real_dist = col_real_dist in optimized_df.columns

            has_detailed_columns = all(c in optimized_df.columns for c in [col_m200, col_m2l, col_m5l, col_y65])

            if has_detailed_columns:
                q_m200 = pd.to_numeric(optimized_df[col_m200], errors='coerce').fillna(0)
                q_m2l = pd.to_numeric(optimized_df[col_m2l], errors='coerce').fillna(0)
                q_m5l = pd.to_numeric(optimized_df[col_m5l], errors='coerce').fillna(0)
                q_y65 = pd.to_numeric(optimized_df[col_y65], errors='coerce').fillna(0)
                
                w_m200 = q_m200 * (w_m200_net + w_m200_pkg)
                w_m2l = q_m2l * (w_m2l_net + w_m2l_pkg)
                w_m5l = q_m5l * (w_m5l_net + w_m5l_pkg)
                w_y65 = q_y65 * (w_y65_net + w_y65_pkg)
                
                weight_list = (w_m200 + w_m2l + w_m5l + w_y65).tolist()
            elif col_weight_total in optimized_df.columns:
                weight_list = pd.to_numeric(optimized_df[col_weight_total], errors='coerce').fillna(0).tolist()
            else:
                weight_list = [0.0] * len(optimized_df)

            weight_list[-1] = 0.0 
            total_initial_weight = sum(weight_list)
            current_weight = total_initial_weight

            current_datetime = datetime.datetime.combine(datetime.date.today(), start_time)
            schedule_data = []
            total_distance = 0.0
            total_travel_mins = 0.0
            total_wait_mins = 0.0
            map_markers = []

            for i in range(len(optimized_df)):
                row = optimized_df.iloc[i]
                map_markers.append([row['Lat'], row['Lon']])
                
                if max_capacity > 0:
                    weight_ratio = min(current_weight / max_capacity, 1.0)
                    current_speed = empty_speed - ((empty_speed - full_speed) * weight_ratio)
                else: 
                    current_speed = empty_speed
                current_speed = max(current_speed, 10.0) 

                if i == 0:
                    dist = 0.0; travel_mins = 0
                else:
                    if not is_optimized and has_real_dist:
                        try: dist = float(row[col_real_dist])
                        except: dist = 0.0
                    elif road_distances: dist = road_distances[i-1] 
                    else: dist = calculate_distance(optimized_df.iloc[i-1]['Lat'], optimized_df.iloc[i-1]['Lon'], row['Lat'], row['Lon'])
                    
                    travel_mins = (dist / current_speed) * 60
                
                total_distance += dist
                total_travel_mins += travel_mins
                current_datetime += datetime.timedelta(minutes=travel_mins)
                
                arrival_time = current_datetime.strftime("%H:%M:%S")
                status = "✅ ปกติ"
                wait_mins = 0
                
                if i > 0 and i < len(optimized_df) - 1:
                    open_time = parse_time_val(row.get('เริ่มรับได้', ''), datetime.time(0, 0))
                    close_time = parse_time_val(row.get('ต้องส่งก่อน', ''), datetime.time(23, 59))
                    open_dt = datetime.datetime.combine(current_datetime.date(), open_time)
                    close_dt = datetime.datetime.combine(current_datetime.date(), close_time)
                    
                    if current_datetime < open_dt:
                        wait_mins = (open_dt - current_datetime).total_seconds() / 60.0
                        total_wait_mins += wait_mins
                        current_datetime = open_dt 
                        status = f"⏳ รอเริ่มรับ {int(wait_mins)} นาที"
                    elif current_datetime > close_dt:
                        status = "❌ ล่าช้า"
                
                if i == len(optimized_df) - 1: departure_time = "-"
                else:
                    current_datetime += datetime.timedelta(minutes=service_time)
                    departure_time = current_datetime.strftime("%H:%M:%S")
                
                display_name = f"🔄 กลับสู่: {row['ชื่อสถานที่']}" if i == len(optimized_df) - 1 else row['ชื่อสถานที่']

                schedule_data.append({
                    "ลำดับ": i,
                    "ชื่อสถานที่": display_name,
                    "สถานะ": status,
                    "ถึง (ETA)": arrival_time,
                    "เวลาออก": departure_time,
                    "ระยะทาง (กม.)": f"{dist:.2f}",
                    "นน. บรรทุกสะสมช่วงนี้ (กก.)": f"{current_weight:.2f}",
                    "ความเร็วช่วงนี้": f"{current_speed:.1f} กม./ชม."
                })
                current_weight = max(current_weight - weight_list[i], 0)

            total_co2 = (total_distance / fuel_rate if fuel_rate > 0 else 0) * co2_rate
            total_time_mins = total_travel_mins + total_wait_mins + ((len(optimized_df) - 1) * service_time)
            
            st.markdown("---\n")
            st.subheader("📊 4. สรุปผลลัพธ์การเดินรถรวม")
            
            st.markdown("##### ⚖️ สถานะความจุพิกัดรถ (Capacity Progress)")
            capacity_percent = min((total_initial_weight / max_capacity) * 100, 100) if max_capacity > 0 else 0
            
            if capacity_percent >= 100:
                st.error(f"⚠️ Overload! น้ำหนักบรรทุกรวม {total_initial_weight:.2f} กก. (เกินพิกัดรถ {max_capacity} กก.)")
                st.progress(1.0)
            elif capacity_percent >= 80:
                st.warning(f"🟡 ใกล้เต็มความจุ: น้ำหนักบรรทุกรวม {total_initial_weight:.2f} กก. จาก {max_capacity} กก. ({capacity_percent:.1f}%)")
                st.progress(capacity_percent / 100.0)
            else:
                st.success(f"🟢 สถานะปกติ: น้ำหนักบรรทุกรวม {total_initial_weight:.2f} กก. จาก {max_capacity} กก. ({capacity_percent:.1f}%)")
                st.progress(capacity_percent / 100.0)

            st.write("") 
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("ระยะทางรวมทั้งสิ้น", f"{total_distance:.2f} กม.")
            m2.metric(f"ต้นทุนน้ำมัน ({selected_fuel})", f"฿{((total_distance/fuel_rate) * fuel_price) if fuel_rate > 0 else 0:.2f}")
            m3.metric("คาร์บอนฟุตพริ้นท์ (CO2e)", f"{total_co2:.2f} kg")
            m4.metric("เวลาจบงาน (ถึงจุดเริ่มต้น)", f"{int(total_time_mins//60)} ชม. {int(total_time_mins%60)} น.")

            if total_wait_mins > 0:
                st.warning(f"⚠️ มีการเสียเวลาจอดรอร้านเริ่มรับสินค้ารวมทั้งสิ้น {int(total_wait_mins)} นาที (ตรวจสอบจุดที่ต้องรอในตารางด้านล่าง)")

            st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)

            st.markdown("---")
            st.subheader("📍 5. แผนที่เส้นทางเดินรถ Closed-Loop")
            m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)
            export_geometry = road_geometry if road_geometry else map_markers

            # --- แก้ไขจาก PolyLine เป็น AntPath เพื่อแสดงแอนิเมชันทิศทาง ---
            if road_geometry: 
                AntPath(road_geometry, color="blue", pulse_color="white", weight=5, delay=800).add_to(m)
            else: 
                AntPath(map_markers, color="red", pulse_color="yellow", weight=4, delay=800).add_to(m)

            for i in range(len(optimized_df) - 1):
                row = optimized_df.iloc[i]
                html = f"<b>ลำดับคิว {i}: {row['ชื่อสถานที่']}</b><br>เวลาถึง: {schedule_data[i]['ถึง (ETA)']}<br>สถานะ: {schedule_data[i]['สถานะ']}<br>น้ำหนักบรรทุกช่วงนี้: {schedule_data[i]['นน. บรรทุกสะสมช่วงนี้ (กก.)']} กก."
                color_bg = "#ff2200" if i == 0 else ("#ff9900" if "รอเริ่มรับ" in schedule_data[i]['สถานะ'] else ("#cc0000" if "ล่าช้า" in schedule_data[i]['สถานะ'] else "#0078ff"))
                label_text = "คลัง" if i == 0 else str(i)
                icon = folium.DivIcon(html=f"""<div style="background-color:{color_bg}; color:white; border-radius:50%; width:32px; height:32px; display:flex; justify-content:center; align-items:center; font-weight:bold; border:2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);">{label_text}</div>""", icon_anchor=(16, 16))
                folium.Marker(location=[row['Lat'], row['Lon']], popup=html, icon=icon).add_to(m)

            st_folium(m, width=1000, height=600)

            st.markdown("---")
            st.subheader("📥 6. ดาวน์โหลดเส้นทาง (Export Route)")
            dl_col1, dl_col2 = st.columns(2)
            kml_data = create_kml(optimized_df, export_geometry)
            gpx_data = create_gpx(optimized_df, export_geometry)
            
            with dl_col1:
                st.download_button(label="🌍 ดาวน์โหลดไฟล์ KML", data=kml_data, file_name="milk_run_route.kml", mime="application/vnd.google-earth.kml+xml")
            with dl_col2:
                st.download_button(label="📡 ดาวน์โหลดไฟล์ GPX", data=gpx_data, file_name="milk_run_route.gpx", mime="application/gpx+xml")
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผล: {e}")
else:
    st.info("👆 อัปโหลดไฟล์สถานที่เพื่อเริ่มต้นใช้งาน")
