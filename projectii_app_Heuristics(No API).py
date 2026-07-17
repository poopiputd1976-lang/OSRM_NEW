import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import math
import datetime
import requests

# ... (เก็บฟังก์ชัน get_osrm_route, calculate_distance, nearest_neighbor_route, savings_route ไว้เหมือนเดิม) ...

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
        
        # 1. ส่วนกำหนดการและ Service Time
        st.subheader("📅 1. กำหนดการและค่าพารามิเตอร์")
        col1, col2, col3 = st.columns(3)
        with col1: 
            selected_date = st.date_input("วันที่ปฏิบัติงาน", datetime.date.today())
        with col2: 
            start_time = st.time_input("เวลาเริ่มปฏิบัติงาน", datetime.time(8, 0))
        with col3:
            # นี่คือส่วน Interface ใหม่ที่คุณต้องการ
            service_time_input = st.number_input("เวลาจอดลงของต่อจุด (วินาที)", min_value=0, value=300, step=10)
        
        if 'ชื่อสถานที่' in df.columns and 'Lat' in df.columns and 'Lon' in df.columns:
            st.subheader("📝 2. ข้อมูลสถานที่ต้นทางและลูกค้า")
            edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

            # ... (ส่วนการเลือกอัลกอริทึมเหมือนเดิม) ...
            st.subheader("🧠 3. เลือกวิธีจัดเรียงเส้นทาง")
            algo_choice = st.radio("รูปแบบ:", ("1. ลำดับตามไฟล์ดั้งเดิม", "2. Nearest Neighbor Heuristic", "3. Saving Heuristic"))
            
            if "Nearest Neighbor" in algo_choice:
                best_indices = nearest_neighbor_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            elif "Saving" in algo_choice:
                best_indices = savings_route(edited_df); best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            else:
                optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)

            # คำนวณตารางเดินรถ
            road_geometry, road_distances = get_osrm_route(optimized_df)
            current_datetime = datetime.datetime.combine(selected_date, start_time)
            schedule_data = []
            
            for i in range(len(optimized_df)):
                row = optimized_df.iloc[i]
                
                # เพิ่มเวลาเดินทาง
                if i > 0:
                    dist = road_distances[i-1] if road_distances else calculate_distance(optimized_df.iloc[i-1]['Lat'], optimized_df.iloc[i-1]['Lon'], row['Lat'], row['Lon'])
                    current_datetime += datetime.timedelta(minutes=(dist/50)*60)
                
                # เพิ่มเวลา Service Time ที่กรอกใน Interface (ใช้ค่าจาก service_time_input)
                current_datetime += datetime.timedelta(seconds=service_time_input)
                
                schedule_data.append({"ลำดับ": i, "ชื่อสถานที่": row['ชื่อสถานที่'], "เวลาถึง (ETA)": current_datetime.strftime("%H:%M:%S")})

            st.subheader("📊 4. สรุปผลลัพธ์")
            st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)
            # ... (ส่วนแสดงแผนที่เหมือนเดิม) ...
            m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)
            if road_geometry: AntPath(road_geometry, color="blue", weight=5).add_to(m)
            st_folium(m, width=1000, height=500)

    except Exception as e: st.error(f"เกิดข้อผิดพลาด: {e}")
