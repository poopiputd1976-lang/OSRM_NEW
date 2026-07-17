import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import math
import datetime
import requests

# --- ส่วนดึงราคาน้ำมัน (ตัวเดิมของคุณ) ---
def get_fuel_prices_api():
    url = "https://api.chnwt.dev/thai-oil-api/latest"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json().get("response")
    except:
        return None
    return None

# --- ส่วน OSRM และการคำนวณ (ตัวเดิมของคุณที่ผมกู้คืนมาให้ครบครับ) ---
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
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

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

# --- หน้าจอหลัก (ตัวเดิมที่รวมทุกอย่าง) ---
st.set_page_config(page_title="Milk Run Optimization", layout="wide")
st.title("🚚 SUT Daily Route Planning")

# แสดงราคาน้ำมัน (ตัวเดิม)
st.subheader("⛽ ราคาน้ำมันอัปเดตล่าสุด")
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
        if rows: st.dataframe(pd.DataFrame(rows), use_container_width=True)
    except: st.write("ไม่สามารถแสดงตารางได้")
else: st.error("ดึงข้อมูลไม่ได้")

# อัปโหลดไฟล์และคำนวณ (ตัวเดิม)
uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์สถานที่ (Excel / CSV)", type=["xlsx", "csv"])
if uploaded_file is not None:
    df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
    edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
    algo_choice = st.radio("รูปแบบ:", ("ลำดับไฟล์", "Nearest Neighbor", "Saving Heuristic"))
    
    if "Nearest" in algo_choice:
        best_indices = nearest_neighbor_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
    elif "Saving" in algo_choice:
        best_indices = savings_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
    else:
        optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)

    road_geometry, road_distances = get_osrm_route(optimized_df)
    st.subheader("📊 ผลลัพธ์")
    st.dataframe(optimized_df, use_container_width=True)
    
    m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)
    if road_geometry: AntPath(road_geometry, color="blue", weight=5).add_to(m)
    for i, row in optimized_df.iterrows():
        folium.Marker([row['Lat'], row['Lon']], popup=f"{i}: {row['ชื่อสถานที่']}").add_to(m)
    st_folium(m, width=1000, height=500)
