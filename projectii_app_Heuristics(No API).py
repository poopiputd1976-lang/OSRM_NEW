import datetime
import json
import math

import folium
import pandas as pd
import requests
import streamlit as st
from folium.plugins import AntPath
from streamlit_folium import st_folium


# =========================================================
# ค่าพารามิเตอร์หลังบ้านสำหรับการใช้น้ำมัน
# =========================================================
# อัตราสิ้นเปลืองขณะรถวิ่ง หน่วยกิโลเมตรต่อลิตร
BACKEND_DRIVING_FUEL_EFFICIENCY_KM_PER_LITER = 10.0

# อัตราการใช้น้ำมันขณะจอดติดเครื่อง หน่วยลิตรต่อชั่วโมง
BACKEND_IDLING_FUEL_RATE_LITER_PER_HOUR = 1.5


# =========================================================
# ฟังก์ชันคำนวณระยะทางและเส้นทาง
# =========================================================
def calculate_distance(lat1, lon1, lat2, lon2):
    """คำนวณระยะทางเส้นตรงแบบ Haversine หน่วยเป็นกิโลเมตร"""
    earth_radius_km = 6371.0

    lat1_rad = math.radians(float(lat1))
    lon1_rad = math.radians(float(lon1))
    lat2_rad = math.radians(float(lat2))
    lon2_rad = math.radians(float(lon2))

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius_km * c


def get_osrm_route(route_df):
    """
    ขอเส้นทางถนนจาก OSRM
    คืนค่า:
        geometry      = พิกัดสำหรับวาดเส้นทาง
        leg_distances = ระยะทางแต่ละช่วง หน่วยกิโลเมตร
        leg_durations = เวลาเดินทางแต่ละช่วง หน่วยวินาที
    """
    if len(route_df) < 2:
        return None, None, None

    try:
        coords = ";".join(
            f"{float(row['Lon'])},{float(row['Lat'])}"
            for _, row in route_df.iterrows()
        )

        url = (
            "https://router.project-osrm.org/route/v1/driving/"
            f"{coords}?overview=full&geometries=geojson&steps=false"
        )

        response = requests.get(url, timeout=20)
        response.raise_for_status()
        result = response.json()

        if result.get("code") != "Ok" or not result.get("routes"):
            return None, None, None

        route = result["routes"][0]

        geometry = [
            [coordinate[1], coordinate[0]]
            for coordinate in route["geometry"]["coordinates"]
        ]
        leg_distances = [
            leg["distance"] / 1000.0
            for leg in route["legs"]
        ]
        leg_durations = [
            leg["duration"]
            for leg in route["legs"]
        ]

        return geometry, leg_distances, leg_durations

    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None, None, None


@st.cache_data(ttl=1800)
def get_latest_fuel_prices():
    """
    ดึงราคาน้ำมันล่าสุดจาก Bangchak Web Service

    คืนค่า:
        fuel_data = {
            "prices": {ชื่อชนิดน้ำมัน: ราคา},
            "price_date": วันที่ประกาศ,
            "price_time": เวลาประกาศ,
            "effective_note": หมายเหตุ,
            "source": แหล่งข้อมูล,
        }
        error_message = ข้อผิดพลาด หรือ None
    """
    api_url = "https://oil-price.bangchak.co.th/ApiOilPrice2/th"

    try:
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        raw_data = response.json()

        if not raw_data:
            raise ValueError("API ไม่ส่งข้อมูลราคาน้ำมันกลับมา")

        main_data = raw_data[0]
        oil_list_raw = main_data.get("OilList", [])

        if isinstance(oil_list_raw, str):
            oil_list = json.loads(oil_list_raw)
        elif isinstance(oil_list_raw, list):
            oil_list = oil_list_raw
        else:
            raise ValueError("รูปแบบ OilList ไม่ถูกต้อง")

        fuel_prices = {}

        for oil in oil_list:
            fuel_name = str(oil.get("OilName", "")).strip()
            price_today = oil.get("PriceToday")

            if fuel_name and price_today not in (None, ""):
                try:
                    fuel_prices[fuel_name] = float(price_today)
                except (TypeError, ValueError):
                    continue

        if not fuel_prices:
            raise ValueError("ไม่พบราคาน้ำมันที่ใช้งานได้จาก API")

        return {
            "prices": fuel_prices,
            "price_date": main_data.get("OilPriceDate", "-"),
            "price_time": main_data.get("OilPriceTime", "-"),
            "effective_note": main_data.get("OilRemark2", ""),
            "source": "Bangchak",
        }, None

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        return None, str(error)


# =========================================================
# ฟังก์ชันจัดลำดับจุดส่งภายในรถแต่ละคัน
# =========================================================
def nearest_neighbor_route(route_df):
    """
    route_df ต้องมีคลังเป็นแถวแรก
    คืนลำดับ index โดยเริ่มจากคลัง แต่ยังไม่ใส่คลังปลายทางซ้ำ
    """
    if len(route_df) <= 1:
        return [0]

    unvisited = list(range(1, len(route_df)))
    route = [0]
    current = 0

    while unvisited:
        next_node = min(
            unvisited,
            key=lambda index: calculate_distance(
                route_df.iloc[current]["Lat"],
                route_df.iloc[current]["Lon"],
                route_df.iloc[index]["Lat"],
                route_df.iloc[index]["Lon"],
            ),
        )

        route.append(next_node)
        current = next_node
        unvisited.remove(next_node)

    return route


def savings_route(route_df):
    """
    Clarke-Wright Savings แบบง่ายสำหรับจัดลำดับจุดส่งของรถหนึ่งคัน
    route_df ต้องมีคลังเป็นแถวแรก
    """
    if len(route_df) <= 2:
        return list(range(len(route_df)))

    number_of_rows = len(route_df)
    depot_lat = route_df.iloc[0]["Lat"]
    depot_lon = route_df.iloc[0]["Lon"]

    savings = []

    for i in range(1, number_of_rows):
        for j in range(i + 1, number_of_rows):
            saving_value = (
                calculate_distance(
                    depot_lat,
                    depot_lon,
                    route_df.iloc[i]["Lat"],
                    route_df.iloc[i]["Lon"],
                )
                + calculate_distance(
                    depot_lat,
                    depot_lon,
                    route_df.iloc[j]["Lat"],
                    route_df.iloc[j]["Lon"],
                )
                - calculate_distance(
                    route_df.iloc[i]["Lat"],
                    route_df.iloc[i]["Lon"],
                    route_df.iloc[j]["Lat"],
                    route_df.iloc[j]["Lon"],
                )
            )

            savings.append((saving_value, i, j))

    savings.sort(key=lambda item: item[0], reverse=True)

    routes = [[i] for i in range(1, number_of_rows)]

    for _, i, j in savings:
        route_i = next((route for route in routes if i in route), None)
        route_j = next((route for route in routes if j in route), None)

        if (
            route_i is None
            or route_j is None
            or route_i is route_j
        ):
            continue

        merged_route = None

        if route_i[-1] == i and route_j[0] == j:
            merged_route = route_i + route_j
        elif route_i[0] == i and route_j[-1] == j:
            merged_route = route_j + route_i
        elif route_i[0] == i and route_j[0] == j:
            merged_route = list(reversed(route_i)) + route_j
        elif route_i[-1] == i and route_j[-1] == j:
            merged_route = route_i + list(reversed(route_j))

        if merged_route is not None:
            routes.remove(route_i)
            routes.remove(route_j)
            routes.append(merged_route)

    final_nodes = []
    for route in routes:
        final_nodes.extend(route)

    return [0] + final_nodes


def optimize_single_vehicle_route(vehicle_df, algorithm_choice):
    """
    vehicle_df มีคลังเป็นแถวแรกและลูกค้าของรถคันนั้น
    คืน DataFrame เส้นทางที่เริ่มและจบที่คลัง
    """
    if len(vehicle_df) == 1:
        return pd.concat(
            [vehicle_df, vehicle_df.iloc[[0]]],
            ignore_index=True,
        )

    if "Nearest Neighbor" in algorithm_choice:
        route_indices = nearest_neighbor_route(vehicle_df)
    elif "Saving" in algorithm_choice:
        route_indices = savings_route(vehicle_df)
    else:
        route_indices = list(range(len(vehicle_df)))

    route_indices.append(0)

    return vehicle_df.iloc[route_indices].reset_index(drop=True)


# =========================================================
# ฟังก์ชันคำนวณน้ำหนักจากจำนวนสินค้า
# =========================================================
def calculate_location_weights(
    dataframe,
    weight_200cc_kg,
    weight_2l_kg,
    weight_5l_kg,
    weight_yogurt_kg,
):
    """
    สร้างคอลัมน์น้ำหนัก(กก.) และน้ำหนัก(ตัน)
    จากจำนวนสินค้าในแต่ละจุด
    """
    product_columns = ["200cc", "2L", "5L", "Yogurt"]

    result_df = dataframe.copy()

    for column in product_columns:
        if column not in result_df.columns:
            result_df[column] = 0

        result_df[column] = pd.to_numeric(
            result_df[column],
            errors="coerce",
        ).fillna(0)

    result_df["น้ำหนัก(กก.)"] = (
        result_df["200cc"] * weight_200cc_kg
        + result_df["2L"] * weight_2l_kg
        + result_df["5L"] * weight_5l_kg
        + result_df["Yogurt"] * weight_yogurt_kg
    )

    result_df["น้ำหนัก(ตัน)"] = result_df["น้ำหนัก(กก.)"] / 1000.0

    # แถวแรกเป็นคลัง จึงไม่ถือเป็นน้ำหนักสินค้าที่ต้องส่ง
    if not result_df.empty:
        result_df.loc[result_df.index[0], ["น้ำหนัก(กก.)", "น้ำหนัก(ตัน)"]] = 0.0

    return result_df


# =========================================================
# ฟังก์ชันแบ่งลูกค้าให้รถตามจำนวนรถและความจุ
# =========================================================
def assign_customers_to_vehicles(
    dataframe,
    truck_count,
    max_weight_tons,
):
    """
    แบ่งจุดส่งให้รถแต่ละคันด้วย Best-Fit Decreasing

    เงื่อนไข:
    - แถวแรกเป็นคลัง
    - ลูกค้าหนึ่งจุดจะไม่ถูกแยกสินค้าไปหลายคัน
    - น้ำหนักรวมของรถแต่ละคันต้องไม่เกิน max_weight_tons

    คืนค่า:
        vehicle_assignments = list ของ list index ลูกค้า
        vehicle_loads       = น้ำหนักรวมแต่ละคัน
        error_message       = ข้อผิดพลาด หรือ None
    """
    if truck_count < 1:
        return None, None, "จำนวนรถต้องไม่น้อยกว่า 1 คัน"

    if max_weight_tons <= 0:
        return None, None, "กรุณากำหนดความจุน้ำหนักต่อคันให้มากกว่า 0 ตัน"

    customer_indices = list(range(1, len(dataframe)))

    if not customer_indices:
        return [[] for _ in range(truck_count)], [0.0] * truck_count, None

    customer_weights = {
        index: float(dataframe.iloc[index]["น้ำหนัก(ตัน)"])
        for index in customer_indices
    }

    overweight_customers = [
        index
        for index, weight in customer_weights.items()
        if weight > max_weight_tons + 1e-9
    ]

    if overweight_customers:
        customer_names = [
            str(dataframe.iloc[index]["ชื่อสถานที่"])
            for index in overweight_customers
        ]

        return (
            None,
            None,
            "มีจุดส่งที่น้ำหนักมากกว่าความจุรถหนึ่งคัน: "
            + ", ".join(customer_names),
        )

    total_weight = sum(customer_weights.values())
    total_capacity = truck_count * max_weight_tons

    if total_weight > total_capacity + 1e-9:
        return (
            None,
            None,
            (
                f"น้ำหนักรวม {total_weight:.3f} ตัน "
                f"เกินความจุรวม {total_capacity:.3f} ตัน "
                "กรุณาเพิ่มจำนวนรถหรือเพิ่มความจุต่อคัน"
            ),
        )

    # เรียงจุดที่หนักที่สุดก่อน เพื่อให้แบ่งรถได้มีประสิทธิภาพขึ้น
    sorted_customers = sorted(
        customer_indices,
        key=lambda index: customer_weights[index],
        reverse=True,
    )

    vehicle_assignments = [[] for _ in range(truck_count)]
    vehicle_loads = [0.0] * truck_count

    for customer_index in sorted_customers:
        customer_weight = customer_weights[customer_index]

        feasible_vehicles = [
            vehicle_index
            for vehicle_index in range(truck_count)
            if vehicle_loads[vehicle_index] + customer_weight
            <= max_weight_tons + 1e-9
        ]

        if not feasible_vehicles:
            return (
                None,
                None,
                (
                    "ไม่สามารถแบ่งจุดส่งลงรถได้ภายใต้เงื่อนไขปัจจุบัน "
                    "แม้น้ำหนักรวมอาจไม่เกินความจุรวม "
                    "กรุณาเพิ่มรถหรือเพิ่มความจุต่อคัน"
                ),
            )

        # Best Fit:
        # เลือกรถที่ใส่จุดนี้แล้วเหลือพื้นที่น้อยที่สุด
        selected_vehicle = min(
            feasible_vehicles,
            key=lambda vehicle_index: (
                max_weight_tons
                - (vehicle_loads[vehicle_index] + customer_weight),
                len(vehicle_assignments[vehicle_index]),
            ),
        )

        vehicle_assignments[selected_vehicle].append(customer_index)
        vehicle_loads[selected_vehicle] += customer_weight

    # เรียงกลับตามลำดับเดิมในไฟล์ เพื่อให้ตัวเลือก "ลำดับเดิม" ทำงานถูกต้อง
    for assignment in vehicle_assignments:
        assignment.sort()

    return vehicle_assignments, vehicle_loads, None


# =========================================================
# ฟังก์ชันสร้างตารางเวลา
# =========================================================
def create_vehicle_schedule(
    route_df,
    selected_date,
    start_time,
    service_time_seconds,
    fallback_speed_kmh,
    road_distances,
    road_durations,
    vehicle_number,
):
    """
    สร้าง ETA แยกตามรถ
    หาก OSRM ไม่ตอบ จะใช้ระยะทางเส้นตรงและความเร็วเฉลี่ยที่ผู้ใช้กำหนด
    """
    current_datetime = datetime.datetime.combine(selected_date, start_time)
    schedule_rows = []

    for route_position in range(len(route_df)):
        row = route_df.iloc[route_position]

        if route_position == 0:
            distance_from_previous = 0.0
            travel_seconds = 0.0
            event_name = "ออกจากคลัง"
        else:
            previous_row = route_df.iloc[route_position - 1]

            if (
                road_distances is not None
                and route_position - 1 < len(road_distances)
            ):
                distance_from_previous = road_distances[route_position - 1]
            else:
                distance_from_previous = calculate_distance(
                    previous_row["Lat"],
                    previous_row["Lon"],
                    row["Lat"],
                    row["Lon"],
                )

            if (
                road_durations is not None
                and route_position - 1 < len(road_durations)
            ):
                travel_seconds = road_durations[route_position - 1]
            else:
                travel_seconds = (
                    distance_from_previous / fallback_speed_kmh
                ) * 3600.0

            current_datetime += datetime.timedelta(seconds=travel_seconds)

            if route_position == len(route_df) - 1:
                event_name = "กลับถึงคลัง"
            else:
                event_name = "ส่งสินค้า"

        arrival_time = current_datetime

        # ไม่คิดเวลาจอดบริการที่คลังต้นทางและคลังปลายทาง
        if 0 < route_position < len(route_df) - 1:
            current_datetime += datetime.timedelta(
                seconds=service_time_seconds
            )

        departure_time = current_datetime

        schedule_rows.append(
            {
                "รถคันที่": vehicle_number,
                "ลำดับในเส้นทาง": route_position,
                "สถานะ": event_name,
                "ชื่อสถานที่": row["ชื่อสถานที่"],
                "น้ำหนักจุดนี้ (กก.)": round(
                    float(row.get("น้ำหนัก(กก.)", 0.0)),
                    2,
                ),
                "ระยะจากจุดก่อนหน้า (กม.)": round(
                    distance_from_previous,
                    2,
                ),
                "เวลาถึง (ETA)": arrival_time.strftime("%H:%M:%S"),
                "เวลาออก": departure_time.strftime("%H:%M:%S"),
            }
        )

    return schedule_rows


# =========================================================
# ส่วนหน้าเว็บ
# =========================================================
st.set_page_config(
    page_title="Milk Run Optimization & Dashboard",
    layout="wide",
)

st.title("🚚 SUT Daily Route Planning")

uploaded_file = st.file_uploader(
    "📂 อัปโหลดไฟล์สถานที่ (Excel / CSV)",
    type=["xlsx", "csv"],
)

if uploaded_file is not None:
    try:
        if uploaded_file.name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        required_columns = ["ชื่อสถานที่", "Lat", "Lon"]
        missing_columns = [
            column
            for column in required_columns
            if column not in df.columns
        ]

        if missing_columns:
            st.error(
                "ไฟล์ขาดคอลัมน์ที่จำเป็น: "
                + ", ".join(missing_columns)
            )
            st.stop()

        # ตรวจและแปลง Lat/Lon
        df["Lat"] = pd.to_numeric(df["Lat"], errors="coerce")
        df["Lon"] = pd.to_numeric(df["Lon"], errors="coerce")

        if df[["Lat", "Lon"]].isna().any().any():
            st.error("พบค่า Lat หรือ Lon ที่ว่างหรือไม่ใช่ตัวเลข")
            st.stop()

        st.info(
            "ระบบถือว่าแถวแรกของไฟล์เป็นคลังสินค้า "
            "และแถวถัดไปเป็นจุดส่งสินค้า"
        )

        st.subheader("📅 1. กำหนดการและค่าพารามิเตอร์")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            selected_date = st.date_input(
                "วันที่ปฏิบัติงาน",
                datetime.date.today(),
            )

        with col2:
            start_time = st.time_input(
                "เวลาเริ่มปฏิบัติงาน",
                datetime.time(8, 0),
            )

        with col3:
            service_time_input = st.number_input(
                "เวลาจอดส่งของต่อจุด (วินาที)",
                min_value=0,
                value=300,
                step=10,
            )

        with col4:
            fallback_speed_kmh = st.number_input(
                "ความเร็วเฉลี่ยกรณี OSRM ใช้ไม่ได้ (กม./ชม.)",
                min_value=1.0,
                value=50.0,
                step=1.0,
            )

        st.subheader("📝 2. ข้อมูลสถานที่และจำนวนสินค้า")

        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
        )

        # หลังแก้ไขตาราง ต้องตรวจ Lat/Lon ซ้ำ
        edited_df["Lat"] = pd.to_numeric(
            edited_df["Lat"],
            errors="coerce",
        )
        edited_df["Lon"] = pd.to_numeric(
            edited_df["Lon"],
            errors="coerce",
        )

        if edited_df[["Lat", "Lon"]].isna().any().any():
            st.error("ข้อมูลหลังแก้ไขมี Lat หรือ Lon ที่ไม่ถูกต้อง")
            st.stop()

        st.subheader("⚖️ 3. น้ำหนักสินค้าต่อหน่วย")

        weight_col1, weight_col2, weight_col3, weight_col4 = st.columns(4)

        with weight_col1:
            weight_200cc_kg = st.number_input(
                "200cc ต่อหน่วย (กก.)",
                min_value=0.0,
                value=0.20,
                step=0.01,
                format="%.2f",
            )

        with weight_col2:
            weight_2l_kg = st.number_input(
                "2L ต่อหน่วย (กก.)",
                min_value=0.0,
                value=2.00,
                step=0.10,
                format="%.2f",
            )

        with weight_col3:
            weight_5l_kg = st.number_input(
                "5L ต่อหน่วย (กก.)",
                min_value=0.0,
                value=5.00,
                step=0.10,
                format="%.2f",
            )

        with weight_col4:
            weight_yogurt_kg = st.number_input(
                "Yogurt ต่อหน่วย (กก.)",
                min_value=0.0,
                value=0.20,
                step=0.01,
                format="%.2f",
            )

        weighted_df = calculate_location_weights(
            edited_df,
            weight_200cc_kg,
            weight_2l_kg,
            weight_5l_kg,
            weight_yogurt_kg,
        )

        st.caption(
            "ค่าด้านบนเป็นค่าเริ่มต้นโดยประมาณ "
            "ควรเปลี่ยนเป็นน้ำหนักจริงรวมบรรจุภัณฑ์"
        )

        st.dataframe(
            weighted_df[
                [
                    "ชื่อสถานที่",
                    "200cc",
                    "2L",
                    "5L",
                    "Yogurt",
                    "น้ำหนัก(กก.)",
                    "น้ำหนัก(ตัน)",
                ]
            ],
            use_container_width=True,
        )

        st.subheader("🚛 4. การตั้งค่ารถขนส่ง")

        truck_col1, truck_col2 = st.columns(2)

        with truck_col1:
            truck_count = st.number_input(
                "จำนวนรถ (คัน)",
                min_value=1,
                value=1,
                step=1,
            )

        with truck_col2:
            max_weight = st.number_input(
                "น้ำหนักบรรทุกสูงสุดต่อคัน (ตัน)",
                min_value=0.01,
                max_value=9.50,
                value=1.00,
                step=0.10,
                format="%.2f",
            )

        total_weight = float(
            weighted_df.iloc[1:]["น้ำหนัก(ตัน)"].sum()
        )
        total_capacity = int(truck_count) * float(max_weight)

        metric_col1, metric_col2, metric_col3 = st.columns(3)
        metric_col1.metric(
            "น้ำหนักสินค้ารวม",
            f"{total_weight:.3f} ตัน",
        )
        metric_col2.metric(
            "ความจุรวมของรถ",
            f"{total_capacity:.3f} ตัน",
        )
        metric_col3.metric(
            "ความจุคงเหลือรวม",
            f"{total_capacity - total_weight:.3f} ตัน",
        )

        st.subheader("⛽ 5. ราคาน้ำมัน")

        fuel_data, fuel_error = get_latest_fuel_prices()
        fuel_col1, fuel_col2 = st.columns(2)

        if fuel_data and fuel_data["prices"]:
            available_fuels = list(fuel_data["prices"].keys())
            default_fuel_index = 0

            for index, fuel_name in enumerate(available_fuels):
                if "ดีเซล" in fuel_name:
                    default_fuel_index = index
                    break

            with fuel_col1:
                selected_fuel = st.selectbox(
                    "ชนิดน้ำมัน",
                    available_fuels,
                    index=default_fuel_index,
                )

            latest_fuel_price = float(
                fuel_data["prices"][selected_fuel]
            )

            with fuel_col2:
                fuel_price = st.number_input(
                    "ราคาน้ำมันที่ใช้คำนวณ (บาท/ลิตร)",
                    min_value=0.0,
                    value=latest_fuel_price,
                    step=0.01,
                    format="%.2f",
                )

            st.success(
                f"✅ ราคาล่าสุดจาก {fuel_data['source']}: "
                f"{selected_fuel} = {latest_fuel_price:.2f} บาท/ลิตร"
            )

            st.caption(
                f"ประกาศวันที่ {fuel_data['price_date']} "
                f"เวลา {fuel_data['price_time']} "
                f"{fuel_data['effective_note']}"
            )

        else:
            st.warning(
                "⚠️ ไม่สามารถดึงราคาน้ำมันออนไลน์ได้ "
                "ระบบจะใช้ราคาที่ผู้ใช้กรอกเอง"
            )

            if fuel_error:
                st.caption(f"รายละเอียด: {fuel_error}")

            with fuel_col1:
                selected_fuel = st.selectbox(
                    "ชนิดน้ำมัน",
                    ["ดีเซล", "เบนซิน", "แก๊สโซฮอล์"],
                )

            with fuel_col2:
                fuel_price = st.number_input(
                    "ราคาน้ำมันสำรอง (บาท/ลิตร)",
                    min_value=0.0,
                    value=30.00,
                    step=0.01,
                    format="%.2f",
                )

        st.caption(
            "ระบบใช้อัตราสิ้นเปลืองขณะวิ่งและอัตราการใช้น้ำมันขณะจอด "
            "จากค่าที่กำหนดไว้หลังบ้าน"
        )

        st.subheader("🧠 6. เลือกวิธีจัดลำดับเส้นทาง")

        algorithm_choice = st.radio(
            "รูปแบบ:",
            (
                "1. ลำดับตามไฟล์ดั้งเดิม",
                "2. Nearest Neighbor Heuristic",
                "3. Saving Heuristic",
            ),
        )

        # จุดที่ทำให้จำนวนรถและน้ำหนักมีผลต่อระบบจริง
        vehicle_assignments, vehicle_loads, assignment_error = (
            assign_customers_to_vehicles(
                weighted_df,
                int(truck_count),
                float(max_weight),
            )
        )

        if assignment_error:
            st.error(f"⚠️ {assignment_error}")
            st.stop()

        st.success(
            "✅ แบ่งจุดส่งให้รถแต่ละคันเรียบร้อยแล้ว "
            "โดยน้ำหนักไม่เกินความจุที่กำหนด"
        )

        depot_df = weighted_df.iloc[[0]].copy()

        route_colors = [
            "blue",
            "red",
            "green",
            "purple",
            "orange",
            "darkred",
            "cadetblue",
            "darkgreen",
            "darkblue",
            "pink",
        ]

        map_center = [
            weighted_df["Lat"].mean(),
            weighted_df["Lon"].mean(),
        ]

        route_map = folium.Map(
            location=map_center,
            zoom_start=13,
        )

        all_schedule_rows = []
        assignment_summary_rows = []
        route_summary_rows = []
        total_driving_fuel_liters_all_vehicles = 0.0
        total_idling_fuel_liters_all_vehicles = 0.0
        total_fuel_liters_all_vehicles = 0.0
        total_fuel_cost_all_vehicles = 0.0

        for vehicle_index, customer_indices in enumerate(
            vehicle_assignments
        ):
            vehicle_number = vehicle_index + 1
            vehicle_color = route_colors[
                vehicle_index % len(route_colors)
            ]

            if customer_indices:
                customer_df = weighted_df.iloc[
                    customer_indices
                ].copy()

                vehicle_df = pd.concat(
                    [depot_df, customer_df],
                    ignore_index=True,
                )
            else:
                vehicle_df = depot_df.copy()

            optimized_route_df = optimize_single_vehicle_route(
                vehicle_df,
                algorithm_choice,
            )

            road_geometry, road_distances, road_durations = (
                get_osrm_route(optimized_route_df)
            )

            vehicle_schedule = create_vehicle_schedule(
                optimized_route_df,
                selected_date,
                start_time,
                int(service_time_input),
                float(fallback_speed_kmh),
                road_distances,
                road_durations,
                vehicle_number,
            )

            all_schedule_rows.extend(vehicle_schedule)

            total_route_distance = sum(
                row["ระยะจากจุดก่อนหน้า (กม.)"]
                for row in vehicle_schedule
            )

            # น้ำมันขณะวิ่ง คำนวณจากระยะทางรวม
            driving_fuel_liters = (
                total_route_distance
                / BACKEND_DRIVING_FUEL_EFFICIENCY_KM_PER_LITER
            )

            # น้ำมันขณะจอดติดเครื่อง คำนวณเฉพาะจุดส่งสินค้า
            total_service_seconds = (
                len(customer_indices) * float(service_time_input)
            )
            idling_fuel_liters = (
                total_service_seconds / 3600.0
            ) * BACKEND_IDLING_FUEL_RATE_LITER_PER_HOUR

            estimated_fuel_liters = (
                driving_fuel_liters + idling_fuel_liters
            )
            estimated_fuel_cost = (
                estimated_fuel_liters * float(fuel_price)
            )

            total_driving_fuel_liters_all_vehicles += driving_fuel_liters
            total_idling_fuel_liters_all_vehicles += idling_fuel_liters
            total_fuel_liters_all_vehicles += estimated_fuel_liters
            total_fuel_cost_all_vehicles += estimated_fuel_cost

            route_summary_rows.append(
                {
                    "รถคันที่": vehicle_number,
                    "จำนวนจุดส่ง": len(customer_indices),
                    "น้ำหนักรวม (ตัน)": round(
                        vehicle_loads[vehicle_index],
                        3,
                    ),
                    "ความจุคงเหลือ (ตัน)": round(
                        float(max_weight)
                        - vehicle_loads[vehicle_index],
                        3,
                    ),
                    "ระยะทางรวมโดยประมาณ (กม.)": round(
                        total_route_distance,
                        2,
                    ),
                    "ชนิดน้ำมัน": selected_fuel,
                    "น้ำมันขณะวิ่ง (ลิตร)": round(
                        driving_fuel_liters,
                        2,
                    ),
                    "น้ำมันขณะจอด (ลิตร)": round(
                        idling_fuel_liters,
                        2,
                    ),
                    "น้ำมันรวมโดยประมาณ (ลิตร)": round(
                        estimated_fuel_liters,
                        2,
                    ),
                    "ราคาน้ำมัน (บาท/ลิตร)": round(
                        float(fuel_price),
                        2,
                    ),
                    "ต้นทุนน้ำมันโดยประมาณ (บาท)": round(
                        estimated_fuel_cost,
                        2,
                    ),
                }
            )

            for customer_index in customer_indices:
                customer_row = weighted_df.iloc[customer_index]

                assignment_summary_rows.append(
                    {
                        "รถคันที่": vehicle_number,
                        "ชื่อสถานที่": customer_row["ชื่อสถานที่"],
                        "น้ำหนักจุดนี้ (กก.)": round(
                            float(customer_row["น้ำหนัก(กก.)"]),
                            2,
                        ),
                    }
                )

            if road_geometry:
                AntPath(
                    road_geometry,
                    color=vehicle_color,
                    weight=5,
                    opacity=0.8,
                    tooltip=f"รถคันที่ {vehicle_number}",
                ).add_to(route_map)
            else:
                fallback_coordinates = [
                    [row["Lat"], row["Lon"]]
                    for _, row in optimized_route_df.iterrows()
                ]

                folium.PolyLine(
                    fallback_coordinates,
                    color=vehicle_color,
                    weight=4,
                    opacity=0.7,
                    tooltip=(
                        f"รถคันที่ {vehicle_number} "
                        "(เส้นตรงสำรอง)"
                    ),
                ).add_to(route_map)

            # Marker คลัง
            if vehicle_index == 0:
                depot_row = weighted_df.iloc[0]
                folium.Marker(
                    location=[depot_row["Lat"], depot_row["Lon"]],
                    icon=folium.Icon(
                        color="black",
                        icon="home",
                        prefix="fa",
                    ),
                    popup=f"คลัง: {depot_row['ชื่อสถานที่']}",
                    tooltip="คลังสินค้า",
                ).add_to(route_map)

            # Marker จุดส่งของรถแต่ละคัน
            for route_position in range(
                1,
                len(optimized_route_df) - 1,
            ):
                row = optimized_route_df.iloc[route_position]

                marker_html = f"""
                <div style="
                    font-size: 10pt;
                    font-weight: bold;
                    color: white;
                    background-color: {vehicle_color};
                    border-radius: 50%;
                    width: 30px;
                    height: 30px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    border: 2px solid white;
                    box-shadow: 0 0 3px black;">
                    {vehicle_number}-{route_position}
                </div>
                """

                folium.Marker(
                    location=[row["Lat"], row["Lon"]],
                    icon=folium.DivIcon(html=marker_html),
                    popup=(
                        f"รถคันที่ {vehicle_number}<br>"
                        f"ลำดับที่ {route_position}<br>"
                        f"{row['ชื่อสถานที่']}<br>"
                        f"น้ำหนัก {row['น้ำหนัก(กก.)']:.2f} กก."
                    ),
                ).add_to(route_map)

        st.subheader("📊 7. สรุปการใช้รถและต้นทุนน้ำมัน")

        st.dataframe(
            pd.DataFrame(route_summary_rows),
            use_container_width=True,
        )

        fuel_metric_col1, fuel_metric_col2, fuel_metric_col3, fuel_metric_col4 = st.columns(4)
        fuel_metric_col1.metric(
            "น้ำมันขณะวิ่งรวม",
            f"{total_driving_fuel_liters_all_vehicles:.2f} ลิตร",
        )
        fuel_metric_col2.metric(
            "น้ำมันขณะจอดรวม",
            f"{total_idling_fuel_liters_all_vehicles:.2f} ลิตร",
        )
        fuel_metric_col3.metric(
            "น้ำมันรวมทุกคัน",
            f"{total_fuel_liters_all_vehicles:.2f} ลิตร",
        )
        fuel_metric_col4.metric(
            "ต้นทุนน้ำมันรวม",
            f"{total_fuel_cost_all_vehicles:,.2f} บาท",
        )

        st.caption(
            f"ราคาที่ใช้คำนวณ {float(fuel_price):.2f} บาท/ลิตร"
        )

        if assignment_summary_rows:
            st.subheader("📦 จุดส่งที่มอบหมายให้รถแต่ละคัน")

            st.dataframe(
                pd.DataFrame(assignment_summary_rows),
                use_container_width=True,
            )

        st.subheader("🕒 8. ตารางเส้นทางและ ETA")

        st.dataframe(
            pd.DataFrame(all_schedule_rows),
            use_container_width=True,
        )

        st.subheader("🗺️ 9. แผนที่เส้นทางแยกตามรถ")

        st_folium(
            route_map,
            width=1200,
            height=600,
        )

    except Exception as error:
        st.exception(error)
