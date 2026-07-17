import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import math
import datetime

# --- ฟังก์ชันคำนวณ ---
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
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
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

# --- หน้าเว็บ ---
st.set_page_config(page_title="Milk Run Optimization", layout="wide")
st.title("🚚 SUT Daily Route Planning")

# --- ส่วนกรอกราคาน้ำมันเอง (แทนที่ API) ---
st.subheader("⛽ กรอกราคาน้ำมันอ้างอิง")
with st.expander("คลิกเพื่อกรอกราคาน้ำมัน"):
    col_a, col_b, col_c = st.columns(3)
    gas_95 = col_a.number_input("Gasohol 95", value=35.0)
    diesel = col_b.number_input("Diesel", value=32.0)
    e20 = col_c.number_input("Gasohol E20", value=33.0)
    st.info(f"ราคาน้ำมันที่ใช้คำนวณ: Gas 95 = {gas_95}, Diesel = {diesel}, E20 = {e20}")

# --- ส่วนอัปโหลดและคำนวณ ---
uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์สถานที่ (Excel / CSV)", type=["xlsx", "csv"])

if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        
        st.subheader("📅 1. กำหนดการ")
        col1, col2, col3 = st.columns(3)
        selected_date = col1.date_input("วันที่", datetime.date.today())
        start_time = col2.time_input("เวลาเริ่ม", datetime.time(8, 0))
        service_time = col3.number_input("เวลาจอด (วินาที)", value=300)
        
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        
        # จัดเรียงเส้นทาง
        algo_choice = st.radio("วิธีจัดเรียง:", ("ลำดับไฟล์", "Nearest Neighbor", "Saving Heuristic"))
        if "Nearest" in algo_choice:
            idx = nearest_neighbor_route(edited_df); idx.append(0); opt_df = edited_df.iloc[idx].reset_index(drop=True)
        elif "Saving" in algo_choice:
            idx = savings_route(edited_df); idx.append(0); opt_df = edited_df.iloc[idx].reset_index(drop=True)
        else:
            opt_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)

        st.subheader("📊 ผลลัพธ์")
        st.dataframe(opt_df, use_container_width=True)
        
        # แผนที่
        m = folium.Map(location=[opt_df['Lat'].mean(), opt_df['Lon'].mean()], zoom_start=14)
        for i in range(len(opt_df)):
            folium.Marker([opt_df.iloc[i]['Lat'], opt_df.iloc[i]['Lon']], popup=opt_df.iloc[i]['ชื่อสถานที่']).add_to(m)
        st_folium(m, width=1000, height=400)
        
    except Exception as e: st.error(f"Error: {e}")
