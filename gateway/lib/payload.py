# -*- coding: utf-8 -*-
"""
按《网关上传json.txt》的约定组装上报数据。

纯 Python，不依赖 machine 模块，可在 PC 上验证。
"""

# 文档规定的 9 个数据项，没采到的值填 None（JSON 里就是 null）
DATA_KEYS = (
    "soil_temperature",
    "soil_humidity",
    "nitrogen",
    "phosphorus",
    "potassium",
    "ph",
    "salinity",
    "air_temperature",
    "air_humidity",
)


def _round(value, ndigits):
    if value is None:
        return None
    try:
        return round(float(value), ndigits)
    except (TypeError, ValueError):
        return None


def _empty_data():
    data = {}
    for key in DATA_KEYS:
        data[key] = None
    return data


def build_payload(meta, timestamp_ms, latitude, longitude, air, soil):
    """
    参数：
        meta: dict，键为 gateway_id / gateway_unique / air_id / air_type /
              air_type_name / soil_id / soil_type / soil_type_name
        timestamp_ms: 整包上报时间，Unix 毫秒
        latitude/longitude: WGS84 十进制度；无定位时传 0.0
        air:  空气传感器读数 dict 或 None
        soil: 土壤传感器读数 dict 或 None

    返回：可直接 json.dumps 的 dict。
    """
    air_data = _empty_data()
    if air:
        air_data["air_temperature"] = _round(air.get("air_temperature"), 1)
        air_data["air_humidity"] = _round(air.get("air_humidity"), 1)

    soil_data = _empty_data()
    if soil:
        soil_data["soil_temperature"] = _round(soil.get("soil_temperature"), 1)
        soil_data["soil_humidity"] = _round(soil.get("soil_humidity"), 1)
        soil_data["nitrogen"] = _round(soil.get("nitrogen"), 1)
        soil_data["phosphorus"] = _round(soil.get("phosphorus"), 1)
        soil_data["potassium"] = _round(soil.get("potassium"), 1)
        soil_data["ph"] = _round(soil.get("ph"), 1)
        soil_data["salinity"] = _round(soil.get("salinity"), 2)

    unique = meta["gateway_unique"]
    sensors = [
        {
            "sensor_id": meta["air_id"],
            # 传感器唯一码 = 网关唯一码 + 4 位顺序号
            "unique_code": "%s-0001" % unique,
            "type": meta["air_type"],
            "type_name": meta["air_type_name"],
            "data": air_data,
        },
        {
            "sensor_id": meta["soil_id"],
            "unique_code": "%s-0002" % unique,
            "type": meta["soil_type"],
            "type_name": meta["soil_type_name"],
            "data": soil_data,
        },
    ]

    return {
        "timestamp": int(timestamp_ms),
        "gateway": {
            "gateway_id": meta["gateway_id"],
            "unique_code": unique,
            "sensor_count": len(sensors),
            "location": {
                "longitude": float(longitude),
                "latitude": float(latitude),
            },
        },
        "sensors": sensors,
    }
